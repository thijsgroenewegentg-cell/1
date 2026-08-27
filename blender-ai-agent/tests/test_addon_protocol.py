"""
Integration test for the REAL addon.py server code, using a tiny fake `bpy`
module instead of Blender. Verifies socket framing, the main-thread queue,
exec/stdout capture, scene_info and shutdown over a real TCP connection.
Run with:  python3 tests/test_addon_protocol.py
"""

import os
import sys
import time
import types
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --- Build a minimal fake bpy before importing the add-on -------------------

class _Dummy:
    def __init__(self, **kw):
        self.__dict__.update(kw)


fake_bpy = types.ModuleType("bpy")
fake_bpy.app = types.SimpleNamespace(
    version_string="4.2.0-fake",
    timers=types.SimpleNamespace(register=lambda *a, **k: None,
                                 is_registered=lambda *a: False,
                                 unregister=lambda *a: None),
)
fake_bpy.context = types.SimpleNamespace(
    scene=_Dummy(
        name="Scene",
        objects=[],
        camera=None,
        frame_current=1, frame_start=1, frame_end=250,
        render=_Dummy(engine="BLENDER_EEVEE_NEXT", fps=24,
                      resolution_x=1920, resolution_y=1080,
                      resolution_percentage=100, filepath="/tmp/x.png"),
    )
)
fake_bpy.data = types.SimpleNamespace(objects=[], materials=[], collections=[])
fake_bpy.ops = types.SimpleNamespace(
    ed=types.SimpleNamespace(
        undo_push=lambda **kw: None,
        undo=lambda: None,
        redo=lambda: None,
    ),
    wm=types.SimpleNamespace(
        save_as_mainfile=lambda **kw: None,
        stl_export=lambda **kw: None,
        obj_export=lambda **kw: None,
        fbx_export=lambda **kw: None,
    ),
)


class _Operator:
    @classmethod
    def poll(cls, context):
        return True


class _Panel:
    pass


fake_bpy.types = types.SimpleNamespace(
    Operator=_Operator,
    Panel=_Panel,
    Scene=_Dummy(),
)
fake_bpy.utils = types.SimpleNamespace(
    register_class=lambda cls: None,
    unregister_class=lambda cls: None,
)
fake_bpy.props = types.SimpleNamespace(
    IntProperty=lambda **kw: 0,
)
sys.modules["bpy"] = fake_bpy

import addon  # noqa: E402  (imports the fake bpy)


class RawBridge:
    """Minimal JSON-lines client for talking to the addon server directly."""
    def __init__(self, host, port, timeout=10):
        import socket as _sock
        self.s = _sock.create_connection((host, port), timeout=timeout)
        self.s.settimeout(timeout)
        self.buf = b""
        self.id = 0

    def call(self, cmd, **args):
        import json as _json
        self.id += 1
        self.s.sendall((_json.dumps({"id": self.id, "cmd": cmd, "args": args}) + "\n").encode())
        while b"\n" not in self.buf:
            self.buf += self.s.recv(65536)
        line, self.buf = self.buf.split(b"\n", 1)
        return _json.loads(line.decode())

    def close(self):
        self.s.close()


def main():
    # Start the add-on's real server thread on an ephemeral port.
    addon._state["port"] = 0
    addon._state["running"] = True
    server_thread = threading.Thread(target=addon._server_thread, daemon=True)
    server_thread.start()
    for _ in range(50):
        if addon._state["server"] is not None:
            break
        time.sleep(0.02)
    port = addon._state["server"].getsockname()[1]

    # Emulate Blender's main-thread timer that drains the request queue.
    stop_driver = threading.Event()

    def driver():
        while not stop_driver.is_set():
            addon._process_queue()
            time.sleep(0.02)

    threading.Thread(target=driver, daemon=True).start()

    try:
        bridge = RawBridge("127.0.0.1", port, timeout=10)

        ping = bridge.call("ping")
        assert ping["ok"] and ping["result"]["blender"] == "4.2.0-fake", ping

        reply = bridge.call("exec", code="print('hello from', 1 + 1)")
        assert reply["ok"], reply
        assert reply["result"]["stdout"].strip() == "hello from 2", reply["result"]

        # code inside Blender can import bpy and sees the live module
        reply = bridge.call("exec", code="import bpy\nprint('bpy version:', bpy.app.version_string)")
        assert "4.2.0-fake" in reply["result"]["stdout"], reply["result"]

        # persistent namespace across calls
        bridge.call("exec", code="message = 'persisted'")
        reply = bridge.call("exec", code="print(message)")
        assert reply["result"]["stdout"].strip() == "persisted"

        # errors come back as tracebacks
        reply = bridge.call("exec", code="1/0")
        assert reply["ok"] and "ZeroDivisionError" in reply["result"]["error"]

        info = bridge.call("scene_info")
        assert info["ok"] and info["result"]["scene"] == "Scene"
        assert info["result"]["render_engine"] == "BLENDER_EEVEE_NEXT"

        # save: writes the .blend path through (fake bpy accepts it)
        import tempfile
        blend_path = os.path.join(tempfile.gettempdir(), "agent_test_scene.blend")
        saved = bridge.call("save", filepath=blend_path)
        assert saved["ok"] and saved["result"]["saved"] and saved["result"]["filepath"].endswith(".blend")

        # export: STL via the fake bpy.ops.wm.stl_export
        stl_path = os.path.join(tempfile.gettempdir(), "agent_test_model.stl")
        exported = bridge.call("export", filepath=stl_path, format="STL")
        assert exported["ok"] and exported["result"]["exported"] and exported["result"]["format"] == "STL"
        # bad format is reported cleanly
        bad_fmt = bridge.call("export", filepath="/tmp/x", format="WRL")
        assert not bad_fmt["ok"] or "Unsupported" in str(bad_fmt)

        # unknown command is a protocol-level failure, not a crash
        bad = bridge.call("not_a_command")
        assert not bad["ok"] and "Unknown command" in bad["error"]

        shutdown = bridge.call("shutdown")
        assert shutdown["ok"] and shutdown["result"]["shutting_down"]
        bridge.close()
    finally:
        stop_driver.set()
        addon._state["running"] = False

    print("PASS: addon.py server speaks the protocol over a real TCP socket")
    print("PASS: exec captures stdout and tracebacks; namespace persists")
    print("PASS: scene_info / ping / unknown-command / shutdown all behave")
    print("\nAll add-on protocol tests passed.")


if __name__ == "__main__":
    main()

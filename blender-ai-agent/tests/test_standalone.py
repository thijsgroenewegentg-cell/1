"""
Smoke test for bridge_standalone.py with a fake bpy: verifies it imports,
parses --port arguments and starts the add-on server without an add-on install.
Run with: python3 tests/test_standalone.py
"""

import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _Dummy:
    def __init__(self, **kw):
        self.__dict__.update(kw)


fake_bpy = types.ModuleType("bpy")

_timers = []
fake_bpy.app = types.SimpleNamespace(
    version_string="4.2.0-fake",
    background=True,
    timers=types.SimpleNamespace(
        register=lambda fn, **kw: _timers.append(fn),
        is_registered=lambda fn: fn in _timers,
        unregister=lambda fn: _timers.remove(fn) if fn in _timers else None,
    ),
)
fake_bpy.context = types.SimpleNamespace(
    scene=_Dummy(name="Scene", objects=[], camera=None,
                 frame_current=1, frame_start=1, frame_end=250,
                 render=_Dummy(engine="BLENDER_EEVEE_NEXT", fps=24,
                               resolution_x=1920, resolution_y=1080,
                               resolution_percentage=100, filepath="/tmp/x.png"))
)
fake_bpy.data = types.SimpleNamespace(objects=[], materials=[], collections=[])


class _Operator:
    @classmethod
    def poll(cls, context):
        return True


fake_bpy.types = types.SimpleNamespace(Operator=_Operator,
                                       Panel=type("Panel", (), {}),
                                       Scene=_Dummy())
fake_bpy.utils = types.SimpleNamespace(register_class=lambda cls: None,
                                       unregister_class=lambda cls: None)
fake_bpy.props = types.SimpleNamespace(IntProperty=lambda **kw: 0)
fake_bpy.ops = types.SimpleNamespace(
    ed=types.SimpleNamespace(undo_push=lambda **kw: None,
                             undo=lambda: None, redo=lambda: None),
    wm=types.SimpleNamespace(save_as_mainfile=lambda **kw: None),
)
sys.modules["bpy"] = fake_bpy

import bridge_standalone as bs  # noqa: E402
import addon                     # noqa: E402
import agent                     # noqa: E402


def main():
    # --- argument parsing -------------------------------------------------
    old_argv = sys.argv
    sys.argv = ["blender", "--background", "--python", "x.py", "--", "--port", "11122"]
    assert bs._parse_args() == 11122
    sys.argv = ["blender"]  # no "--" section -> default port
    assert bs._parse_args() == 9876
    sys.argv = old_argv

    # --- start the bridge and drive it like a real agent ------------------
    # Use an ephemeral port by patching _parse_args.
    bs._parse_args = lambda: 0
    bs._start_bridge()

    # The standalone script registered the processing timer.
    assert "addon" in sys.modules
    assert addon._process_queue in _timers, "main-thread timer must be registered"

    for _ in range(50):
        if addon._state["server"] is not None:
            break
        time.sleep(0.02)
    port = addon._state["server"].getsockname()[1]

    # Emulate Blender's main thread draining the queue.
    stop = threading_mod = __import__("threading")
    done = threading_mod.Event()

    def driver():
        while not done.is_set():
            addon._process_queue()
            time.sleep(0.02)

    threading_mod.Thread(target=driver, daemon=True).start()

    try:
        bridge = agent.BlenderBridge("127.0.0.1", port, timeout=10)
        ping = bridge.call("ping")
        assert ping["ok"] and ping["result"]["blender"] == "4.2.0-fake", ping
        reply = bridge.call("exec", code="print('standalone works')")
        assert reply["result"]["stdout"].strip() == "standalone works"
        bridge.close()
    finally:
        done.set()
        addon._state["running"] = False

    print("PASS: standalone bridge starts without add-on install and serves agents")


if __name__ == "__main__":
    main()
    print("\nStandalone bridge test passed.")

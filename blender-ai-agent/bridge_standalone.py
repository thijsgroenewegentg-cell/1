# SPDX-License-Identifier: MIT
#
# Standalone launcher for the AI Agent Bridge - no add-on installation needed.
#
# Launch Blender with this script and the bridge server starts automatically,
# in both the normal GUI and background (headless) mode:
#
#   blender --python bridge_standalone.py
#
#   blender --background --python bridge_standalone.py -- --port 9876
#
# Anything after "--" is passed to this script (use that in --background mode
# to set a different port). Then run agent.py as usual from a normal terminal.

import os
import sys

# addon.py lives next to this file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import addon  # noqa: E402  (the add-on module; safe to import outside Blender UI)

import bpy  # noqa: E402


def _parse_args():
    argv = []
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    port = 9876
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    return port


def _start_bridge():
    addon._state["port"] = _parse_args()
    addon._state["running"] = True
    addon._state["queue"] = []
    addon._state["namespace"] = {}

    import threading
    thread = threading.Thread(target=addon._server_thread, daemon=True)
    thread.start()

    if not bpy.app.timers.is_registered(addon._process_queue):
        bpy.app.timers.register(addon._process_queue, persistent=True)

    def _announce():
        srv = addon._state.get("server")
        port = srv.getsockname()[1] if srv is not None else addon._state["port"]
        print("[AI Agent Bridge] listening on 127.0.0.1:%s (background: %s)"
              % (port, bpy.app.background))
    bpy.app.timers.register(_announce, first_interval=1.0)


def register():
    # In GUI mode register the panel too; in --background there is no UI.
    try:
        addon.register()
    except Exception:
        pass
    bpy.app.timers.register(_start_bridge, first_interval=0.2)


if __name__ == "__main__":
    register()

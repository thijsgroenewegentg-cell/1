# SPDX-License-Identifier: MIT
#
# AI Agent Bridge - a Blender add-on that lets an external AI agent build
# things in Blender for you.
#
# It opens a small JSON-over-TCP server on 127.0.0.1 (localhost only - it is
# never reachable from the network/internet). The companion agent script
# (agent.py) sends Blender Python code here; the code runs on Blender's main
# thread through a timer queue, which is the thread-safe way to drive bpy.
#
# Install:  Blender > Edit > Preferences > Add-ons > Install from Disk...
#           pick this file, then tick "AI Agent Bridge".
# Use:      3D Viewport > press N > "AI Agent" tab > Start Server.

bl_info = {
    "name": "AI Agent Bridge",
    "author": "Arena Agent",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar (N) > AI Agent",
    "description": "Lets a free local AI agent build things in Blender over a localhost socket",
    "category": "3D View",
}

import contextlib
import io
import json
import os
import socket
import threading
import traceback

try:
    import bpy
except ImportError:  # allow importing/py_compile outside Blender
    bpy = None

HOST = "127.0.0.1"  # localhost only, by design

_state = {
    "running": False,
    "port": 9876,
    "server": None,          # listening socket
    "thread": None,          # accept thread
    "client": None,          # current client socket
    "client_lock": threading.Lock(),
    "queue": [],             # (request_dict, client_socket) waiting for main thread
    "queue_lock": threading.Lock(),
    "namespace": {},         # persistent Python namespace for agent code
}


# --------------------------------------------------------------------------
# Command handlers (all run on Blender's main thread via the timer)
# --------------------------------------------------------------------------

def _cmd_ping(args):
    return {
        "blender": bpy.app.version_string,
        "scene": bpy.context.scene.name,
        "pid": __import__("os").getpid(),
    }


def _cmd_exec(args):
    code = args.get("code", "")
    if args.get("reset"):
        _state["namespace"] = {}

    ns = _state["namespace"]
    # Make the usual Blender modules available in every execution.
    import bpy as _bpy
    import math
    ns.setdefault("bpy", _bpy)
    try:
        import bmesh
        ns.setdefault("bmesh", bmesh)
    except ImportError:
        pass
    try:
        import mathutils
        ns.setdefault("mathutils", mathutils)
    except ImportError:
        pass
    ns.setdefault("math", math)

    # Push an undo step so the user can Ctrl+Z anything the agent does.
    try:
        bpy.ops.ed.undo_push(message="AI Agent step")
    except Exception:
        pass

    stdout = io.StringIO()
    error = None
    try:
        with contextlib.redirect_stdout(stdout):
            exec(compile(code, "<agent_code>", "exec"), ns)
    except Exception:
        error = traceback.format_exc()

    return {"stdout": stdout.getvalue(), "error": error}


def _cmd_scene_info(args):
    scene = bpy.context.scene
    objects = []
    for obj in scene.objects:
        mats = []
        mats_slot = getattr(obj.data, "materials", None)
        if mats_slot is not None:
            mats = [m.name for m in mats_slot if m is not None]
        objects.append({
            "name": obj.name,
            "type": obj.type,
            "location": [round(v, 3) for v in obj.location],
            "rotation_deg": [round(v * 57.2957795, 2) for v in obj.rotation_euler],
            "scale": [round(v, 3) for v in obj.scale],
            "dimensions": [round(v, 3) for v in obj.dimensions],
            "materials": mats,
        })
    return {
        "blender": bpy.app.version_string,
        "scene": scene.name,
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "render_engine": scene.render.engine,
        "fps": scene.render.fps,
        "camera": scene.camera.name if scene.camera else None,
        "objects": objects,
        "materials": [m.name for m in bpy.data.materials],
        "collections": [c.name for c in bpy.data.collections],
        "objects_in_file": len(bpy.data.objects),
    }


def _cmd_render(args):
    scene = bpy.context.scene
    if scene.camera is None:
        return {"error": "No camera in the scene. Add one before rendering."}

    filepath = args.get("filepath")
    if not filepath:
        import tempfile
        import os
        fd, filepath = tempfile.mkstemp(prefix="blender_agent_", suffix=".png")
        os.close(fd)

    old_path = scene.render.filepath
    old_x = scene.render.resolution_x
    old_y = scene.render.resolution_y
    old_pct = scene.render.resolution_percentage
    try:
        scene.render.filepath = filepath
        if args.get("res_x"):
            scene.render.resolution_x = int(args["res_x"])
        if args.get("res_y"):
            scene.render.resolution_y = int(args["res_y"])
        if args.get("res_percentage"):
            scene.render.resolution_percentage = int(args["res_percentage"])
        elif not args.get("res_x") and not args.get("res_y"):
            scene.render.resolution_percentage = 50  # fast preview by default
        bpy.ops.render.render(write_still=True)
    except Exception:
        return {"error": traceback.format_exc()}
    finally:
        scene.render.filepath = old_path
        scene.render.resolution_x = old_x
        scene.render.resolution_y = old_y
        scene.render.resolution_percentage = old_pct

    import os
    return {"filepath": os.path.abspath(filepath)}


def _cmd_undo(args):
    try:
        bpy.ops.ed.undo()
        return {"ok": True}
    except Exception:
        return {"error": traceback.format_exc()}


def _cmd_redo(args):
    try:
        bpy.ops.ed.redo()
        return {"ok": True}
    except Exception:
        return {"error": traceback.format_exc()}


def _cmd_save(args):
    filepath = args.get("filepath")
    if not filepath:
        return {"error": "save requires a filepath (absolute path ending in .blend)"}
    filepath = os.path.abspath(os.path.expanduser(filepath))
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        bpy.ops.wm.save_as_mainfile(filepath=filepath)
    except Exception:
        return {"error": traceback.format_exc()}
    return {"filepath": filepath, "saved": True}


def _cmd_export(args):
    filepath = args.get("filepath")
    fmt = (args.get("format") or "").upper()
    if not filepath:
        return {"error": "export requires a filepath"}
    filepath = os.path.abspath(os.path.expanduser(filepath))
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Map format -> extension, export kwargs, and candidate operators
    # (Blender moved FBX/OBJ/STL between wm and export_scene across versions).
    formats = {
        "GLB":  ("glb", {"export_format": 'GLB'},
                 [("export_scene", "gltf")]),
        "GLTF": ("gltf", {},
                 [("export_scene", "gltf")]),
        "STL":  ("stl", {},
                 [("wm", "stl_export"), ("export_mesh", "stl")]),
        "FBX":  ("fbx", {},
                 [("wm", "fbx_export"), ("export_scene", "fbx")]),
        "OBJ":  ("obj", {},
                 [("wm", "obj_export"), ("export_scene", "obj")]),
    }
    ext, kwargs, candidates = formats.get(fmt, (None, None, None))
    if ext is None:
        return {"error": "Unsupported export format %r. Use GLB, GLTF, STL, FBX or OBJ." % fmt}
    if not filepath.lower().endswith("." + ext):
        filepath += "." + ext

    last_error = None
    for category, op_name in candidates:
        category_obj = getattr(bpy.ops, category, None)
        operator = getattr(category_obj, op_name, None) if category_obj else None
        if operator is None:
            continue
        try:
            operator(filepath=filepath, **kwargs)
            return {"filepath": filepath, "format": fmt, "exported": True}
        except Exception as exc:
            last_error = "%s.%s: %s" % (category, op_name, exc)

    return {"error": "Could not export %s. Last attempt: %s\n%s"
                     % (fmt, last_error, traceback.format_exc())}


def _cmd_reset_namespace(args):
    _state["namespace"] = {}
    return {"ok": True}


def _cmd_shutdown(args):
    _state["running"] = False
    srv = _state.get("server")
    if srv:
        try:
            srv.close()
        except OSError:
            pass
    return {"ok": True, "shutting_down": True}


_COMMANDS = {
    "ping": _cmd_ping,
    "exec": _cmd_exec,
    "scene_info": _cmd_scene_info,
    "render": _cmd_render,
    "save": _cmd_save,
    "export": _cmd_export,
    "undo": _cmd_undo,
    "redo": _cmd_redo,
    "reset_namespace": _cmd_reset_namespace,
    "shutdown": _cmd_shutdown,
}


def _dispatch(request):
    """Run one request on the main thread; always returns a reply dict."""
    rid = request.get("id")
    cmd = request.get("cmd")
    args = request.get("args") or {}
    handler = _COMMANDS.get(cmd)
    if handler is None:
        return {"id": rid, "ok": False, "error": "Unknown command: %r" % cmd}
    try:
        result = handler(args)
        return {"id": rid, "ok": True, "result": result}
    except Exception:
        return {"id": rid, "ok": False, "error": traceback.format_exc()}


# --------------------------------------------------------------------------
# Socket server (background threads; bpy is never touched here)
# --------------------------------------------------------------------------

def _reader_thread(conn):
    buf = b""
    while _state["running"]:
        try:
            chunk = conn.recv(65536)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line.decode("utf-8"))
            except Exception as exc:
                request = {"id": None, "cmd": "__parse_error__", "args": {"error": str(exc)}}
            with _state["queue_lock"]:
                _state["queue"].append((request, conn))

    with _state["client_lock"]:
        if _state["client"] is conn:
            _state["client"] = None
    try:
        conn.close()
    except OSError:
        pass


def _server_thread():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, _state["port"]))
    srv.listen(1)
    srv.settimeout(0.5)
    _state["server"] = srv

    while _state["running"]:
        try:
            conn, _addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        with _state["client_lock"]:
            old = _state["client"]
            _state["client"] = conn
        if old is not None:
            try:
                old.close()
            except OSError:
                pass

        reader = threading.Thread(target=_reader_thread, args=(conn,), daemon=True)
        reader.start()

    try:
        srv.close()
    except OSError:
        pass


def _process_queue():
    """Blender main-thread timer: execute queued requests safely."""
    if not _state["running"]:
        return None  # unregister this timer

    try:
        while True:
            with _state["queue_lock"]:
                if not _state["queue"]:
                    break
                request, conn = _state["queue"].pop(0)

            if request.get("cmd") == "__parse_error__":
                reply = {"id": request.get("id"), "ok": False,
                         "error": "Invalid JSON: %s" % request["args"]["error"]}
            else:
                reply = _dispatch(request)

            try:
                conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
            except OSError:
                pass

            if request.get("cmd") == "shutdown":
                _state["running"] = False
                with _state["client_lock"]:
                    client = _state["client"]
                if client is not None:
                    try:
                        client.close()
                    except OSError:
                        pass
                return None
    except Exception:
        traceback.print_exc()

    return 0.05  # tick again in 50 ms


# --------------------------------------------------------------------------
# Blender UI
# --------------------------------------------------------------------------

if bpy is not None:

    class AIAGENT_OT_start(bpy.types.Operator):
        bl_idname = "aiagent.start_server"
        bl_label = "Start AI Agent Server"
        bl_description = "Start the localhost socket server so agent.py can drive Blender"

        def execute(self, context):
            if _state["running"]:
                self.report({'WARNING'}, "AI Agent server is already running")
                return {'CANCELLED'}

            _state["port"] = int(context.scene.ai_agent_port)
            _state["running"] = True
            _state["namespace"] = {}
            _state["queue"] = []

            thread = threading.Thread(target=_server_thread, daemon=True)
            _state["thread"] = thread
            thread.start()

            if not bpy.app.timers.is_registered(_process_queue):
                bpy.app.timers.register(_process_queue, persistent=True)

            self.report({'INFO'}, "AI Agent server listening on %s:%d" % (HOST, _state["port"]))
            return {'FINISHED'}


    class AIAGENT_OT_stop(bpy.types.Operator):
        bl_idname = "aiagent.stop_server"
        bl_label = "Stop AI Agent Server"
        bl_description = "Stop the localhost socket server"

        def execute(self, context):
            _state["running"] = False
            srv = _state.get("server")
            if srv is not None:
                try:
                    srv.close()
                except OSError:
                    pass
            with _state["client_lock"]:
                client = _state["client"]
            if client is not None:
                try:
                    client.close()
                except OSError:
                    pass
            if bpy.app.timers.is_registered(_process_queue):
                bpy.app.timers.unregister(_process_queue)
            self.report({'INFO'}, "AI Agent server stopped")
            return {'FINISHED'}


    class AIAGENT_PT_panel(bpy.types.Panel):
        bl_label = "AI Agent"
        bl_idname = "AIAGENT_PT_panel"
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'UI'
        bl_category = "AI Agent"

        def draw(self, context):
            layout = self.layout
            layout.prop(context.scene, "ai_agent_port", text="Port")

            if _state["running"]:
                layout.label(text="Running on port %d" % _state["port"], icon='CHECKMARK')
                layout.operator("aiagent.stop_server", icon='PAUSE')
            else:
                layout.label(text="Stopped", icon='X')
                layout.operator("aiagent.start_server", icon='PLAY')

            layout.separator()
            layout.label(text="Then run on your computer:")
            box = layout.box()
            box.label(text='python agent.py "your idea"')
            layout.label(text="Setup guide: see README.md", icon='INFO')


    classes = (
        AIAGENT_OT_start,
        AIAGENT_OT_stop,
        AIAGENT_PT_panel,
    )


def register():
    if bpy is None:
        return
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ai_agent_port = bpy.props.IntProperty(
        name="AI Agent Port",
        description="TCP port for the AI Agent bridge (localhost only)",
        default=9876, min=1024, max=65535,
    )


def unregister():
    if bpy is None:
        return
    _state["running"] = False
    srv = _state.get("server")
    if srv is not None:
        try:
            srv.close()
        except OSError:
            pass
    if bpy.app.timers.is_registered(_process_queue):
        bpy.app.timers.unregister(_process_queue)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ai_agent_port


if __name__ == "__main__":
    register()

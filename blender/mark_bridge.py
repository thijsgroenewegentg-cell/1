"""MARK Bridge Blender add-on.

Install through Edit > Preferences > Add-ons > Install, enable it, enter the
same value as MARK_BLENDER_TOKEN in the add-on panel or preferences, then click
Start. The server binds only to 127.0.0.1 and exposes
named, allowlisted scene operations—not arbitrary Python or bpy evaluation.
"""
from __future__ import annotations

import hmac
import json
import os
import queue
import socketserver
import threading
from pathlib import Path

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel

bl_info = {
    "name": "MARK Local Bridge",
    "author": "MARK",
    "version": (1, 0, 0),
    "blender": (3, 3, 0),
    "location": "View3D > Sidebar > MARK",
    "description": "Authenticated loopback bridge for safe MARK scene operations",
    "category": "3D View",
}

_HOST = "127.0.0.1"
_requests: queue.Queue = queue.Queue()
_server = None
_server_thread = None


def _preferences():
    addon = bpy.context.preferences.addons.get(__name__)
    return addon.preferences if addon else None


def _token() -> str:
    prefs = _preferences()
    return (os.environ.get("MARK_BLENDER_TOKEN", "").strip()
            or (prefs.token.strip() if prefs else ""))


def _port() -> int:
    prefs = _preferences()
    value = prefs.port if prefs else 8765
    return max(1024, min(65535, int(value)))


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(2_000_001)
            if len(line) > 2_000_000:
                self._send({"ok": False, "error": "Request too large."})
                return
            request = json.loads(line.decode("utf-8"))
            response_queue: queue.Queue = queue.Queue(maxsize=1)
            _requests.put((request, response_queue))
            response = response_queue.get(timeout=30)
            self._send(response)
        except Exception as exc:
            self._send({"ok": False, "error": f"Bridge request failed: {exc}"})

    def _send(self, value: dict):
        try:
            self.wfile.write((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _start_server() -> tuple[bool, str]:
    global _server, _server_thread
    if _server is not None:
        return True, f"MARK Bridge already listening on {_HOST}:{_port()}"
    if not _token():
        return False, "Enter a bridge token in MARK Bridge preferences or set MARK_BLENDER_TOKEN."
    try:
        _server = _Server((_HOST, _port()), _Handler)
        _server_thread = threading.Thread(target=_server.serve_forever, daemon=True, name="mark-blender-bridge")
        _server_thread.start()
        return True, f"MARK Bridge listening on {_HOST}:{_port()}"
    except Exception as exc:
        _server = None
        return False, f"Could not start MARK Bridge: {exc}"


def _stop_server() -> tuple[bool, str]:
    global _server, _server_thread
    if _server is None:
        return True, "MARK Bridge is already stopped."
    server, _server_thread = _server, None
    _server = None
    try:
        server.shutdown()
        server.server_close()
    except Exception as exc:
        return False, f"Could not stop MARK Bridge: {exc}"
    return True, "MARK Bridge stopped."


def _vec(value, default, length=3):
    if not isinstance(value, (list, tuple)) or len(value) != length:
        return list(default)
    try:
        return [float(value[i]) for i in range(length)]
    except (TypeError, ValueError):
        return list(default)


def _object(name: str):
    value = str(name or "").strip()
    if not value or len(value) > 128 or "\n" in value:
        return None
    return bpy.data.objects.get(value)


def _status(params):
    scene = bpy.context.scene
    return {
        "scene": scene.name,
        "frame": scene.frame_current,
        "engine": scene.render.engine,
        "objects": len(scene.objects),
        "active": bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else "",
    }


def _list_objects(params):
    try:
        limit = max(1, min(200, int(params.get("limit", 100))))
    except (TypeError, ValueError):
        limit = 100
    return [{"name": obj.name, "type": obj.type} for obj in list(bpy.context.scene.objects)[:limit]]


def _inspect_object(params):
    obj = _object(params.get("object_name"))
    if obj is None:
        raise ValueError("Named Blender object was not found.")
    return {
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "rotation": list(obj.rotation_euler),
        "scale": list(obj.scale),
        "dimensions": list(obj.dimensions),
        "materials": [mat.name for mat in obj.data.materials] if hasattr(obj.data, "materials") else [],
    }


def _create_primitive(params, kind):
    name = str(params.get("object_name") or f"MARK_{kind}").strip()[:128]
    location = _vec(params.get("location"), (0.0, 0.0, 0.0))
    scale = _vec(params.get("scale"), (1.0, 1.0, 1.0))
    operators = {
        "cube": bpy.ops.mesh.primitive_cube_add,
        "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
        "cylinder": bpy.ops.mesh.primitive_cylinder_add,
    }
    operators[kind](location=location)
    obj = bpy.context.object
    obj.name = name or obj.name
    obj.scale = scale
    bpy.context.view_layer.objects.active = obj
    return {"name": obj.name, "type": obj.type}


def _create_camera(params):
    name = str(params.get("object_name") or "MARK_Camera").strip()[:128]
    data = bpy.data.cameras.new(name=name or "MARK_Camera")
    obj = bpy.data.objects.new(name or "MARK_Camera", data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = _vec(params.get("location"), (7.0, -7.0, 5.0))
    obj.rotation_euler = _vec(params.get("rotation"), (0.0, 0.0, 0.0))
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return {"name": obj.name, "type": obj.type}


def _create_light(params):
    name = str(params.get("object_name") or "MARK_Light").strip()[:128]
    light_type = str(params.get("light_type", "POINT")).upper().strip()
    if light_type not in {"POINT", "SUN", "AREA", "SPOT"}:
        raise ValueError("light_type must be POINT, SUN, AREA or SPOT.")
    data = bpy.data.lights.new(name=name or "MARK_Light", type=light_type)
    try:
        data.energy = max(0.0, min(100000.0, float(params.get("energy", 1000.0))))
    except (TypeError, ValueError):
        data.energy = 1000.0
    if params.get("color") is not None:
        data.color = _color(params.get("color"))[:3]
    obj = bpy.data.objects.new(name or "MARK_Light", data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = _vec(params.get("location"), (4.0, -4.0, 5.0))
    obj.rotation_euler = _vec(params.get("rotation"), (0.0, 0.0, 0.0))
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    return {"name": obj.name, "type": obj.type, "light_type": light_type}


def _add_modifier(params):
    obj = _object(params.get("object_name"))
    if obj is None:
        raise ValueError("Named Blender object was not found.")
    modifier_type = str(params.get("modifier_type", "BEVEL")).upper().strip()
    allowed = {"BEVEL", "SUBSURF", "SOLIDIFY", "ARRAY", "MIRROR", "DECIMATE"}
    if modifier_type not in allowed:
        raise ValueError("Modifier type is not allowlisted.")
    name = str(params.get("modifier_name") or f"MARK_{modifier_type.title()}").strip()[:64]
    modifier = obj.modifiers.new(name=name or "MARK_Modifier", type=modifier_type)
    try:
        if modifier_type == "BEVEL":
            modifier.width = max(0.0, min(10.0, float(params.get("amount", 0.1))))
            modifier.segments = max(1, min(12, int(params.get("segments", 2))))
        elif modifier_type == "SUBSURF":
            modifier.levels = max(0, min(4, int(params.get("levels", 1))))
            modifier.render_levels = modifier.levels
        elif modifier_type == "SOLIDIFY":
            modifier.thickness = max(-10.0, min(10.0, float(params.get("amount", 0.01))))
        elif modifier_type == "ARRAY":
            modifier.count = max(1, min(20, int(params.get("count", 2))))
        elif modifier_type == "DECIMATE":
            modifier.ratio = max(0.01, min(1.0, float(params.get("amount", 0.5))))
    except (TypeError, ValueError) as exc:
        obj.modifiers.remove(modifier)
        raise ValueError("Modifier values were invalid.") from exc
    return {"object": obj.name, "modifier": modifier.name, "type": modifier_type}


def _set_transform(params):
    obj = _object(params.get("object_name"))
    if obj is None:
        raise ValueError("Named Blender object was not found.")
    if "location" in params:
        obj.location = _vec(params.get("location"), obj.location)
    if "rotation" in params:
        obj.rotation_euler = _vec(params.get("rotation"), obj.rotation_euler)
    if "scale" in params:
        obj.scale = _vec(params.get("scale"), obj.scale)
    return {"name": obj.name, "location": list(obj.location), "rotation": list(obj.rotation_euler), "scale": list(obj.scale)}


def _color(value):
    raw = str(value or "").strip().lstrip("#")
    if len(raw) not in {6, 8}:
        raise ValueError("Color must be #RRGGBB or #RRGGBBAA.")
    try:
        values = [int(raw[i:i + 2], 16) / 255.0 for i in range(0, len(raw), 2)]
    except ValueError as exc:
        raise ValueError("Color must be hexadecimal.") from exc
    return tuple(values if len(values) == 4 else values + [1.0])


def _set_material(params):
    obj = _object(params.get("object_name"))
    if obj is None:
        raise ValueError("Named Blender object was not found.")
    if not hasattr(obj.data, "materials"):
        raise ValueError("That object cannot receive a material.")
    material = bpy.data.materials.get(str(params.get("material_name") or f"MARK_{obj.name}"))
    if material is None:
        material = bpy.data.materials.new(name=str(params.get("material_name") or f"MARK_{obj.name}")[:128])
    material.use_nodes = True
    node = material.node_tree.nodes.get("Principled BSDF")
    if node is None:
        raise ValueError("Principled BSDF node was not found.")
    if params.get("color") is not None:
        node.inputs["Base Color"].default_value = _color(params.get("color"))
    if params.get("metallic") is not None:
        node.inputs["Metallic"].default_value = max(0.0, min(1.0, float(params["metallic"])))
    if params.get("roughness") is not None:
        node.inputs["Roughness"].default_value = max(0.0, min(1.0, float(params["roughness"])))
    obj.data.materials.clear()
    obj.data.materials.append(material)
    return {"object": obj.name, "material": material.name}


def _delete_object(params):
    obj = _object(params.get("object_name"))
    if obj is None:
        raise ValueError("Named Blender object was not found.")
    name = obj.name
    bpy.data.objects.remove(obj, do_unlink=True)
    return {"deleted": name}


def _render(params):
    bpy.ops.render.render(write_still=False)
    return {"rendered": True, "scene": bpy.context.scene.name}


def _save_blend(params):
    raw = str(params.get("path") or "").strip()
    if not raw:
        raise ValueError("A .blend path is required for save_blend.")
    path = Path(raw).expanduser().resolve()
    try:
        path.relative_to(Path.home().resolve())
    except ValueError as exc:
        raise ValueError("For safety, save_blend paths must stay under the user home folder.") from exc
    if path.suffix.lower() != ".blend":
        raise ValueError("save_blend requires a .blend filename.")
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    return {"saved": str(path)}


def _execute(request: dict) -> dict:
    if not isinstance(request, dict) or not hmac.compare_digest(str(request.get("token", "")), _token()):
        return {"ok": False, "error": "Invalid bridge token."}
    action = str(request.get("action", "")).strip().lower()
    params = request.get("parameters") if isinstance(request.get("parameters"), dict) else {}
    handlers = {
        "status": _status,
        "list_objects": _list_objects,
        "inspect_object": _inspect_object,
        "create_cube": lambda p: _create_primitive(p, "cube"),
        "create_sphere": lambda p: _create_primitive(p, "sphere"),
        "create_cylinder": lambda p: _create_primitive(p, "cylinder"),
        "create_camera": _create_camera,
        "create_light": _create_light,
        "set_transform": _set_transform,
        "set_material": _set_material,
        "add_modifier": _add_modifier,
        "delete_object": _delete_object,
        "render": _render,
        "save_blend": _save_blend,
    }
    handler = handlers.get(action)
    if handler is None:
        return {"ok": False, "error": "Unknown or disallowed Blender action."}
    try:
        return {"ok": True, "result": json.dumps(handler(params), ensure_ascii=False)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _drain():
    for _ in range(8):
        try:
            request, response_queue = _requests.get_nowait()
        except queue.Empty:
            break
        response_queue.put(_execute(request))
    return 0.05


class MARKBridgePreferences(AddonPreferences):
    bl_idname = __name__
    token: StringProperty(name="Bridge token", subtype="PASSWORD", default="")
    port: IntProperty(name="Port", default=8765, min=1024, max=65535)

    def draw(self, context):
        self.layout.prop(self, "token")
        self.layout.prop(self, "port")
        self.layout.label(text="Loopback only: 127.0.0.1")


class MARK_OT_bridge_start(Operator):
    bl_idname = "mark_bridge.start"
    bl_label = "Start MARK Bridge"

    def execute(self, context):
        ok, message = _start_server()
        self.report({"INFO" if ok else "ERROR"}, message)
        return {"FINISHED" if ok else "CANCELLED"}


class MARK_OT_bridge_stop(Operator):
    bl_idname = "mark_bridge.stop"
    bl_label = "Stop MARK Bridge"

    def execute(self, context):
        ok, message = _stop_server()
        self.report({"INFO" if ok else "ERROR"}, message)
        return {"FINISHED" if ok else "CANCELLED"}


class MARK_PT_bridge(Panel):
    bl_label = "MARK Bridge"
    bl_idname = "MARK_PT_bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MARK"

    def draw(self, context):
        layout = self.layout
        prefs = _preferences()
        if prefs:
            layout.prop(prefs, "token")
            layout.prop(prefs, "port")
        row = layout.row(align=True)
        row.operator("mark_bridge.start", icon="PLAY")
        row.operator("mark_bridge.stop", icon="PAUSE")
        layout.label(text="Running" if _server is not None else "Stopped")
        layout.label(text="127.0.0.1 only")


_CLASSES = (MARKBridgePreferences, MARK_OT_bridge_start, MARK_OT_bridge_stop, MARK_PT_bridge)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.timers.register(_drain, first_interval=0.05, persistent=True)


def unregister():
    _stop_server()
    if bpy.app.timers.is_registered(_drain):
        bpy.app.timers.unregister(_drain)
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()

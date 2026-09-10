"""MARK Bridge Blender add-on.

Install through Edit > Preferences > Add-ons > Install, enable it, enter the
same value as MARK_BLENDER_TOKEN in the add-on panel or preferences, then click
Start. The server binds only to 127.0.0.1 and exposes
named, allowlisted scene operations—not arbitrary Python or bpy evaluation. It
also exposes an MCP-compatible JSON-RPC endpoint at POST /mcp for clients that
support Model Context Protocol.
"""
from __future__ import annotations

import hmac
import json
import os
import queue
import socketserver
import threading
import uuid
from pathlib import Path

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel

bl_info = {
    "name": "MARK Local Bridge",
    "author": "MARK",
    "version": (2, 0, 0),
    "blender": (3, 3, 0),
    "location": "View3D > Sidebar > MARK",
    "description": "Authenticated loopback bridge for safe MARK scene operations",
    "category": "3D View",
}

_HOST = "127.0.0.1"
_MCP_PROTOCOL_VERSION = "2025-06-18"
_MCP_SESSION_ID = f"mark-blender-{uuid.uuid4().hex}"
_MCP_ACTIONS = (
    "status", "list_objects", "inspect_object", "create_cube", "create_sphere",
    "create_cylinder", "create_camera", "create_light", "create_collection",
    "duplicate_object", "set_transform", "set_active_camera", "look_at",
    "set_material", "add_modifier", "delete_object", "set_render_settings",
    "render", "save_blend", "scene_checkpoint", "undo",
)
_MCP_TOOL_DESCRIPTION = (
    "Authenticated MARK Blender scene tool. Use read-only actions to inspect the "
    "scene; mutations remain allowlisted and are confirmation-gated by MARK. "
    "Never send Python, bpy expressions, shell commands or arbitrary file paths."
)
_MCP_PARAMETER_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "object_name": {"type": "string"},
        "target_name": {"type": "string"},
        "new_name": {"type": "string"},
        "collection_name": {"type": "string"},
        "location": {"type": "array", "items": {"type": "number"}},
        "target_location": {"type": "array", "items": {"type": "number"}},
        "rotation": {"type": "array", "items": {"type": "number"}},
        "scale": {"type": "array", "items": {"type": "number"}},
        "dimensions": {"type": "array", "items": {"type": "number"}},
        "color": {"type": "string"},
        "material_name": {"type": "string"},
        "metallic": {"type": "number"},
        "roughness": {"type": "number"},
        "light_type": {"type": "string"},
        "energy": {"type": "number"},
        "modifier_type": {"type": "string"},
        "modifier_name": {"type": "string"},
        "amount": {"type": "number"},
        "segments": {"type": "integer"},
        "levels": {"type": "integer"},
        "count": {"type": "integer"},
        "path": {"type": "string"},
        "engine": {"type": "string"},
        "resolution": {"type": "array", "items": {"type": "integer"}},
        "samples": {"type": "integer"},
        "format": {"type": "string"},
        "limit": {"type": "integer"},
    },
}
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
    """Accept MCP Streamable HTTP plus the old one-line bridge during migration.

    MCP clients send POST /mcp with a JSON-RPC message and a standard Bearer
    token. MARK's own client also uses that transport. The legacy newline JSON
    request remains available for one release so an already-running MARK build
    can still talk to a freshly updated add-on.
    """

    def handle(self):
        try:
            first = self.rfile.readline(2_000_001)
            if len(first) > 2_000_000:
                self._send_legacy({"ok": False, "error": "Request too large."})
                return
            if first.startswith(b"POST ") or first.startswith(b"GET "):
                self._handle_http(first)
                return
            request = json.loads(first.decode("utf-8"))
            response = self._dispatch_legacy(request)
            if response is not None:
                self._send_legacy(response)
        except Exception as exc:
            if 'first' in locals() and (first.startswith(b"POST ") or first.startswith(b"GET ")):
                self._send_http(400, {"jsonrpc": "2.0", "id": None,
                                      "error": {"code": -32700, "message": str(exc)}})
            else:
                self._send_legacy({"ok": False, "error": f"Bridge request failed: {exc}"})

    def _dispatch_legacy(self, request: dict):
        response_queue: queue.Queue = queue.Queue(maxsize=1)
        _requests.put((request, response_queue))
        return response_queue.get(timeout=30)

    def _handle_http(self, first: bytes):
        if first.startswith(b"GET "):
            self._send_http(405, {"error": "MCP uses POST /mcp for this local bridge."})
            return
        headers = {}
        while True:
            line = self.rfile.readline(16_384)
            if not line or line in {b"\r\n", b"\n"}:
                break
            key, separator, value = line.decode("iso-8859-1").partition(":")
            if separator:
                headers[key.strip().lower()] = value.strip()
        try:
            length = int(headers.get("content-length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 2_000_000:
            self._send_http(400, {"jsonrpc": "2.0", "id": None,
                                  "error": {"code": -32600, "message": "Invalid request body size."}})
            return
        request = json.loads(self.rfile.read(length).decode("utf-8"))
        bearer = headers.get("authorization", "")
        transport_token = bearer[7:].strip() if bearer.lower().startswith("bearer ") else ""
        response = _mcp_request(request, transport_token)
        if response is None:
            self._send_http(202, None)
        else:
            self._send_http(200, response, session=True)

    def _send_legacy(self, value: dict):
        try:
            self.wfile.write((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()
        except Exception:
            pass

    def _send_http(self, status: int, value, session: bool = False):
        try:
            raw = b"" if value is None else (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
            headers = [
                f"HTTP/1.1 {status} OK\r\n",
                "Content-Type: application/json\r\n",
                f"Content-Length: {len(raw)}\r\n",
                f"MCP-Protocol-Version: {_MCP_PROTOCOL_VERSION}\r\n",
            ]
            if session:
                headers.append(f"Mcp-Session-Id: {_MCP_SESSION_ID}\r\n")
            headers.append("Connection: close\r\n\r\n")
            self.wfile.write("".join(headers).encode("iso-8859-1") + raw)
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
    active = bpy.context.view_layer.objects.active
    selected = [obj.name for obj in list(bpy.context.selected_objects)[:50]]
    objects = [{"name": obj.name, "type": obj.type} for obj in list(scene.objects)[:100]]
    return {
        "scene": scene.name,
        "frame": scene.frame_current,
        "engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "camera": scene.camera.name if scene.camera else "",
        "objects": len(scene.objects),
        "object_summary": objects,
        "collections": [collection.name for collection in scene.collection.children],
        "active": active.name if active else "",
        "selected": selected,
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


def _create_collection(params):
    name = str(params.get("collection_name") or params.get("object_name") or "MARK_Collection").strip()[:128]
    collection = bpy.data.collections.new(name or "MARK_Collection")
    bpy.context.scene.collection.children.link(collection)
    return {"collection": collection.name}


def _duplicate_object(params):
    obj = _object(params.get("object_name"))
    if obj is None:
        raise ValueError("Named Blender object was not found.")
    copy = obj.copy()
    if getattr(obj, "data", None) is not None:
        copy.data = obj.data.copy()
    name = str(params.get("new_name") or f"{obj.name}_copy").strip()[:128]
    copy.name = name or copy.name
    collection = bpy.data.collections.get(str(params.get("collection_name") or ""))
    (collection or bpy.context.scene.collection).objects.link(copy)
    from mathutils import Vector
    copy.location = obj.location + Vector((1.0, 0.0, 0.0))
    bpy.context.view_layer.objects.active = copy
    copy.select_set(True)
    return {"source": obj.name, "duplicate": copy.name}


def _set_active_camera(params):
    obj = _object(params.get("object_name"))
    if obj is None or obj.type != "CAMERA":
        raise ValueError("Named camera object was not found.")
    bpy.context.scene.camera = obj
    return {"camera": obj.name}


def _look_at(params):
    obj = _object(params.get("object_name"))
    if obj is None:
        raise ValueError("Named Blender object was not found.")
    target = _object(params.get("target_name"))
    if target is not None:
        point = target.location
    else:
        values = params.get("target_location")
        point = _vec(values, (0.0, 0.0, 0.0))
        from mathutils import Vector
        point = Vector(point)
    direction = point - obj.location
    if direction.length == 0:
        raise ValueError("Object and target cannot be at the same location.")
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return {"object": obj.name, "target": target.name if target else list(point)}


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
    if "dimensions" in params:
        obj.dimensions = _vec(params.get("dimensions"), obj.dimensions)
    return {"name": obj.name, "location": list(obj.location), "rotation": list(obj.rotation_euler), "scale": list(obj.scale), "dimensions": list(obj.dimensions)}


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


def _set_render_settings(params):
    scene = bpy.context.scene
    engine = str(params.get("engine") or "").upper().strip()
    if engine:
        allowed = {"BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH", "CYCLES"}
        if engine not in allowed:
            raise ValueError("Render engine is not allowlisted.")
        try:
            scene.render.engine = engine
        except Exception as exc:
            raise ValueError(f"Render engine is unavailable in this Blender build: {engine}") from exc
    resolution = params.get("resolution")
    if isinstance(resolution, (list, tuple)) and len(resolution) == 2:
        try:
            scene.render.resolution_x = max(16, min(8192, int(resolution[0])))
            scene.render.resolution_y = max(16, min(8192, int(resolution[1])))
        except (TypeError, ValueError) as exc:
            raise ValueError("resolution must contain two integers.") from exc
    if params.get("samples") is not None:
        samples = max(1, min(4096, int(params["samples"])))
        if hasattr(scene, "cycles"):
            scene.cycles.samples = samples
        if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
            scene.eevee.taa_render_samples = samples
    image_format = str(params.get("format") or "").upper().strip()
    if image_format:
        if image_format not in {"PNG", "JPEG", "OPEN_EXR"}:
            raise ValueError("format must be PNG, JPEG or OPEN_EXR.")
        scene.render.image_settings.file_format = image_format
    return {
        "engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "format": scene.render.image_settings.file_format,
    }


def _render(params):
    raw = str(params.get("path") or "").strip()
    if raw:
        path = Path(raw).expanduser().resolve()
        try:
            path.relative_to(Path.home().resolve())
        except ValueError as exc:
            raise ValueError("Render paths must stay under the user home folder.") from exc
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".exr"}:
            raise ValueError("Render path must end in .png, .jpg, .jpeg or .exr.")
        path.parent.mkdir(parents=True, exist_ok=True)
        old_path = bpy.context.scene.render.filepath
        old_format = bpy.context.scene.render.image_settings.file_format
        suffix_format = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".exr": "OPEN_EXR"}[path.suffix.lower()]
        try:
            bpy.context.scene.render.filepath = str(path)
            bpy.context.scene.render.image_settings.file_format = suffix_format
            bpy.ops.render.render(write_still=True)
        finally:
            bpy.context.scene.render.filepath = old_path
            bpy.context.scene.render.image_settings.file_format = old_format
        return {"rendered": True, "scene": bpy.context.scene.name, "path": str(path)}
    bpy.ops.render.render(write_still=False)
    return {"rendered": True, "scene": bpy.context.scene.name}


def _undo(params):
    try:
        bpy.ops.ed.undo()
    except Exception as exc:
        raise RuntimeError(f"Blender undo was unavailable: {exc}") from exc
    return {"undone": True, "scene": bpy.context.scene.name}


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


def _mcp_tool_list() -> list[dict]:
    tools = [{
        "name": "blender_control",
        "description": _MCP_TOOL_DESCRIPTION,
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": list(_MCP_ACTIONS)},
                "parameters": _MCP_PARAMETER_SCHEMA,
            },
            "required": ["action"],
        },
    }]
    for action in _MCP_ACTIONS:
        tools.append({
            "name": f"blender_{action}",
            "description": f"Run the allowlisted Blender {action} operation through MARK's authenticated bridge.",
            "inputSchema": _MCP_PARAMETER_SCHEMA,
        })
    return tools


def _mcp_text_response(request_id, text: str, is_error: bool = False,
                       structured=None) -> dict:
    result = {
        "content": [{"type": "text", "text": str(text)}],
        "isError": bool(is_error),
    }
    if structured is not None:
        result["structuredContent"] = structured
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_request(request: dict, transport_token: str = ""):
    """Handle one MCP JSON-RPC message without executing Blender off-thread."""
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None,
                "error": {"code": -32600, "message": "MCP requires a JSON-RPC 2.0 request."}}
    request_id = request.get("id")
    supplied = str(transport_token or request.get("token", ""))
    if not hmac.compare_digest(supplied, _token()):
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32001, "message": "Invalid bridge token."}}

    method = str(request.get("method", "")).strip()
    if not method:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32600, "message": "MCP method is required."}}
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": _MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "MARK Blender Bridge", "version": "2.0.0"},
                "instructions": _MCP_TOOL_DESCRIPTION,
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id,
                "result": {"tools": _mcp_tool_list(), "nextCursor": None}}
    if method != "tools/call":
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": f"Unsupported MCP method: {method}"}}

    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    name = str(params.get("name", "")).strip()
    arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
    if name == "blender_control":
        action = str(arguments.get("action", "")).strip().lower().replace("-", "_")
        call_params = arguments.get("parameters") if isinstance(arguments.get("parameters"), dict) else {}
    elif name.startswith("blender_"):
        action = name[len("blender_"):].strip().lower().replace("-", "_")
        call_params = dict(arguments)
    else:
        return _mcp_text_response(request_id, f"Unknown MCP tool: {name}", True)
    if action not in _MCP_ACTIONS:
        return _mcp_text_response(request_id, "Unknown or disallowed Blender action.", True)

    # bpy may only be touched on Blender's main thread. The timer drains this
    # queue there; the network handler waits for the bounded result.
    response_queue: queue.Queue = queue.Queue(maxsize=1)
    _requests.put(({"token": _token(), "action": action, "parameters": call_params}, response_queue))
    try:
        result = response_queue.get(timeout=30)
    except queue.Empty:
        return _mcp_text_response(request_id, "Blender did not finish the MCP tool call in time.", True)
    if not result.get("ok"):
        return _mcp_text_response(request_id, result.get("error", "Blender rejected the action."), True)
    raw = str(result.get("result", ""))
    try:
        structured = json.loads(raw)
    except (TypeError, ValueError):
        structured = None
    return _mcp_text_response(request_id, raw, False, structured)


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
        "create_collection": _create_collection,
        "duplicate_object": _duplicate_object,
        "set_transform": _set_transform,
        "set_active_camera": _set_active_camera,
        "look_at": _look_at,
        "set_material": _set_material,
        "add_modifier": _add_modifier,
        "delete_object": _delete_object,
        "set_render_settings": _set_render_settings,
        "render": _render,
        "save_blend": _save_blend,
        "scene_checkpoint": _save_blend,
        "undo": _undo,
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
        layout.label(text="Running — MCP 2.0" if _server is not None else "Stopped — MCP 2.0")
        layout.label(text="127.0.0.1 only · POST /mcp")


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

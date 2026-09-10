"""Authenticated, allowlisted Blender control through the local MARK add-on."""
from __future__ import annotations

from core import confirm as confirm_gate
from core.blender_bridge import call, configuration_error, test_connection


PLUGIN = {
    "name": "blender_control",
    "description": (
        "Connect to Blender through the authenticated localhost MARK Bridge add-on. "
        "Inspect scenes and objects, create primitive meshes/cameras/lights, change "
        "transforms or materials, add allowlisted modifiers, render, save, and delete "
        "named objects. It accepts no bpy/Python "
        "code and mutating actions require confirmation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "status | list_objects | inspect_object | create_cube | create_sphere | "
                    "create_cylinder | create_camera | create_light | create_collection | "
                    "duplicate_object | set_transform | set_active_camera | look_at | set_material | "
                    "add_modifier | delete_object | set_render_settings | render | save_blend | scene_checkpoint | undo"
                ),
            },
            "object_name": {"type": "STRING", "description": "Named Blender object"},
            "target_name": {"type": "STRING", "description": "Target object for look_at"},
            "new_name": {"type": "STRING", "description": "Name for a duplicate"},
            "collection_name": {"type": "STRING", "description": "Collection label"},
            "location": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "XYZ location"},
            "target_location": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "XYZ target point"},
            "rotation": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "XYZ Euler rotation in radians"},
            "scale": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "XYZ scale"},
            "dimensions": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "XYZ world dimensions"},
            "color": {"type": "STRING", "description": "Material color such as #4A90E2"},
            "material_name": {"type": "STRING", "description": "Optional material label"},
            "metallic": {"type": "NUMBER", "description": "Material metallic value 0 to 1"},
            "roughness": {"type": "NUMBER", "description": "Material roughness value 0 to 1"},
            "light_type": {"type": "STRING", "description": "POINT | SUN | AREA | SPOT"},
            "energy": {"type": "NUMBER", "description": "Light energy, bounded by the add-on"},
            "modifier_type": {"type": "STRING", "description": "BEVEL | SUBSURF | SOLIDIFY | ARRAY | MIRROR | DECIMATE"},
            "modifier_name": {"type": "STRING", "description": "Optional modifier label"},
            "amount": {"type": "NUMBER", "description": "Modifier width/strength"},
            "segments": {"type": "INTEGER", "description": "Bevel segments 1 to 12"},
            "levels": {"type": "INTEGER", "description": "Subdivision levels 0 to 4"},
            "count": {"type": "INTEGER", "description": "Array count 1 to 20"},
            "path": {"type": "STRING", "description": "User-selected .blend or render path"},
            "engine": {"type": "STRING", "description": "BLENDER_EEVEE_NEXT | BLENDER_EEVEE | BLENDER_WORKBENCH | CYCLES"},
            "resolution": {"type": "ARRAY", "items": {"type": "INTEGER"}, "description": "Render width and height"},
            "samples": {"type": "INTEGER", "description": "Render samples 1 to 4096"},
            "format": {"type": "STRING", "description": "PNG | JPEG | OPEN_EXR"},
            "limit": {"type": "INTEGER", "description": "Maximum objects to list (default 100)"},
        },
        "required": ["action"],
    },
}

_READ_ONLY = {"status", "list_objects", "inspect_object"}
_MUTATING = {
    "create_cube", "create_sphere", "create_cylinder", "create_camera", "create_light",
    "create_collection", "duplicate_object", "set_transform", "set_active_camera", "look_at",
    "set_material", "add_modifier", "delete_object", "set_render_settings", "render", "save_blend", "scene_checkpoint", "undo",
}


def _settings_note() -> str:
    return "Set MARK_BLENDER_TOKEN in the environment shared by MARK and Blender."


def _test(values: dict) -> tuple[bool, str]:
    return test_connection(values)


PLUGIN_SETTINGS = {
    "namespace": "blender_control",
    "title": "BLENDER — LOCAL BRIDGE",
    "note": (
        "The bridge is loopback-only. Host and port are non-secret settings; the "
        "token is environment-only and is never saved in MARK configuration."
    ),
    "fields": [
        {"key": "host", "label": "Bridge host", "default": "127.0.0.1"},
        {"key": "port", "label": "Bridge port", "default": 8765},
    ],
    "action": {"label": "TEST BLENDER CONNECTION", "run": _test},
}


def _parameters(params: dict) -> dict:
    ignored = {"action"}
    return {key: value for key, value in params.items() if key not in ignored and value is not None}


def _run(action: str, params: dict) -> str:
    ok, message = call(action, _parameters(params))
    return message if ok else f"Blender action failed: {message}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower().replace("-", "_")
    if action not in _READ_ONLY | _MUTATING:
        return "Unknown Blender action. Use status, list_objects, inspect_object, create_cube, create_sphere, create_cylinder, create_camera, create_light, create_collection, duplicate_object, set_transform, set_active_camera, look_at, set_material, add_modifier, delete_object, set_render_settings, render, save_blend, scene_checkpoint or undo."

    error = configuration_error()
    if error:
        return error + " " + _settings_note()

    if action in _READ_ONLY:
        result = _run(action, params)
    else:
        if confirm_gate.pending_title():
            return "There is already a confirmation waiting on screen. Answer it before another Blender change."
        name = str(params.get("object_name") or params.get("path") or "scene").strip()
        detail = f"Allow MARK to run Blender action '{action}' for {name[:100]}?"
        result = confirm_gate.request(
            "blender_action",
            f"Blender: {action}",
            detail,
            lambda: _run(action, params),
        )

    if player:
        try:
            player.write_log(f"[Blender] {action}")
            if action in {"render", "set_render_settings", "scene_checkpoint"}:
                player.show_content("BLENDER — RENDER / CHECKPOINT", result)
        except Exception:
            pass
    return result

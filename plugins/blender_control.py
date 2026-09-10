"""Use the user's existing Blender MCP add-on through its stdio MCP server.

The BlenderMCP panel shown by the user listens on localhost:9876. MARK starts
the fixed ``uvx blender-mcp`` MCP server, which connects to that add-on. MARK
never accepts arbitrary shell commands or exposes the upstream server's
arbitrary-Python tool; only advertised non-code tools can be called, and
unknown/mutating calls require the normal on-screen confirmation.
"""
from __future__ import annotations

import json

from core import confirm as confirm_gate
from core.blender_bridge import (
    call,
    call_tool,
    configuration_error,
    list_tools,
    test_connection,
)


PLUGIN = {
    "name": "blender_control",
    "description": (
        "Connect to the user's existing BlenderMCP add-on through the local MCP "
        "server. The Blender panel normally uses port 9876. First use action "
        "list_tools when the available MCP capabilities are unknown, then use "
        "action mcp_call with the exact advertised mcp_tool and JSON arguments. "
        "Read-only scene inspection is immediate; all scene changes, asset downloads, "
        "renders, saves and external integrations require confirmation. The arbitrary "
        "Python/code execution tool is blocked by MARK."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "status | list_tools | mcp_call | list_objects | inspect_object | "
                    "create_cube | create_sphere | create_cylinder | create_camera | "
                    "create_light | create_collection | duplicate_object | set_transform | "
                    "set_active_camera | look_at | set_material | add_modifier | delete_object | "
                    "set_render_settings | render | save_blend | scene_checkpoint | undo"
                ),
            },
            "mcp_tool": {
                "type": "STRING",
                "description": "Exact tool name returned by action list_tools, for example get_scene_info or create_object",
            },
            "arguments": {
                "type": "OBJECT",
                "description": "Exact JSON arguments for the selected advertised MCP tool",
                "properties": {},
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

_READ_ONLY = {"status", "list_tools", "list_objects", "inspect_object"}
_MUTATING = {
    "create_cube", "create_sphere", "create_cylinder", "create_camera", "create_light",
    "create_collection", "duplicate_object", "set_transform", "set_active_camera", "look_at",
    "set_material", "add_modifier", "delete_object", "set_render_settings", "render",
    "save_blend", "scene_checkpoint", "undo",
}
_BLOCKED_MCP_WORDS = (
    "execute_blender_code", "execute_python", "run_python", "run_code",
    "shell", "terminal", "eval",
)
_READ_ONLY_MCP_PREFIXES = (
    "get_", "list_", "inspect_", "search_", "find_", "describe_", "check_",
)


def _test(values: dict) -> tuple[bool, str]:
    return test_connection(values)


PLUGIN_SETTINGS = {
    "namespace": "blender_control",
    "title": "BLENDER — EXISTING MCP SERVER",
    "note": (
        "Uses the BlenderMCP add-on already installed in Blender. MARK launches "
        "the fixed uvx blender-mcp server, which connects to the add-on's local "
        "socket. Host and port are non-secret settings; no Blender credential is "
        "stored by MARK."
    ),
    "fields": [
        {"key": "host", "label": "Blender add-on host", "default": "127.0.0.1"},
        {"key": "port", "label": "Blender add-on port", "default": 9876},
        {"key": "launcher", "label": "MCP launcher", "default": "uvx", "placeholder": "uvx or python"},
    ],
    "action": {"label": "TEST EXISTING BLENDER MCP", "run": _test},
}


def _parameters(params: dict) -> dict:
    ignored = {"action", "mcp_tool", "arguments", "_approved"}
    return {key: value for key, value in params.items() if key not in ignored and value is not None}


def _blocked_tool(name: str) -> bool:
    value = str(name or "").strip().lower()
    return not value or any(word in value for word in _BLOCKED_MCP_WORDS)


def _read_only_tool(name: str) -> bool:
    value = str(name or "").strip().lower()
    return value in {
        "get_scene_info", "get_object_info", "get_viewport_screenshot",
        "get_polyhaven_status", "get_hyper3d_status", "get_hunyuan3d_status",
        "search_blender_docs", "list_objects", "inspect_object",
    } or value.startswith(_READ_ONLY_MCP_PREFIXES)


def _run_direct(action: str, params: dict) -> str:
    ok, message = call(action, _parameters(params))
    return message if ok else f"Blender MCP action failed: {message}"


def _run_mcp_tool(tool: str, arguments: dict) -> str:
    if _blocked_tool(tool):
        return "MARK blocked that Blender MCP tool because it can execute arbitrary Python or commands."
    ok, message = call_tool(tool, arguments)
    return message if ok else f"Blender MCP tool failed: {message}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = dict(parameters or {})
    action = str(params.get("action", "status")).strip().lower().replace("-", "_")
    approved = bool(params.pop("_approved", False))
    if action not in _READ_ONLY | _MUTATING | {"mcp_call"}:
        return "Unknown Blender action. Use list_tools, mcp_call, status, inspect_object or an allowlisted Blender action."

    error = configuration_error()
    if error:
        return error

    if action == "list_tools":
        ok, result = list_tools()
        if player:
            try:
                player.write_log(f"[Blender MCP] list_tools: {result[:180]}")
            except Exception:
                pass
        return result if ok else f"Blender MCP tool discovery failed: {result}"

    if action == "mcp_call":
        tool = str(params.get("mcp_tool", "")).strip()
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if _blocked_tool(tool):
            return "MARK blocked that Blender MCP tool because it can execute arbitrary Python or commands."
        if not _read_only_tool(tool) and not approved:
            if confirm_gate.pending_title():
                return "There is already a confirmation waiting on screen. Answer it before another Blender MCP change."
            detail = f"Allow MARK to call the Blender MCP tool '{tool}' with these arguments?\n{json.dumps(arguments, ensure_ascii=False)[:900]}"
            return confirm_gate.request(
                "blender_mcp_tool",
                f"Blender MCP: {tool}",
                detail,
                lambda: run({**params, "_approved": True}, player=player, session_memory=session_memory),
            )
        result = _run_mcp_tool(tool, arguments)
    elif action in _READ_ONLY:
        result = _run_direct(action, params)
    else:
        if confirm_gate.pending_title():
            return "There is already a confirmation waiting on screen. Answer it before another Blender change."
        name = str(params.get("object_name") or params.get("path") or "scene").strip()
        detail = f"Allow MARK to use the existing Blender MCP server for '{action}' on {name[:100]}?"
        return confirm_gate.request(
            "blender_mcp_legacy_action",
            f"Blender MCP: {action}",
            detail,
            lambda: _run_direct(action, params),
        )

    if player:
        try:
            player.write_log(f"[Blender MCP] {action}: {str(result)[:180]}")
            if action in {"render", "set_render_settings", "scene_checkpoint", "mcp_call"}:
                player.show_content("BLENDER MCP", str(result))
        except Exception:
            pass
    return str(result)

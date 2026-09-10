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
from core.task_planner import current as current_task_plan, render as render_task_plan, update as update_task_plan
from core.blender_bridge import (
    call,
    call_tool,
    call_tool_with_images,
    close as close_blender_bridge,
    configuration_error,
    list_tools,
    test_connection,
    validate_arguments,
)
from core.llm_client import call_llm_text, get_vision_model
from core.blender_workflows import build_plan, render_plan


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
                    "status | list_tools | plan | workflow_plan | scene_summary | visual_review | verify | mcp_call | list_objects | inspect_object | "
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
            "goal": {"type": "STRING", "description": "High-level visual goal for a bounded workflow plan"},
            "workflow": {"type": "STRING", "description": "inspect | preview | cinematic; use plan to view the workflow"},
        },
        "required": ["action"],
    },
}

_READ_ONLY = {"status", "list_tools", "plan", "workflow_plan", "scene_summary", "visual_review", "verify", "list_objects", "inspect_object"}
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
    if value in {
        "get_scene_info", "get_object_info", "get_viewport_screenshot",
        "get_polyhaven_status", "get_hyper3d_status", "get_hunyuan3d_status",
        "search_blender_docs", "list_objects", "inspect_object",
    } or value.startswith(_READ_ONLY_MCP_PREFIXES):
        return True
    # Some MCP servers use a bare capability name for a screenshot. Treat
    # visual inspection as read-only, but never classify a render/export as one.
    return any(word in value for word in ("screenshot", "viewport", "scene_info", "object_info")) and not any(word in value for word in ("render", "save", "export"))


def _run_direct(action: str, params: dict) -> str:
    ok, message = call(action, _parameters(params))
    return message if ok else f"Blender MCP action failed: {message}"


def _run_confirmed_direct(action: str, params: dict, player=None) -> str:
    before_text, before_visual = _run_mcp_tool("get_viewport_screenshot", {})
    result = _run_direct(action, params)
    after_text, after_visual = _run_mcp_tool("get_viewport_screenshot", {})
    if before_visual and after_visual and not any(marker in str(result).lower() for marker in ("failed", "could not", "does not expose")):
        result += f"\nVisual before/after verification:\n{_visual_before_after(before_visual, after_visual, action)}"
    return _finish_waiting_plan(result, player)


def _run_mcp_tool(tool: str, arguments: dict) -> tuple[str, list[dict]]:
    if _blocked_tool(tool):
        return "MARK blocked that Blender MCP tool because it can execute arbitrary Python or commands.", []
    ok, message, images = call_tool_with_images(tool, arguments)
    # Only read-only inspection may be retried, and only once, after resetting
    # a dead stdio session. Mutations are never replayed automatically.
    transient = any(marker in str(message).lower() for marker in ("connect", "refused", "timed out", "process is not running"))
    if not ok and _read_only_tool(tool) and transient:
        close_blender_bridge()
        ok, message, images = call_tool_with_images(tool, arguments)
    return (message if ok else f"Blender MCP tool failed: {message}"), (images if ok else [])


def _finish_waiting_plan(result: str, player=None) -> str:
    """Close the current checklist step when a human-approved action returns."""
    try:
        plan = current_task_plan()
        if plan and plan.get("status") == "waiting_confirmation" and plan.get("cursor"):
            text = str(result).lower()
            failed = any(marker in text for marker in ("failed", "could not", "failure reason:"))
            update_task_plan(int(plan["cursor"]), "failed" if failed else "done", "Blender action returned")
            if player:
                player.show_content("TASK PLAN", render_task_plan())
    except Exception:
        pass
    return result


def _vision_feedback(tool: str, scene_text: str, images: list[dict]) -> str:
    """Use the configured local vision model to turn MCP images into feedback."""
    if not images:
        return ""
    prompt = (
        "Inspect this current Blender viewport or render. Describe only visible, "
        "useful facts: framing, object presence, obvious geometry/material/camera "
        "problems, and whether the requested visual result appears complete. "
        "Do not invent hidden scene data. Keep the feedback under 120 words.\n\n"
        f"MCP operation: {tool}\nTool text: {scene_text[:900]}"
    )
    try:
        feedback = call_llm_text(
            prompt,
            model=get_vision_model(),
            images=images[:1],
            num_predict=220,
            timeout=180,
        ).strip()
    except Exception as exc:
        return f"Local vision feedback unavailable: {exc}"
    return feedback or "Local vision returned no feedback."


def _visual_before_after(before: list[dict], after: list[dict], operation: str) -> str:
    """Ask the local vision model for a bounded before/after comparison."""
    if not before or not after:
        return "Visual before/after verification unavailable: one of the bounded screenshots was not returned."
    prompt = (
        "Compare the two supplied local Blender viewport/render images. The first is BEFORE and the second is AFTER. "
        "Report only visible differences relevant to the requested operation, whether the scene still appears coherent, "
        "and any uncertainty. Do not invent hidden scene data. Keep it under 100 words.\n\n"
        f"Operation: {operation}"
    )
    try:
        feedback = call_llm_text(
            prompt,
            model=get_vision_model(),
            images=[before[0], after[0]],
            num_predict=180,
            timeout=180,
        ).strip()
    except Exception as exc:
        return f"Visual before/after verification unavailable: {exc}"
    return feedback or "Visual before/after verification returned no feedback."


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = dict(parameters or {})
    action = str(params.get("action", "status")).strip().lower().replace("-", "_")
    approved = bool(params.pop("_approved", False))
    if action not in _READ_ONLY | _MUTATING | {"mcp_call"}:
        return "Unknown Blender action. Use list_tools, mcp_call, status, inspect_object or an allowlisted Blender action."

    if action in {"plan", "workflow_plan"}:
        result = render_plan(build_plan(str(params.get("goal", "")), str(params.get("workflow", ""))))
        if player:
            try:
                player.show_content("BLENDER WORKFLOW", result)
            except Exception:
                pass
        return result

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

    if action in {"scene_summary", "verify"}:
        result = _run_direct("status", params)
    elif action == "visual_review":
        scene = _run_direct("status", params)
        screenshot, images = _run_mcp_tool("get_viewport_screenshot", {})
        result = f"Scene metadata:\n{scene}\nViewport review:\n{screenshot}"
        if images:
            result += f"\nLocal vision feedback:\n{_vision_feedback('get_viewport_screenshot', screenshot, images)}"
    elif action == "mcp_call":
        tool = str(params.get("mcp_tool", "")).strip()
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if _blocked_tool(tool):
            return "MARK blocked that Blender MCP tool because it can execute arbitrary Python or commands."
        argument_error = validate_arguments(arguments)
        if argument_error:
            return argument_error
        mutating = not _read_only_tool(tool)
        before_visual: list[dict] = []
        if mutating and approved:
            try:
                _before_text, before_visual = _run_mcp_tool("get_viewport_screenshot", {})
            except Exception:
                before_visual = []
        if mutating and not approved:
            if confirm_gate.pending_title():
                return "There is already a confirmation waiting on screen. Answer it before another Blender MCP change."
            context = ""
            try:
                ok_context, context_value = call_tool("get_scene_info", {}, timeout=20.0)
                if ok_context:
                    context = f"\nCurrent scene context:\n{str(context_value)[:700]}"
            except Exception:
                pass
            detail = (
                f"Allow MARK to call the Blender MCP tool '{tool}' with these arguments?"
                f"{context}\nArguments:\n{json.dumps(arguments, ensure_ascii=False)[:900]}"
            )
            return confirm_gate.request(
                "blender_mcp_tool",
                f"Blender MCP: {tool}",
                detail,
                lambda: run({**params, "_approved": True}, player=player, session_memory=session_memory),
            )
        result, images = _run_mcp_tool(tool, arguments)
        if images:
            result += f"\nLocal vision feedback:\n{_vision_feedback(tool, result, images)}"
        if mutating and not str(result).lower().startswith("blender mcp tool failed"):
            # A render tool may return only a path/text result. Make one
            # bounded, read-only viewport attempt so the next planning round
            # can refine the visual result instead of guessing from metadata.
            if not images and "render" in tool.lower():
                try:
                    ok_preview, preview_text, preview_images = call_tool_with_images(
                        "get_viewport_screenshot", {}, timeout=20.0
                    )
                    if ok_preview and preview_images:
                        result += f"\nPost-render local vision feedback:\n{_vision_feedback('get_viewport_screenshot', preview_text, preview_images)}"
                except Exception:
                    pass
            try:
                ok_verify, verify = call_tool("get_scene_info", {}, timeout=20.0)
                if ok_verify:
                    result += f"\nVerification scene snapshot:\n{str(verify)[:900]}"
            except Exception:
                pass
            if before_visual:
                try:
                    _after_text, after_visual = _run_mcp_tool("get_viewport_screenshot", {})
                    if after_visual:
                        result += f"\nVisual before/after verification:\n{_visual_before_after(before_visual, after_visual, tool)}"
                except Exception:
                    pass
    elif action in _READ_ONLY:
        result = _run_direct(action, params)
    else:
        if not approved:
            if confirm_gate.pending_title():
                return "There is already a confirmation waiting on screen. Answer it before another Blender change."
            name = str(params.get("object_name") or params.get("path") or "scene").strip()
            detail = f"Allow MARK to use the existing Blender MCP server for '{action}' on {name[:100]}?"
            return confirm_gate.request(
                "blender_mcp_legacy_action",
                f"Blender MCP: {action}",
                detail,
                lambda: _run_confirmed_direct(action, params, player),
            )
        result = _run_confirmed_direct(action, params, player)

    if approved:
        result = _finish_waiting_plan(str(result), player)
    if player:
        try:
            player.write_log(f"[Blender MCP] {action}: {str(result)[:180]}")
            if action in {"render", "set_render_settings", "scene_checkpoint", "mcp_call"}:
                player.show_content("BLENDER MCP", str(result))
        except Exception:
            pass
    return str(result)

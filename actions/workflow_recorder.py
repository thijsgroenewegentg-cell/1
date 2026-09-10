"""Safe workflow recorder: record, inspect, replay or delete approved routines."""
from __future__ import annotations

from core.workflow_recorder import delete, describe, edit_step, names, replay, start, stop


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()
    name = str(params.get("name", "")).strip()
    if action == "start":
        result = start(
            name or "workflow",
            inputs=params.get("inputs") if isinstance(params.get("inputs"), dict) else {},
            permissions=params.get("permissions") if isinstance(params.get("permissions"), list) else [],
            confirmation_points=params.get("confirmation_points") if isinstance(params.get("confirmation_points"), list) else [],
            verification=params.get("verification") if isinstance(params.get("verification"), list) else [],
            recovery=str(params.get("recovery", "")),
        )
    elif action == "stop":
        workflow = stop()
        result = "Recording was not active." if not workflow else f"Recording saved: {workflow['name']} ({len(workflow['steps'])} steps)."
    elif action == "list":
        found = names()
        result = "Saved workflows: " + ", ".join(found) if found else "No saved workflows."
    elif action == "show":
        result = describe(name)
    elif action == "edit":
        result = edit_step(name, params.get("step", 0), params.get("parameters"), params.get("tool"))
    elif action == "replay":
        result = replay(name)
    elif action == "delete":
        result = f"Deleted workflow: {name}" if delete(name) else f"Workflow not found: {name}"
    else:
        result = "Use workflow_recorder action start, stop, list, show, edit, replay or delete."
    if player:
        try:
            player.show_content("WORKFLOW RECORDER", result)
            player.write_log(f"[Workflow] {action}")
        except Exception:
            pass
    return result


TOOL = {
    "name": "workflow_recorder",
    "description": (
        "Record safe reusable workflows made from MARK tools. Start recording before a routine, "
        "stop to save it, show it before replay, edit safe non-sensitive steps, and replay only when the user asks. "
        "Passwords, clipboard contents, typed text, message bodies and credentials are never recorded."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "start | stop | list | show | edit | replay | delete"},
            "name": {"type": "STRING", "description": "Workflow name"},
            "inputs": {"type": "OBJECT", "description": "Non-secret named inputs for the workflow"},
            "permissions": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Explicit tool names permitted during replay"},
            "confirmation_points": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Human approval points"},
            "verification": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Postcondition checks"},
            "recovery": {"type": "STRING", "description": "Recovery instruction if replay fails"},
            "step": {"type": "INTEGER", "description": "1-based step number for edit"},
            "tool": {"type": "STRING", "description": "Optional replacement tool name for edit"},
            "parameters": {"type": "OBJECT", "description": "Safe replacement parameters; sensitive values are redacted"},
        },
        "required": ["action"],
    },
    "handler": run,
}

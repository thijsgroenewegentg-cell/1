"""Inspect MARK's durable task execution trace without executing anything."""
from __future__ import annotations

from core.task_runtime import render_runtime, runtime


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    if action == "status":
        result = render_runtime(include_history=bool(params.get("history", False)))
    elif action == "timeline":
        rows = runtime().timeline(int(params.get("limit", 30)))
        result = "TASK TIMELINE\n" + ("\n".join(f"{row.get('time', '')} · {row.get('kind', '')} · {row.get('detail', '')}" for row in rows) if rows else "No task events recorded.")
    elif action == "clear_history":
        runtime().clear_history()
        result = "Task runtime history cleared locally."
    else:
        result = "Use task_runtime action status, timeline or clear_history."
    if player:
        try:
            player.show_content("TASK RUNTIME", result)
            player.write_log(f"[Task runtime] {action}")
        except Exception:
            pass
    return result


TOOL = {
    "name": "task_runtime",
    "description": "Inspect the structured task trace, operation status, verification and recovery notes. This tool never executes or retries operations.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | timeline | clear_history"},
            "history": {"type": "BOOLEAN", "description": "Include recent completed task summaries"},
            "limit": {"type": "INTEGER", "description": "Maximum timeline events"},
        },
        "required": ["action"],
    },
    "handler": run,
}

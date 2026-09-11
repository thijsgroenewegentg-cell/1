"""Read-only recovery and observability surface for MARK."""
from __future__ import annotations

from core.authority import get_authority
from core.failure import recent as recent_failures
from core.operation_checkpoints import recent as recent_operations
from core.task_runtime import runtime


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    if action in {"status", "failures"}:
        rows = recent_failures(int(params.get("limit", 10)))
        result = "RECENT FAILURES\n" + ("\n".join(f"{row.get('time', '')} · {row.get('component', '')}: {row.get('error', '')}" for row in rows) if rows else "No recorded failures.")
    elif action == "operations":
        rows = recent_operations(int(params.get("limit", 10)))
        result = "RECENT OPERATIONS\n" + ("\n".join(f"{row.get('time', '')} · {row.get('component', '')}/{row.get('operation', '')} · changed={row.get('changed', False)} · {row.get('recovery', '')}" for row in rows) if rows else "No operation journal entries.")
    elif action == "task":
        result = runtime().render(include_history=True)
    elif action == "audit":
        rows = get_authority().audit(int(params.get("limit", 20)))
        result = "AUTHORITY AUDIT\n" + ("\n".join(
            f"{row.get('time', '')} · {row.get('kind', '')} · {row.get('outcome', '')} · {row.get('tool', '')} · {row.get('detail', '')}"
            for row in rows
        ) if rows else "No authority audit events recorded.")
    else:
        result = "Use recovery action status, failures, operations, task or audit. Recovery is diagnostic only; MARK never retries a mutation blindly."
    if player:
        try:
            player.show_content("RECOVERY", result)
            player.write_log(f"[Recovery] {action}")
        except Exception:
            pass
    return result


TOOL = {
    "name": "recovery",
    "description": "Inspect failures, operation checkpoints and task recovery notes. Diagnostic only: it never blindly retries or replays a mutation.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | failures | operations | task | audit"},
            "limit": {"type": "INTEGER", "description": "Maximum records"},
        },
        "required": ["action"],
    },
    "handler": run,
}

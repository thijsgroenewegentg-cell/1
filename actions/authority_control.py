"""Inspect MARK's central authority/audit state and use its emergency gate."""
from __future__ import annotations

from core.authority import get_authority


def _render_audit(rows: list[dict]) -> str:
    if not rows:
        return "No authority audit events recorded."
    return "\n".join(
        f"{row.get('time', '')} · {row.get('kind', '')} · {row.get('outcome', '')}"
        f" · {row.get('tool', '')} · {row.get('detail', '')}".strip()
        for row in rows
    )


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    authority = get_authority()
    try:
        if action in {"status", "emergency_status"}:
            status = authority.emergency_status()
            result = (
                f"AUTHORITY mode={status.get('mode', 'normal')}; "
                f"pending_approvals={status.get('pending_approvals', 0)}; "
                f"active_task_grants={status.get('active_grants', 0)}; "
                f"reason={status.get('reason', '') or 'none'}"
            )
        elif action == "audit":
            result = "AUTHORITY AUDIT\n" + _render_audit(authority.audit(int(params.get("limit", 30))))
        elif action in {"pause", "safety_pause"}:
            status = authority.set_emergency("pause", str(params.get("reason", "Emergency safety pause requested.")), actor="assistant")
            result = f"Emergency safety pause active. No tool execution will start until it is resumed. reason={status.get('reason', '')}"
        elif action in {"kill", "emergency_stop"}:
            status = authority.set_emergency("kill", str(params.get("reason", "Emergency stop requested.")), actor="assistant")
            result = f"Emergency kill switch active. Tool execution is blocked until the user explicitly clears it. reason={status.get('reason', '')}"
        elif action in {"resume", "clear_kill", "clear"}:
            status = authority.set_emergency("normal", "Emergency gate cleared by the user.", actor="assistant")
            result = f"Emergency gate cleared; authority mode is {status.get('mode', 'normal')}."
        else:
            result = "Use authority_control action status, audit, pause, kill, resume or clear_kill."
    except Exception as exc:
        result = f"Authority control failed safely: {exc}"
    if player:
        try:
            player.show_content("AUTHORITY", result)
            player.write_log(f"[Authority] {action}")
        except Exception:
            pass
    return result


TOOL = {
    "name": "authority_control",
    "description": (
        "Inspect MARK's centralized approval and audit state, or activate a local emergency pause/kill gate. "
        "Emergency stop is fail-safe; clearing it is explicit and does not replay blocked tools. "
        "This tool never grants shell, Python or unrestricted MCP access."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | audit | pause | kill | resume | clear_kill"},
            "reason": {"type": "STRING", "description": "Short safety reason"},
            "limit": {"type": "INTEGER", "description": "Maximum audit records"},
        },
        "required": ["action"],
    },
    "handler": run,
}

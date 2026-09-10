"""Visible planning tool for multi-step work.

Planning never bypasses the normal tool policy. It gives MARK and the user a
shared checklist that can be paused, skipped, failed, completed or cancelled.
"""
from __future__ import annotations

from core.task_planner import cancel, create, current, pause, render, resume, rollback, update


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    try:
        if action == "create":
            raw = params.get("steps", [])
            steps = raw if isinstance(raw, list) else str(raw).split("\n")
            plan = create(str(params.get("title", "MARK task")), steps)
            result = render(plan)
        elif action in {"update", "complete", "fail", "skip", "confirm"}:
            status = {"complete": "done", "fail": "failed", "skip": "skipped", "confirm": "confirmation"}.get(action, params.get("status", "pending"))
            plan = update(params.get("step", params.get("index", 0)), status, str(params.get("note", "")))
            result = render(plan)
        elif action == "pause":
            result = render(pause())
        elif action in {"continue", "resume"}:
            result = render(resume())
        elif action == "rollback":
            result = render(rollback(params.get("step", params.get("index", 1))))
        elif action == "cancel":
            result = render(cancel())
        elif action == "status":
            result = render(current())
        else:
            return "Use task_planner action create, update, complete, fail, skip, confirm, status, pause, continue, rollback or cancel."
    except Exception as exc:
        result = f"Planner could not update the plan: {exc}"
    if player:
        try:
            player.show_content("TASK PLAN", result)
            player.write_log(f"[Planner] {action}")
        except Exception:
            pass
    return result


TOOL = {
    "name": "task_planner",
    "description": (
        "Create and update a visible checklist for requests with three or more steps. "
        "Use create before executing a complex task, then update steps as work progresses. "
        "Supports pause, continue, cancel, skip, confirmation and checklist rollback. "
        "Planning does not itself execute tools; every action still uses normal confirmations."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "create | update | complete | fail | skip | confirm | status | pause | continue | rollback | cancel"},
            "title": {"type": "STRING", "description": "Short task title"},
            "steps": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Ordered task steps"},
            "step": {"type": "INTEGER", "description": "Step number"},
            "index": {"type": "INTEGER", "description": "Alias for step number"},
            "status": {"type": "STRING", "description": "pending | running | done | failed | skipped | confirmation"},
            "note": {"type": "STRING", "description": "Short result or failure note"},
        },
        "required": ["action"],
    },
    "handler": run,
}

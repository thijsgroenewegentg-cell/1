"""Inspect MARK's durable task execution trace without executing anything."""
from __future__ import annotations

from core.task_runtime import render_runtime, runtime


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    task_runtime = runtime()
    if action == "status":
        result = render_runtime(include_history=bool(params.get("history", False)))
    elif action == "timeline":
        rows = task_runtime.timeline(int(params.get("limit", 30)))
        result = "TASK TIMELINE\n" + ("\n".join(f"{row.get('time', '')} · {row.get('kind', '')} · {row.get('detail', '')}" for row in rows) if rows else "No task events recorded.")
    elif action in {"question", "needs_input"}:
        pending = task_runtime.pending_input()
        result = "No clarification is waiting." if not pending else (
            f"INPUT REQUIRED [{pending.get('task_id', '')}]: {pending.get('question', '')}"
            + (" Options: " + ", ".join(pending.get("clarification", {}).get("options", [])) if pending.get("clarification") else "")
        )
    elif action in {"answer", "resume"}:
        answer = str(params.get("answer", "")).strip()
        if action == "answer" and not answer:
            result = "Provide answer to resume the clarification task."
        else:
            task_runtime.resume(answer if answer else None)
            result = task_runtime.render(include_history=False)
    elif action == "clear_history":
        task_runtime.clear_history()
        result = "Task runtime history cleared locally."
    else:
        result = "Use task_runtime action status, timeline, question, answer, resume or clear_history."
    if player:
        try:
            player.show_content("TASK RUNTIME", result)
            player.write_log(f"[Task runtime] {action}")
        except Exception:
            pass
    return result


TOOL = {
    "name": "task_runtime",
    "description": "Inspect the durable task envelope, operation status, clarification question, verification and recovery notes. Answering a pending clarification resumes the same task without replaying prior operations; this tool never executes or retries operations.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | timeline | question | answer | resume | clear_history"},
            "history": {"type": "BOOLEAN", "description": "Include recent completed task summaries"},
            "limit": {"type": "INTEGER", "description": "Maximum timeline events"},
            "answer": {"type": "STRING", "description": "Answer to the pending clarification question"},
        },
        "required": ["action"],
    },
    "handler": run,
}

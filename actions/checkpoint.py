"""Explicit file checkpoints for larger reversible tasks."""
from __future__ import annotations

from core import confirm as confirm_gate
from core.checkpoints import create, list_checkpoints, remove, restore
from core.operation_checkpoints import recent as recent_operations


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()
    try:
        if action == "create":
            cp = create(str(params.get("label", "checkpoint")), params.get("paths", []))
            result = f"Checkpoint created: {cp['id']} ({len(cp['files'])} files)."
        elif action == "list":
            rows = list_checkpoints()
            result = "No checkpoints." if not rows else "\n".join(f"{x['id']} — {x['label']} — {len(x.get('files', []))} files" for x in rows)
            operations = recent_operations(8)
            if operations:
                result += "\n\nRECENT OPERATIONS\n" + "\n".join(
                    f"{x['time']} — {x['component']}/{x['operation']} — {'changed' if x['changed'] else 'no change'}"
                    for x in operations
                )
        elif action == "restore":
            checkpoint_id = str(params.get("checkpoint_id", "")).strip()
            if not checkpoint_id:
                return "Provide checkpoint_id to restore."
            if confirm_gate.pending_title():
                return "There is already a confirmation waiting on screen. Answer it first."
            result = confirm_gate.request(
                "checkpoint_restore",
                "Restore file checkpoint",
                f"Restore checkpoint {checkpoint_id} over the current files? This will replace their contents.",
                lambda: restore(checkpoint_id),
            )
        elif action == "delete":
            result = "Checkpoint deleted." if remove(str(params.get("checkpoint_id", ""))) else "Checkpoint not found."
        else:
            result = "Use checkpoint action create, list, restore or delete."
    except Exception as exc:
        result = f"Checkpoint operation failed: {exc}"
    if player:
        try:
            player.write_log(f"[Checkpoint] {action}")
            player.show_content("CHECKPOINTS", result)
        except Exception:
            pass
    return result


TOOL = {
    "name": "checkpoint",
    "description": (
        "Create, list and restore explicit file checkpoints before larger work. "
        "Checkpoint creation is local and restore always requires human confirmation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "create | list | restore | delete"},
            "label": {"type": "STRING", "description": "Checkpoint label"},
            "paths": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Absolute files under the home folder"},
            "checkpoint_id": {"type": "STRING", "description": "Checkpoint id"},
        },
        "required": ["action"],
    },
    "handler": run,
}

"""Consistent, actionable failure messages and a small local failure history."""
from __future__ import annotations

import threading
import time
from collections import deque

_lock = threading.Lock()
_recent = deque(maxlen=50)


def record(component: str, error: Exception | str, changed: bool = False) -> dict:
    message = str(error).strip() or "unknown error"
    item = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "component": str(component), "error": message[:500], "changed": bool(changed)}
    with _lock:
        _recent.append(item)
    return item


def recent(limit: int = 10) -> list[dict]:
    with _lock:
        return list(_recent)[-max(1, min(50, int(limit))):]


def explain(component: str, error: Exception | str, changed: bool = False) -> str:
    item = record(component, error, changed)
    message = item["error"]
    lower = message.lower()
    if "connect" in lower or "ollama" in lower or "timeout" in lower:
        recovery = "Check that Ollama is running and the configured model is pulled."
    elif "permission" in lower or "access" in lower:
        recovery = "Check the approved path or permission, then try again."
    elif "blender" in component.lower():
        recovery = "Check that the authenticated Blender Bridge add-on is running."
    else:
        recovery = "No changes were applied; inspect the activity log for details."
    change_note = "changed or partially changed; use undo or the shown checkpoint before retrying" if changed else "no changes were made"
    retry = "Do not retry blindly until the current state is checked." if changed else "It is safe to retry after the cause is corrected."
    return (
        f"Attempted action: {component}. Change status: {change_note}. "
        f"Failure reason: {message}. Recovery: {recovery} Retry safety: {retry}"
    )

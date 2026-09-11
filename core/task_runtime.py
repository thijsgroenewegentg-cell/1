"""Durable, inspectable task and tool execution runtime.

The older checklist planner records intentional steps.  This runtime records
what actually happened during a turn: operations, confirmations, verification
and recovery notes.  It is deliberately conservative and never retries an
operation or executes a tool itself.
"""
from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.tool_contracts import ToolResult, normalize_result

BASE_DIR = Path(__file__).resolve().parent.parent
RUNTIME_PATH = BASE_DIR / "memory" / "task_runtime.json"
_MAX_HISTORY = 40
_MAX_EVENTS = 160
_SECRET_RE = re.compile(
    r"(?i)\b(password|passcode|token|api[_ -]?key|secret|private[_ -]?key|cookie)\b\s*[:=]\s*[^\s,;]+"
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_text(value: Any, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return _SECRET_RE.sub(r"\1=<redacted>", text)[:limit]


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "<depth-limited>"
    if isinstance(value, dict):
        return {str(k)[:70]: _safe_value(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return [_safe_value(item, depth + 1) for item in value[:30]]
    if isinstance(value, str):
        return _safe_text(value, 180)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if type(value) is object:
        return "<interface-token>"
    return _safe_text(value)


class TaskRuntime:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or RUNTIME_PATH)
        self._lock = threading.RLock()
        self._state = self._load()
        self._recover_interrupted()

    def _empty(self) -> dict:
        return {"current": None, "history": [], "events": []}

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return {
                    "current": value.get("current") if isinstance(value.get("current"), dict) else None,
                    "history": [x for x in value.get("history", [])[-_MAX_HISTORY:] if isinstance(x, dict)],
                    "events": [x for x in value.get("events", [])[-_MAX_EVENTS:] if isinstance(x, dict)],
                }
        except Exception:
            pass
        return self._empty()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            # Runtime telemetry must never turn an assistant action into a failure.
            pass

    def _event(self, kind: str, detail: str, **fields) -> None:
        event = {"time": _now(), "kind": str(kind)[:50], "detail": _safe_text(detail, 320)}
        event.update({str(k): _safe_value(v) for k, v in fields.items()})
        self._state["events"].append(event)
        self._state["events"] = self._state["events"][-_MAX_EVENTS:]

    def _recover_interrupted(self) -> None:
        with self._lock:
            current = self._state.get("current")
            if not current or current.get("status") in {"completed", "cancelled", "failed", "interrupted"}:
                return
            current["status"] = "interrupted"
            current["updated"] = _now()
            self._state["history"].append(copy.deepcopy(current))
            self._state["history"] = self._state["history"][-_MAX_HISTORY:]
            self._event("recovered", "Previous task was interrupted before MARK restarted.", turn_id=current.get("id"))
            self._state["current"] = None
            self._save()

    def begin_turn(self, title: str) -> str:
        with self._lock:
            if self._state.get("current"):
                old = self._state["current"]
                old["status"] = "interrupted"
                old["updated"] = _now()
                self._state["history"].append(copy.deepcopy(old))
            turn_id = uuid.uuid4().hex[:12]
            self._state["current"] = {
                "id": turn_id,
                "title": _safe_text(title, 180) or "MARK task",
                "status": "active",
                "started": _now(),
                "updated": _now(),
                "operations": [],
            }
            self._event("turn_started", self._state["current"]["title"], turn_id=turn_id)
            self._save()
            return turn_id

    def _current(self) -> dict | None:
        value = self._state.get("current")
        return value if isinstance(value, dict) else None

    def begin_operation(self, tool: str, args: dict | None = None, *, risk: str = "read_only", requires_confirmation: bool = False) -> str:
        with self._lock:
            current = self._current()
            if current is None:
                self.begin_turn(f"Standalone {tool} operation")
                current = self._current()
            op_id = uuid.uuid4().hex[:10]
            operation = {
                "id": op_id,
                "tool": _safe_text(tool, 100),
                "arguments": _safe_value(args or {}),
                "risk": _safe_text(risk, 40),
                "requires_confirmation": bool(requires_confirmation),
                "status": "running",
                "started": _now(),
                "updated": _now(),
            }
            current["operations"].append(operation)
            current["updated"] = _now()
            self._event("operation_started", f"{tool} started", turn_id=current["id"], operation_id=op_id, tool=tool)
            self._save()
            return op_id

    def finish_operation(self, operation_id: str, result: ToolResult | str | dict) -> dict:
        normalized = normalize_result(result)
        with self._lock:
            current = self._current()
            operation = None
            if current:
                operation = next((x for x in current.get("operations", []) if x.get("id") == operation_id), None)
            record = normalized.to_record()
            if operation is not None:
                operation.update({
                    "status": normalized.status,
                    "updated": _now(),
                    "result": record,
                })
                current["updated"] = _now()
            self._event(
                "operation_finished",
                f"{normalized.tool or 'tool'}: {normalized.status}",
                operation_id=operation_id,
                status=normalized.status,
                changed=normalized.changed,
                ok=normalized.ok,
            )
            self._save()
            return record

    def hold(self, status: str = "waiting_confirmation") -> None:
        """Persist the current task while an interface confirmation is pending."""
        with self._lock:
            current = self._current()
            if current is None:
                return
            current["status"] = str(status or "waiting_confirmation")[:40]
            current["updated"] = _now()
            self._event("turn_held", "Task is waiting for an interface confirmation.", turn_id=current.get("id"), status=current["status"])
            self._save()

    def resume(self) -> None:
        """Resume a paused task trace; this never replays an operation."""
        with self._lock:
            current = self._current()
            if current is None:
                return
            if current.get("status") in {"paused", "waiting_confirmation"}:
                current["status"] = "active"
                current["updated"] = _now()
                self._event("turn_resumed", "Task resumed; no previous operation was replayed.", turn_id=current.get("id"))
                self._save()

    def confirmation_resolved(self, key: str, result: str) -> None:
        """Attach an asynchronous confirmation callback result to the task trace."""
        normalized = normalize_result(result, tool=f"confirmation:{key}")
        with self._lock:
            current = self._current()
            if current is None:
                self._event("confirmation_resolved", normalized.summary, key=key, ok=normalized.ok)
                self._save()
                return
            operation_hint = str(key or "").split(":", 2)[1] if str(key or "").startswith("runtime:") and len(str(key or "").split(":", 2)) > 1 else ""
            waiting = next((item for item in reversed(current.get("operations", [])) if item.get("status") == "waiting_confirmation" and (not operation_hint or item.get("id") == operation_hint)), None)
            if waiting is not None:
                waiting["status"] = normalized.status
                waiting["updated"] = _now()
                waiting["result"] = normalized.to_record()
            self._event("confirmation_resolved", normalized.summary, key=key, ok=normalized.ok)
            current["updated"] = _now()
            lower = normalized.summary.lower()
            remaining_waiting = any(item.get("status") == "waiting_confirmation" for item in current.get("operations", []))
            if "cancelled" in lower or "expired" in lower:
                current["status"] = "cancelled"
            elif remaining_waiting:
                current["status"] = "waiting_confirmation"
            elif normalized.ok and not normalized.status == "waiting_confirmation":
                current["status"] = "completed"
            elif not normalized.ok:
                current["status"] = "failed"
            self._save()
            if current.get("status") in {"completed", "failed"}:
                self._state["history"].append(copy.deepcopy(current))
                self._state["history"] = self._state["history"][-_MAX_HISTORY:]
                self._state["current"] = None
                self._save()

    def end_turn(self, status: str = "completed") -> None:
        with self._lock:
            current = self._current()
            if current is None:
                return
            current["status"] = str(status or "completed")[:40]
            current["updated"] = _now()
            self._event("turn_finished", f"Task {current['status']}.", turn_id=current["id"], status=current["status"])
            self._state["history"].append(copy.deepcopy(current))
            self._state["history"] = self._state["history"][-_MAX_HISTORY:]
            self._state["current"] = None
            self._save()

    def snapshot(self, include_history: bool = False) -> dict:
        with self._lock:
            result = {"current": copy.deepcopy(self._state.get("current")), "events": copy.deepcopy(self._state.get("events", [])[-40:])}
            if include_history:
                result["history"] = copy.deepcopy(self._state.get("history", [])[-10:])
            return result

    def timeline(self, limit: int = 30) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._state.get("events", [])[-max(1, min(100, int(limit))):])

    def clear_history(self) -> None:
        with self._lock:
            self._state["history"] = []
            self._state["events"] = []
            self._save()

    def render(self, include_history: bool = False) -> str:
        snapshot = self.snapshot(include_history=include_history)
        current = snapshot.get("current")
        history = snapshot.get("history", []) if include_history else []
        if not current:
            if not history:
                return "No task is currently running."
            lines = ["TASK RUNTIME — no task currently running", "RECENT TASKS"]
            for item in history[-10:]:
                lines.append(f"- [{item.get('status', 'unknown')}] {item.get('title', 'MARK task')} · {item.get('updated', item.get('started', ''))}")
            return "\n".join(lines)
        lines = [f"TASK RUNTIME [{str(current.get('status', 'active')).upper()}] {current.get('title', 'MARK task')} · {current.get('id', '')}"]
        for operation in current.get("operations", []):
            icon = {"running": "▶", "completed": "✓", "failed": "!", "waiting_confirmation": "?"}.get(operation.get("status"), "○")
            lines.append(f"{icon} {operation.get('tool', 'tool')} [{operation.get('status', 'running')}]")
            result = operation.get("result") or {}
            if result.get("verification"):
                lines.append("  verified: " + _safe_text(result["verification"], 180))
            if result.get("recovery"):
                lines.append("  recovery: " + _safe_text(result["recovery"], 180))
        if history:
            lines.append("RECENT TASKS")
            for item in history[-5:]:
                lines.append(f"- [{item.get('status', 'unknown')}] {item.get('title', 'MARK task')} · {item.get('updated', item.get('started', ''))}")
        return "\n".join(lines)


_runtime = TaskRuntime()


def runtime() -> TaskRuntime:
    return _runtime


def current_snapshot(include_history: bool = False) -> dict:
    return _runtime.snapshot(include_history=include_history)


def render_runtime(include_history: bool = False) -> str:
    return _runtime.render(include_history=include_history)

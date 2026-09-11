"""Durable, inspectable task envelopes and tool execution runtime.

The runtime is MARK's small local task registry.  It persists the request
contract, bounded conversation buffer, clarification state, operations,
results, approvals, verification and recovery notes.  It deliberately never
executes a tool and never replays an operation on resume.
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
_MAX_EVENTS = 240
_MAX_CONVERSATION = 36
_TERMINAL = {"completed", "cancelled", "failed", "interrupted"}
_PRESERVED_ON_RESTART = {"paused", "needs_input"}
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

    def _archive_current_locked(self, current: dict) -> None:
        self._state["history"].append(copy.deepcopy(current))
        self._state["history"] = self._state["history"][-_MAX_HISTORY:]

    def _recover_interrupted(self) -> None:
        """Reconcile a crash without destroying resumable paused/input tasks."""
        with self._lock:
            current = self._state.get("current")
            if not current or current.get("status") in _TERMINAL or current.get("status") in _PRESERVED_ON_RESTART:
                return
            if current.get("status") == "waiting_confirmation":
                # The UI callback is process-local and cannot be reconstructed
                # safely after restart. Cancel parked operation records and ask
                # the user to review/request the action again instead of replaying.
                for operation in current.get("operations", []):
                    if operation.get("status") == "waiting_confirmation":
                        operation["status"] = "interrupted"
                        operation["updated"] = _now()
                        operation["recovery"] = "The confirmation callback was lost during restart; no operation was replayed."
                current["status"] = "needs_input"
                current["question"] = "MARK restarted while a confirmation was pending. Review the task and tell me whether to request it again."
                current["clarification"] = {"question": current["question"], "options": ["request again", "cancel"]}
                current["updated"] = _now()
                self._event(
                    "recovered_confirmation",
                    current["question"],
                    task_id=current.get("id"),
                    resume_safe=True,
                    replayed_operations=False,
                )
                self._save()
                return
            current["status"] = "interrupted"
            current["updated"] = _now()
            self._archive_current_locked(current)
            self._event(
                "recovered",
                "Previous active task was interrupted before MARK restarted; no operation was replayed.",
                task_id=current.get("id"),
                resume_safe=False,
            )
            self._state["current"] = None
            self._save()

    def begin_task(self, title: str, request: dict | None = None, **metadata: Any) -> str:
        """Create a durable task envelope; alias kept distinct from a checklist plan."""
        return self.begin_turn(title, request=request, **metadata)

    def begin_turn(
        self,
        title: str,
        *,
        request: dict | None = None,
        language: str = "en",
        task_type: str = "general",
        intent: str = "",
        conversation_id: str = "",
    ) -> str:
        with self._lock:
            if self._state.get("current"):
                old = self._state["current"]
                if old.get("status") not in _TERMINAL:
                    old["status"] = "interrupted"
                    old["updated"] = _now()
                    self._archive_current_locked(old)
            turn_id = uuid.uuid4().hex[:12]
            original = dict(request or {})
            original.setdefault("original_message", title)
            original.setdefault("task_type", task_type)
            original.setdefault("intent", intent or title)
            original.setdefault("language", language)
            self._state["current"] = {
                "id": turn_id,
                "title": _safe_text(title, 180) or "MARK task",
                "request": _safe_value(original),
                "task_type": _safe_text(task_type, 50) or "general",
                "language": _safe_text(language, 12) or "en",
                "intent": _safe_text(intent or title, 240),
                "conversation_id": _safe_text(conversation_id, 100),
                "status": "active",
                "started": _now(),
                "updated": _now(),
                "resume_count": 0,
                "attempt": 1,
                "question": "",
                "clarification": None,
                "result": None,
                "operations": [],
                "conversation": [],
            }
            self._event("task_started", self._state["current"]["title"], task_id=turn_id, task_type=task_type, language=language)
            self._save()
            return turn_id

    def _current(self) -> dict | None:
        value = self._state.get("current")
        return value if isinstance(value, dict) else None

    def task_id(self) -> str:
        with self._lock:
            return str((self._current() or {}).get("id", ""))

    def begin_operation(self, tool: str, args: dict | None = None, *, risk: str = "read_only", requires_confirmation: bool = False, execution_mode: str = "immediate") -> str:
        with self._lock:
            current = self._current()
            if current is None:
                self.begin_turn(f"Standalone {tool} operation", task_type="standalone")
                current = self._current()
            op_id = uuid.uuid4().hex[:10]
            operation = {
                "id": op_id,
                "tool": _safe_text(tool, 100),
                "arguments": _safe_value(args or {}),
                "risk": _safe_text(risk, 40),
                "requires_confirmation": bool(requires_confirmation),
                "execution_mode": _safe_text(execution_mode, 30),
                "status": "running",
                "started": _now(),
                "updated": _now(),
            }
            current["operations"].append(operation)
            current["updated"] = _now()
            self._event("operation_started", f"{tool} started", task_id=current["id"], operation_id=op_id, tool=tool, execution_mode=execution_mode)
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
                task_id=(current or {}).get("id", ""),
                operation_id=operation_id,
                status=normalized.status,
                changed=normalized.changed,
                ok=normalized.ok,
            )
            self._save()
            return record

    def hold(self, status: str = "waiting_confirmation", *, question: str = "", detail: str = "") -> None:
        """Persist the current task while it waits for UI input or control."""
        with self._lock:
            current = self._current()
            if current is None:
                return
            current["status"] = str(status or "waiting_confirmation")[:40]
            if question:
                current["question"] = _safe_text(question, 600)
            current["updated"] = _now()
            self._event(
                "task_held",
                detail or ("Task is waiting for input." if current["status"] == "needs_input" else "Task is waiting for an interface control."),
                task_id=current.get("id"),
                status=current["status"],
            )
            self._save()

    def request_clarification(self, question: str, options: list[str] | None = None, conversation: list[dict] | None = None) -> dict | None:
        """Pause at ``needs_input`` without discarding the resumable buffer."""
        with self._lock:
            current = self._current()
            if current is None:
                return None
            current["status"] = "needs_input"
            current["question"] = _safe_text(question, 600)
            current["clarification"] = {
                "question": _safe_text(question, 600),
                "options": [_safe_text(item, 120) for item in (options or [])[:8]],
            }
            if conversation is not None:
                self._set_conversation_locked(conversation)
            current["updated"] = _now()
            self._event("needs_input", current["question"], task_id=current.get("id"), options=current["clarification"]["options"], resume_safe=True)
            self._save()
            return copy.deepcopy(current)

    def answer_clarification(self, answer: str) -> dict | None:
        """Record the answer and resume the same task; no prior tool is replayed."""
        with self._lock:
            current = self._current()
            if current is None or current.get("status") != "needs_input":
                return None
            clean = _safe_text(answer, 800)
            self._append_message_locked("user", clean)
            current["question"] = ""
            current["clarification"] = None
            current["status"] = "active"
            current["resume_count"] = int(current.get("resume_count", 0) or 0) + 1
            current["updated"] = _now()
            self._event("clarification_answered", clean, task_id=current.get("id"), resume_count=current["resume_count"], replayed_operations=False)
            self._save()
            return copy.deepcopy(current)

    def pending_input(self) -> dict | None:
        with self._lock:
            current = self._current()
            if not current or current.get("status") != "needs_input":
                return None
            return {
                "task_id": current.get("id", ""),
                "question": current.get("question", ""),
                "clarification": copy.deepcopy(current.get("clarification")),
            }

    def _append_message_locked(self, role: str, content: str, **fields: Any) -> None:
        current = self._current()
        if current is None:
            return
        message = {"role": _safe_text(role, 30), "content": _safe_text(content, 1800)}
        for key in ("name", "tool_calls"):
            if key in fields:
                message[key] = _safe_value(fields[key])
        current.setdefault("conversation", []).append(message)
        current["conversation"] = current["conversation"][-_MAX_CONVERSATION:]
        current["updated"] = _now()

    def append_message(self, role: str, content: str, **fields: Any) -> None:
        with self._lock:
            self._append_message_locked(role, content, **fields)
            self._save()

    def _set_conversation_locked(self, messages: list[dict]) -> None:
        current = self._current()
        if current is None:
            return
        bounded: list[dict] = []
        for raw in messages[-_MAX_CONVERSATION:]:
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role", "")).strip()
            if not role:
                continue
            item = {"role": _safe_text(role, 30), "content": _safe_text(raw.get("content", ""), 1800)}
            if raw.get("name"):
                item["name"] = _safe_text(raw.get("name"), 100)
            if raw.get("tool_calls"):
                item["tool_calls"] = _safe_value(raw.get("tool_calls"))
            bounded.append(item)
        current["conversation"] = bounded
        current["updated"] = _now()

    def set_conversation(self, messages: list[dict]) -> None:
        with self._lock:
            self._set_conversation_locked(messages)
            self._save()

    def conversation(self) -> list[dict]:
        with self._lock:
            return copy.deepcopy((self._current() or {}).get("conversation", []))

    def set_result(self, result: Any, *, status: str = "completed") -> None:
        with self._lock:
            current = self._current()
            if current is None:
                return
            current["result"] = _safe_value(result)
            current["status"] = str(status or "completed")[:40]
            current["updated"] = _now()
            self._event("task_result", "Task result recorded.", task_id=current.get("id"), status=current["status"])
            self._save()

    def resume(self, answer: str | None = None) -> None:
        """Resume a paused task trace; this never replays an operation."""
        with self._lock:
            current = self._current()
            if current is None:
                return
            if answer is not None and current.get("status") == "needs_input":
                # Call the locked helper rather than recursively taking the RLock.
                self._append_message_locked("user", answer)
                current["question"] = ""
                current["clarification"] = None
                current["resume_count"] = int(current.get("resume_count", 0) or 0) + 1
            if current.get("status") in {"paused", "waiting_confirmation", "needs_input"}:
                current["status"] = "active"
                current["updated"] = _now()
                self._event("task_resumed", "Task resumed; no previous operation was replayed.", task_id=current.get("id"), replayed_operations=False)
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
            self._event("confirmation_resolved", normalized.summary, task_id=current.get("id"), key=key, ok=normalized.ok)
            current["updated"] = _now()
            lower = normalized.summary.lower()
            remaining_waiting = any(item.get("status") == "waiting_confirmation" for item in current.get("operations", []))
            if "cancelled" in lower or "expired" in lower:
                current["status"] = "cancelled"
            elif remaining_waiting:
                current["status"] = "waiting_confirmation"
            elif normalized.ok and normalized.status != "waiting_confirmation":
                current["status"] = "completed"
            elif not normalized.ok:
                current["status"] = "failed"
            self._save()
            if current.get("status") in {"completed", "failed", "cancelled"}:
                self._archive_current_locked(current)
                self._state["current"] = None
                self._save()

    def end_turn(self, status: str = "completed", result: Any = None) -> None:
        with self._lock:
            current = self._current()
            if current is None:
                return
            status = str(status or "completed")[:40]
            if result is not None:
                current["result"] = _safe_value(result)
            current["status"] = status
            current["updated"] = _now()
            self._event("task_finished" if status in _TERMINAL else "task_held", f"Task {status}.", task_id=current["id"], status=status, resumable=status in _PRESERVED_ON_RESTART)
            if status in _PRESERVED_ON_RESTART:
                self._save()
                return
            self._archive_current_locked(current)
            self._state["current"] = None
            self._save()

    def snapshot(self, include_history: bool = False) -> dict:
        with self._lock:
            current = copy.deepcopy(self._state.get("current"))
            result = {"current": current, "task": copy.deepcopy(current), "events": copy.deepcopy(self._state.get("events", [])[-60:])}
            if include_history:
                result["history"] = copy.deepcopy(self._state.get("history", [])[-10:])
            return result

    def timeline(self, limit: int = 30) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._state.get("events", [])[-max(1, min(120, int(limit))):])

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
        if current.get("question"):
            lines.append("INPUT REQUIRED: " + _safe_text(current["question"], 320))
        request = current.get("request") or {}
        if request.get("task_type") or current.get("intent"):
            lines.append(f"ENVELOPE: type={current.get('task_type', 'general')} language={current.get('language', 'en')} intent={current.get('intent', '')[:180]}")
        for operation in current.get("operations", []):
            icon = {"running": "▶", "completed": "✓", "failed": "!", "waiting_confirmation": "?", "cancelled": "×", "preview": "◇"}.get(operation.get("status"), "○")
            lines.append(f"{icon} {operation.get('tool', 'tool')} [{operation.get('status', 'running')}] ({operation.get('execution_mode', 'immediate')})")
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

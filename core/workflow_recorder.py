"""Safe, user-visible workflow recording and replay state.

Recorded workflows contain tool names and non-sensitive arguments only. Passwords,
tokens, message bodies, clipboard content and free-form typed text are redacted.
Replay is delegated to MARK's normal executor so its existing confirmations and
allowlists remain in force.
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from core.approval_policy import assess_tool
from core.tool_contracts import normalize_result

BASE_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = BASE_DIR / "config" / "workflows.json"
_SECRET_WORDS = {"password", "passcode", "token", "secret", "credential", "api_key", "cookie", "authorization"}
_SENSITIVE_ACTIONS = {"type", "smart_type", "paste", "send", "send_message", "email_send"}
_lock = threading.RLock()
_active: dict | None = None
_executor: Callable[[str, dict], str] | None = None


def set_executor(fn: Callable[[str, dict], str] | None) -> None:
    global _executor
    _executor = fn


def _load_all() -> dict:
    try:
        value = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save_all(value: dict) -> None:
    WORKFLOW_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = WORKFLOW_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(WORKFLOW_PATH)


def _redact(value, key: str = ""):
    key_low = key.lower()
    if any(word in key_low for word in _SECRET_WORDS):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value[:50]]
    if isinstance(value, str) and (key_low in {"text", "message", "message_text", "code", "content"}):
        return "<redacted>"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)[:200]


def start(name: str, inputs: dict | None = None, permissions: list | None = None,
          confirmation_points: list | None = None, verification: list | None = None,
          recovery: str = "") -> str:
    global _active
    clean_permissions = [str(item)[:80] for item in (permissions or []) if str(item).strip()][:40]
    with _lock:
        _active = {
            "version": 2,
            "name": str(name or "workflow").strip()[:80],
            "created": datetime.now().isoformat(timespec="seconds"),
            "inputs": _redact(inputs or {}),
            "permissions": clean_permissions,
            "confirmation_points": [str(item)[:180] for item in (confirmation_points or []) if str(item).strip()][:20],
            "verification": [str(item)[:180] for item in (verification or []) if str(item).strip()][:20],
            "recovery": str(recovery or "Review the task runtime and use undo/checkpoint before replaying a failed mutation.")[:500],
            "steps": [],
        }
        try:
            stored = _load_all()
            stored.pop("__active__", None)
            _save_all(stored)
        except Exception:
            pass
    return f"Recording started: {_active['name']}. Sensitive text and credentials will be omitted."


def is_recording() -> bool:
    with _lock:
        return _active is not None


def record(tool_name: str, parameters: dict) -> None:
    global _active
    with _lock:
        if _active is None or tool_name in {"workflow_recorder", "task_planner"}:
            return
        safe = _redact(copy.deepcopy(parameters or {}))
        action = str((parameters or {}).get("action", "")).lower()
        if action in _SENSITIVE_ACTIONS or tool_name in {"send_message", "email_client"}:
            safe = {"action": action or "<redacted>"}
        elif tool_name == "save_memory":
            safe = {"category": safe.get("category", "notes"), "key": safe.get("key", "<redacted>"), "value": "<redacted>"}
        decision = assess_tool(str(tool_name), parameters or {})
        _active["steps"].append({
            "tool": str(tool_name),
            "parameters": safe,
            "risk": decision.risk,
            "requires_confirmation": decision.requires_confirmation,
            "verification": {"required": decision.risk != "read_only", "hint": "Fresh tool result or postcondition snapshot"} if decision.risk != "read_only" else {"required": False},
            "recovery": "Do not replay automatically; inspect the result and use undo/checkpoint." if decision.risk != "read_only" else "Retry only if the failure is transient and read-only.",
        })
        _active["steps"] = _active["steps"][-50:]
        try:
            # Recording is best-effort and must never block the requested tool.
            snapshot = copy.deepcopy(_active)
            all_workflows = _load_all()
            all_workflows["__active__"] = snapshot
            _save_all(all_workflows)
        except Exception:
            pass


def stop() -> dict | None:
    global _active
    with _lock:
        finished = _active
        _active = None
        if not finished:
            return None
        all_workflows = _load_all()
        all_workflows.pop("__active__", None)
        all_workflows[finished["name"]] = finished
        _save_all(all_workflows)
        return copy.deepcopy(finished)


def names() -> list[str]:
    with _lock:
        return sorted(name for name in _load_all() if name != "__active__")


def get(name: str) -> dict | None:
    with _lock:
        value = _load_all().get(str(name))
        return copy.deepcopy(value) if isinstance(value, dict) else None


def edit_step(name: str, index: int, parameters: dict | None = None, tool_name: str = "") -> str:
    with _lock:
        data = _load_all()
        workflow = data.get(str(name))
        if not isinstance(workflow, dict):
            return f"Workflow not found: {name}"
        steps = workflow.get("steps", [])
        try:
            position = int(index) - 1
        except (TypeError, ValueError):
            return "Workflow step must be an integer."
        if position < 0 or position >= len(steps):
            return "Workflow step does not exist."
        step = steps[position]
        if tool_name:
            step["tool"] = str(tool_name)[:64]
        if isinstance(parameters, dict):
            step["parameters"] = _redact(parameters)
        data[str(name)] = workflow
        _save_all(data)
        return describe(name)


def delete(name: str) -> bool:
    with _lock:
        data = _load_all()
        existed = str(name) in data
        data.pop(str(name), None)
        if existed:
            _save_all(data)
        return existed


def _contains_redacted(value) -> bool:
    if value == "<redacted>":
        return True
    if isinstance(value, dict):
        return any(_contains_redacted(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_redacted(item) for item in value)
    return False


def replay(name: str) -> str:
    workflow = get(name)
    if not workflow:
        return f"Workflow not found: {name}"
    if _executor is None:
        return "Workflow replay is unavailable until MARK's executor is ready."
    permissions = {str(item) for item in workflow.get("permissions", []) if str(item).strip()}
    lines = [f"Replaying workflow '{name}' — each mutating step still requires confirmation."]
    if workflow.get("confirmation_points"):
        lines.append("Confirmation points: " + "; ".join(str(item) for item in workflow["confirmation_points"][:6]))
    if workflow.get("verification"):
        lines.append("Verification contract: " + "; ".join(str(item) for item in workflow["verification"][:6]))
    for index, step in enumerate(workflow.get("steps", []), 1):
        tool = str(step.get("tool", ""))
        if permissions and tool not in permissions:
            lines.append(f"{index}. {tool}: stopped — tool is outside this workflow's permission manifest")
            break
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        if _contains_redacted(params):
            return f"Replay stopped at step {index}: sensitive input was redacted and must be supplied again."
        try:
            result = _executor(tool, dict(params))
        except Exception as exc:
            lines.append(f"{index}. {tool}: failed — {exc}")
            break
        contract = normalize_result(result, tool=tool, args=params)
        lines.append(f"{index}. {tool}: {contract.summary[:300]} [ok={contract.ok}; changed={contract.changed}; verification={'yes' if contract.verification else 'missing'}]")
        if not contract.ok:
            lines.append("Replay stopped after failure. Recovery: " + (workflow.get("recovery") or contract.recovery or "inspect the task runtime before deciding what to do next."))
            break
        if "[CONFIRMATION_PENDING]" in str(result):
            lines.append("Replay is paused until the confirmation is answered; call replay again to continue.")
            break
    return "\n".join(lines)


def describe(name: str) -> str:
    workflow = get(name)
    if not workflow:
        return f"Workflow not found: {name}"
    lines = [f"WORKFLOW {name} ({len(workflow.get('steps', []))} steps)"]
    lines.append("Permissions: " + (", ".join(workflow.get("permissions", [])) if workflow.get("permissions") else "captured tools only"))
    if workflow.get("inputs"):
        lines.append(f"Inputs: {workflow.get('inputs')}")
    if workflow.get("confirmation_points"):
        lines.append("Confirmation points: " + "; ".join(str(item) for item in workflow["confirmation_points"]))
    if workflow.get("verification"):
        lines.append("Verification: " + "; ".join(str(item) for item in workflow["verification"]))
    lines.append("Recovery: " + str(workflow.get("recovery", "inspect task runtime; use undo/checkpoint")))
    for i, step in enumerate(workflow.get("steps", []), 1):
        lines.append(f"{i}. {step.get('tool')} risk={step.get('risk', 'unknown')} confirm={step.get('requires_confirmation', False)} verify={step.get('verification', {})} {step.get('parameters', {})}")
    return "\n".join(lines)

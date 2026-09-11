"""Central authority, approval and emergency execution gate for MARK.

The model can request an action, but it cannot grant itself authority.  This
module provides one inspectable policy decision point around the existing
``core.approval_policy`` rules, persists approval/audit events locally, and
keeps an emergency pause/kill switch independent from the conversation loop.

It deliberately does not execute tools and does not broaden MARK's existing
safe-path, plugin-trust, Blender-MCP or confirmation rules.
"""
from __future__ import annotations

import copy
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.approval_policy import PolicyDecision, assess_tool

BASE_DIR = Path(__file__).resolve().parent.parent
AUTHORITY_PATH = BASE_DIR / "memory" / "authority_state.json"
_MAX_AUDIT = 500
_MAX_GRANTS = 80
_SECRET_RE = re.compile(
    r"(?i)\b(password|passcode|token|api[_ -]?key|secret|private[_ -]?key|cookie)\b\s*[:=]\s*[^\s,;]+"
)

# These tools are observability/control surfaces.  They remain available while
# an emergency pause is active so a user can inspect state and clear the gate.
_CONTROL_TOOLS = {
    "authority_control", "task_runtime", "recovery", "approval_policy",
    "agent_control", "system_status",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_text(value: Any, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return _SECRET_RE.sub(r"\1=<redacted>", text)[:limit]


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "<depth-limited>"
    if isinstance(value, dict):
        return {str(k)[:80]: _safe_value(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, list):
        return [_safe_value(item, depth + 1) for item in value[:30]]
    if isinstance(value, str):
        return _safe_text(value, 240)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _safe_text(value, 120)


def _category(decision: PolicyDecision) -> str:
    if decision.risk == "read_only":
        return "read"
    if decision.risk == "destructive_or_external":
        return "destructive" if not decision.reversible else "external"
    return "reversible"


@dataclass(frozen=True)
class AuthorityDecision:
    tool: str
    action: str
    category: str
    risk: str
    reversible: bool
    requires_approval: bool
    execution_mode: str
    allowed: bool
    reason: str
    emergency_mode: str = "normal"

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "action": self.action,
            "category": self.category,
            "risk": self.risk,
            "reversible": self.reversible,
            "requires_approval": self.requires_approval,
            "execution_mode": self.execution_mode,
            "allowed": self.allowed,
            "reason": self.reason,
            "emergency_mode": self.emergency_mode,
        }


class AuthorityEngine:
    """Persisted decision/audit state shared by desktop and remote controls."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or AUTHORITY_PATH)
        self._lock = threading.RLock()
        self._state = self._load()
        self._expire_grants_locked()

    def _empty(self) -> dict[str, Any]:
        return {
            "emergency": {"mode": "normal", "reason": "", "at": "", "actor": ""},
            "grants": [],
            "approvals": [],
            "audit": [],
        }

    def _load(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return self._empty()
            empty = self._empty()
            emergency = value.get("emergency") if isinstance(value.get("emergency"), dict) else {}
            empty["emergency"].update({k: _safe_value(emergency.get(k, "")) for k in empty["emergency"]})
            empty["emergency"]["mode"] = str(empty["emergency"].get("mode") or "normal") if str(empty["emergency"].get("mode") or "normal") in {"normal", "pause", "kill"} else "normal"
            empty["grants"] = [x for x in value.get("grants", [])[-_MAX_GRANTS:] if isinstance(x, dict)]
            empty["approvals"] = [x for x in value.get("approvals", [])[-_MAX_AUDIT:] if isinstance(x, dict)]
            empty["audit"] = [x for x in value.get("audit", [])[-_MAX_AUDIT:] if isinstance(x, dict)]
            return empty
        except Exception:
            return self._empty()

    def _save_locked(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            # Safety telemetry must never make an otherwise safe operation fail.
            pass

    def _expire_grants_locked(self) -> None:
        now = time.time()
        valid = []
        for grant in self._state.get("grants", []):
            try:
                if float(grant.get("expires_epoch", 0) or 0) > now:
                    valid.append(grant)
            except (TypeError, ValueError):
                continue
        self._state["grants"] = valid[-_MAX_GRANTS:]

    def _audit_locked(self, kind: str, *, actor: str = "system", task_id: str = "", tool: str = "", outcome: str = "", detail: str = "", **fields: Any) -> dict:
        row = {
            "time": _now(),
            "kind": _safe_text(kind, 80),
            "actor": _safe_text(actor, 80),
            "task_id": _safe_text(task_id, 80),
            "tool": _safe_text(tool, 120),
            "outcome": _safe_text(outcome, 100),
            "detail": _safe_text(detail, 400),
        }
        row.update({str(key)[:70]: _safe_value(value) for key, value in fields.items()})
        self._state["audit"].append(row)
        self._state["audit"] = self._state["audit"][-_MAX_AUDIT:]
        return copy.deepcopy(row)

    def _expire_approvals_locked(self) -> bool:
        now = time.time()
        changed = False
        for approval in self._state.get("approvals", []):
            if approval.get("status") != "pending":
                continue
            try:
                expired = float(approval.get("expires_epoch", 0) or 0) <= now
            except (TypeError, ValueError):
                expired = False
            if expired:
                approval["status"] = "expired"
                approval["resolved_at"] = _now()
                self._audit_locked(
                    "approval_expired",
                    task_id=str(approval.get("task_id", "")),
                    tool=str(approval.get("tool", "")),
                    outcome="expired",
                    detail="Approval expired before the interface resolved it.",
                    approval_key=approval.get("key", ""),
                )
                changed = True
        return changed

    def _emergency_locked(self) -> str:
        mode = str(self._state.get("emergency", {}).get("mode", "normal"))
        return mode if mode in {"normal", "pause", "kill"} else "normal"

    def begin_task(self, task_id: str, *, actor: str = "assistant") -> None:
        with self._lock:
            self._expire_grants_locked()
            self._audit_locked("task_started", actor=actor, task_id=task_id, outcome="accepted")
            self._save_locked()

    def decide(self, tool: str, args: dict | None = None, *, task_id: str = "", interface_approved: bool = False) -> AuthorityDecision:
        args = dict(args or {})
        base = assess_tool(tool, args)
        category = _category(base)
        action = base.action
        with self._lock:
            self._expire_grants_locked()
            approvals_changed = self._expire_approvals_locked()
            if approvals_changed:
                self._save_locked()
            emergency = self._emergency_locked()
            grant = next((item for item in reversed(self._state.get("grants", []))
                          if str(item.get("task_id", "")) == str(task_id)
                          and (str(item.get("tool", "")) in {"", str(tool)} or str(item.get("category", "")) == category)
                          and category == "reversible"), None)
        blocked_by_emergency = emergency != "normal" and str(tool) not in _CONTROL_TOOLS
        granted = bool(grant) and not base.risk == "destructive_or_external"
        emergency_control = str(tool) == "authority_control" and action in {"pause", "safety_pause", "kill", "emergency_stop"}
        requires = bool(base.requires_confirmation and not interface_approved and not granted and not emergency_control)
        if interface_approved:
            requires = False
        if blocked_by_emergency:
            reason = f"Emergency {emergency} gate is active; no tool execution is allowed until an explicit safety control clears it."
            return AuthorityDecision(str(tool), action, category, base.risk, base.reversible, False, "blocked", False, reason, emergency)
        if requires:
            reason = base.reason
            mode = "deferred" if category in {"external", "destructive"} else "inline"
        elif granted:
            reason = "A task-scoped human approval is active for this reversible action; destructive and external work is never covered by that grant."
            mode = "granted"
        else:
            reason = base.reason
            mode = "immediate"
        return AuthorityDecision(str(tool), action, category, base.risk, base.reversible, requires, mode, True, reason, emergency)

    def record_tool_started(self, tool: str, *, task_id: str = "", actor: str = "assistant", decision: AuthorityDecision | None = None) -> None:
        with self._lock:
            self._audit_locked("tool_started", actor=actor, task_id=task_id, tool=tool, outcome="allowed", decision=decision.as_dict() if decision else {})
            self._save_locked()

    def record_tool_finished(self, tool: str, outcome: str, *, task_id: str = "", actor: str = "assistant", changed: bool = False, ok: bool = False, detail: str = "") -> None:
        with self._lock:
            self._audit_locked("tool_finished", actor=actor, task_id=task_id, tool=tool, outcome=outcome, changed=changed, ok=ok, detail=detail)
            self._save_locked()

    def record_denied(self, tool: str, reason: str, *, task_id: str = "", actor: str = "assistant") -> None:
        with self._lock:
            self._audit_locked("tool_denied", actor=actor, task_id=task_id, tool=tool, outcome="denied", detail=reason)
            self._save_locked()

    def approval_requested(self, key: str, tool: str, *, task_id: str = "", execution_mode: str = "inline", actor: str = "assistant", detail: str = "") -> None:
        with self._lock:
            record = {
                "key": _safe_text(key, 160),
                "tool": _safe_text(tool, 120),
                "task_id": _safe_text(task_id, 80),
                "mode": _safe_text(execution_mode, 30),
                "status": "pending",
                "requested_at": _now(),
                "expires_at": datetime.fromtimestamp(time.time() + 90.0, tz=timezone.utc).isoformat(timespec="seconds"),
                "expires_epoch": time.time() + 90.0,
                "resolved_at": "",
            }
            self._state["approvals"].append(record)
            self._state["approvals"] = self._state["approvals"][-_MAX_AUDIT:]
            self._audit_locked("approval_requested", actor=actor, task_id=task_id, tool=tool, outcome="pending", detail=detail, approval_key=key, execution_mode=execution_mode)
            self._save_locked()

    def approval_resolved(self, key: str, outcome: str, *, task_id: str = "", tool: str = "", actor: str = "interface", detail: str = "") -> None:
        with self._lock:
            key = str(key or "")
            found = next((item for item in reversed(self._state.get("approvals", [])) if item.get("key") == key and item.get("status") == "pending"), None)
            if found:
                found["status"] = _safe_text(outcome, 40)
                found["resolved_at"] = _now()
                task_id = task_id or str(found.get("task_id", ""))
                tool = tool or str(found.get("tool", ""))
            self._audit_locked("approval_resolved", actor=actor, task_id=task_id, tool=tool, outcome=outcome, detail=detail, approval_key=key)
            self._save_locked()

    def grant_task(self, task_id: str, *, tool: str = "", category: str = "reversible", ttl: float = 1800, actor: str = "interface") -> bool:
        if not task_id or category != "reversible":
            return False
        with self._lock:
            self._expire_grants_locked()
            grant = {
                "task_id": _safe_text(task_id, 80),
                "tool": _safe_text(tool, 120),
                "category": category,
                "granted_at": _now(),
                "expires_epoch": time.time() + max(30.0, min(float(ttl), 7200.0)),
                "actor": _safe_text(actor, 80),
            }
            self._state["grants"].append(grant)
            self._state["grants"] = self._state["grants"][-_MAX_GRANTS:]
            self._audit_locked("task_grant", actor=actor, task_id=task_id, tool=tool, outcome="granted", detail="Reversible task-scoped grant created.", category=category)
            self._save_locked()
            return True

    def set_emergency(self, mode: str, reason: str = "", *, actor: str = "interface") -> dict:
        mode = str(mode or "normal").lower().strip()
        if mode not in {"normal", "pause", "kill"}:
            raise ValueError("Emergency mode must be normal, pause or kill.")
        with self._lock:
            self._state["emergency"] = {"mode": mode, "reason": _safe_text(reason, 300), "at": _now(), "actor": _safe_text(actor, 80)}
            self._audit_locked("emergency_control", actor=actor, outcome=mode, detail=reason)
            self._save_locked()
            return copy.deepcopy(self._state["emergency"])

    def emergency_status(self) -> dict:
        with self._lock:
            self._expire_grants_locked()
            if self._expire_approvals_locked():
                self._save_locked()
            return {
                **copy.deepcopy(self._state.get("emergency", {})),
                "pending_approvals": sum(1 for item in self._state.get("approvals", []) if item.get("status") == "pending"),
                "active_grants": len(self._state.get("grants", [])),
            }

    def audit(self, limit: int = 50) -> list[dict]:
        with self._lock:
            if self._expire_approvals_locked():
                self._save_locked()
            return copy.deepcopy(self._state.get("audit", [])[-max(1, min(int(limit), 200)):])

    def approvals(self, limit: int = 30) -> list[dict]:
        with self._lock:
            if self._expire_approvals_locked():
                self._save_locked()
            return copy.deepcopy(self._state.get("approvals", [])[-max(1, min(int(limit), 100)):])


_ENGINE = AuthorityEngine()


def get_authority() -> AuthorityEngine:
    return _ENGINE


def authority_status() -> dict:
    return _ENGINE.emergency_status()

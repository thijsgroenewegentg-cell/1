"""Structured contracts for tool results.

MARK's tools pre-date a common result type and therefore still return human
readable strings.  This module lets the runtime attach reliable status,
change, verification and recovery metadata without breaking those handlers.
It deliberately contains no executor and grants no permission to run a tool.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_FAILURE_MARKERS = (
    "failed", "failure reason:", "could not", "unavailable", "offline",
    "rejected", "refused", "timed out", "timeout", "blocked", "not found",
    "not configured", "[confirmation_pending]",
)
_PENDING_MARKERS = ("[confirmation_pending]", "confirmation waiting", "awaiting confirmation")
_MUTATING_ACTIONS = {
    "add", "apply", "build", "clean", "complete", "copy", "create", "delete",
    "download", "edit", "generate", "install", "move", "organize", "remove",
    "rename", "render", "replay", "restore", "run", "save", "send", "set",
    "skip", "type", "update", "upload", "write",
}
_SECRET_RE = re.compile(
    r"(?i)\b(password|passcode|token|api[_ -]?key|secret|private[_ -]?key|cookie)\b\s*[:=]\s*[^\s,;]+"
)


def _safe_text(value: Any, limit: int = 700) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = _SECRET_RE.sub(r"\1=<redacted>", text)
    return text[:limit]


def _safe_value(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "<depth-limited>"
    if isinstance(value, dict):
        return {str(k)[:80]: _safe_value(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return [_safe_value(v, depth + 1) for v in value[:40]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return _safe_text(value, 300) if isinstance(value, str) else value
    return _safe_text(value, 120)


def looks_failed(text: str) -> bool:
    lower = str(text or "").lower()
    return any(marker in lower for marker in _FAILURE_MARKERS)


def is_confirmation_pending(text: str) -> bool:
    lower = str(text or "").lower()
    return any(marker in lower for marker in _PENDING_MARKERS)


def infer_changed(tool: str = "", args: dict | None = None, text: str = "") -> bool:
    """Conservative change inference for legacy string-returning handlers."""
    if looks_failed(text) or is_confirmation_pending(text):
        return False
    name = str(tool or "").lower()
    action = str((args or {}).get("action", "")).lower().replace("-", "_")
    if action in _MUTATING_ACTIONS:
        return True
    if any(word in name for word in ("create", "delete", "write", "send", "install", "render", "update", "control")):
        return True
    return False


@dataclass
class ToolResult:
    """Stable machine-readable representation of one tool outcome."""

    ok: bool
    summary: str
    tool: str = ""
    changed: bool = False
    changed_items: list[str] = field(default_factory=list)
    reversible: bool = False
    risk: str = "read_only"
    verification: dict[str, Any] = field(default_factory=dict)
    recovery: str = ""
    artifacts: list[str] = field(default_factory=list)
    status: str = "completed"
    raw: str = ""

    def __post_init__(self) -> None:
        self.tool = str(self.tool or "")[:100]
        self.summary = _safe_text(self.summary, 1200) or ("Tool completed." if self.ok else "Tool failed.")
        self.raw = _safe_text(self.raw or self.summary, 1600)
        self.status = str(self.status or ("completed" if self.ok else "failed"))[:40]
        self.recovery = _safe_text(self.recovery, 400)
        self.changed_items = [_safe_text(item, 240) for item in self.changed_items[:30]]
        self.artifacts = [_safe_text(item, 240) for item in self.artifacts[:20]]
        self.verification = _safe_value(self.verification) if isinstance(self.verification, dict) else {}

    def as_text(self) -> str:
        """Keep legacy text while appending a compact machine-readable contract."""
        text = self.raw or self.summary
        verification = "yes" if self.verification else "missing"
        changed_items = ",".join(self.changed_items[:6]) or "none"
        recovery = self.recovery or "none"
        return (
            f"{text}\n[TOOL_RESULT ok={str(self.ok).lower()} status={self.status} "
            f"changed={str(self.changed).lower()} changed_items={changed_items} "
            f"reversible={str(self.reversible).lower()} verification={verification} "
            f"recovery={recovery}]"
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "summary": self.summary,
            "tool": self.tool,
            "changed": self.changed,
            "changed_items": self.changed_items,
            "reversible": self.reversible,
            "risk": self.risk,
            "verification": self.verification,
            "recovery": self.recovery,
            "artifacts": self.artifacts,
            "status": self.status,
        }


def normalize_result(value: Any, tool: str = "", args: dict | None = None) -> ToolResult:
    """Normalize legacy strings, dictionaries and tuples without executing anything."""
    if isinstance(value, ToolResult):
        if not value.tool:
            value.tool = str(tool or "")[:100]
        return value
    if isinstance(value, tuple) and len(value) >= 2:
        ok, detail = bool(value[0]), value[1]
        return normalize_result({"ok": ok, "summary": detail}, tool, args)
    if isinstance(value, dict):
        summary = value.get("summary") or value.get("message") or value.get("detail") or ""
        ok = bool(value.get("ok", not looks_failed(str(summary))))
        return ToolResult(
            ok=ok,
            summary=str(summary),
            tool=tool or str(value.get("tool", "")),
            changed=bool(value.get("changed", False)),
            changed_items=value.get("changed_items", []) if isinstance(value.get("changed_items"), list) else [],
            reversible=bool(value.get("reversible", False)),
            risk=str(value.get("risk", "read_only")),
            verification=value.get("verification") if isinstance(value.get("verification"), dict) else {},
            recovery=str(value.get("recovery", "")),
            artifacts=value.get("artifacts", []) if isinstance(value.get("artifacts"), list) else [],
            status=str(value.get("status", "completed" if ok else "failed")),
            raw=str(value.get("raw", summary)),
        )
    text = str(value or "Done.")
    pending = is_confirmation_pending(text)
    cancelled = "cancelled" in text.lower() or "expired" in text.lower()
    failed = (looks_failed(text) and not pending) or cancelled
    verification: dict[str, Any] = {}
    if "verification" in text.lower() or "verified" in text.lower():
        verification = {"reported": True}
    return ToolResult(
        ok=not failed,
        summary=text,
        tool=tool,
        changed=infer_changed(tool, args, text),
        reversible=False,
        verification=verification,
        recovery=("Check the current state before retrying; use undo or the named checkpoint." if failed else ""),
        status="waiting_confirmation" if pending else ("cancelled" if cancelled else ("failed" if failed else "completed")),
        raw=text,
    )

"""Durable, local-only store for opt-in proactive alerts.

Alerts are deduplicated and retained so a user can inspect something MARK
noticed while they were away instead of relying on a spoken notification.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
ALERT_PATH = BASE_DIR / "memory" / "proactive_alerts.json"
_MAX_ALERTS = 120
_LOCK = RLock()
_SECRET_RE = re.compile(r"(?i)\b(password|passcode|token|api[_ -]?key|secret|private[_ -]?key|cookie)\b\s*[:=]\s*\S+")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load() -> dict:
    try:
        value = json.loads(ALERT_PATH.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            alerts = [item for item in value.get("alerts", []) if isinstance(item, dict)]
            return {"alerts": alerts[-_MAX_ALERTS:]}
    except Exception:
        pass
    return {"alerts": []}


def _save(value: dict) -> None:
    try:
        ALERT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = ALERT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(ALERT_PATH)
    except OSError:
        pass


def record_alert(kind: str, message: str, *, source: str = "", dedupe_key: str = "", metadata: dict | None = None) -> dict:
    message = " ".join(str(message or "").split())
    message = _SECRET_RE.sub(r"\1=<redacted>", message)[:1200]
    key = dedupe_key or hashlib.sha256(f"{kind}|{message}".encode("utf-8", errors="replace")).hexdigest()[:20]
    with _LOCK:
        value = _load()
        for alert in value["alerts"]:
            if alert.get("key") == key and not alert.get("dismissed"):
                alert["last_seen"] = _now()
                _save(value)
                return dict(alert)
        alert = {
            "id": hashlib.sha256(f"{key}|{_now()}".encode()).hexdigest()[:12],
            "key": key,
            "kind": str(kind or "general")[:50],
            "source": str(source or "")[:120],
            "message": message,
            "created": _now(),
            "last_seen": _now(),
            "read": False,
            "dismissed": False,
            "metadata": metadata if isinstance(metadata, dict) else {},
        }
        value["alerts"].append(alert)
        value["alerts"] = value["alerts"][-_MAX_ALERTS:]
        _save(value)
        return dict(alert)


def list_alerts(*, unread_only: bool = False, limit: int = 20) -> list[dict]:
    with _LOCK:
        alerts = _load()["alerts"]
        rows = [item for item in reversed(alerts) if not item.get("dismissed") and (not unread_only or not item.get("read"))]
        return [dict(item) for item in rows[:max(1, min(100, int(limit)))]]


def mark_read(alert_id: str) -> bool:
    with _LOCK:
        value = _load()
        changed = False
        for alert in value["alerts"]:
            if str(alert.get("id")) == str(alert_id):
                alert["read"] = True
                changed = True
        if changed:
            _save(value)
        return changed


def dismiss(alert_id: str) -> bool:
    with _LOCK:
        value = _load()
        changed = False
        for alert in value["alerts"]:
            if str(alert.get("id")) == str(alert_id):
                alert["dismissed"] = True
                changed = True
        if changed:
            _save(value)
        return changed


def unread_count() -> int:
    return len(list_alerts(unread_only=True, limit=_MAX_ALERTS))

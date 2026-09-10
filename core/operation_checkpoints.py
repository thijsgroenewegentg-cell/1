"""Durable operation journal used to explain and recover larger changes.

This journal never grants permission to perform an operation. It records what
MARK attempted, whether a change was reported, and which user-visible recovery
mechanism applies. Files have byte checkpoints; Blender and calendar operations
can point to their own snapshot/undo path.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "memory" / "checkpoints"
PATH = ROOT / "operations.json"
_lock = threading.RLock()


def _load() -> list[dict]:
    try:
        value = json.loads(PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except Exception:
        return []


def record(component: str, operation: str, result: str = "", changed: bool = False,
           recovery: str = "Use undo or the named checkpoint if available.") -> dict:
    entry = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "component": str(component)[:80],
        "operation": str(operation)[:100],
        "changed": bool(changed),
        "result": str(result)[:500],
        "recovery": str(recovery)[:300],
    }
    try:
        with _lock:
            rows = _load()
            rows.append(entry)
            ROOT.mkdir(parents=True, exist_ok=True)
            PATH.write_text(json.dumps(rows[-100:], indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        # A journal failure must never turn a successful user action into a
        # reported tool failure.
        pass
    return entry


def recent(limit: int = 20) -> list[dict]:
    with _lock:
        return _load()[-max(1, min(100, int(limit))):]


def clear() -> None:
    with _lock:
        try:
            PATH.unlink(missing_ok=True)
        except OSError:
            pass

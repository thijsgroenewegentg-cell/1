# /core/failures.py
"""A compact, durable record of JARVIS's own stumbles.

Every unhandled error during a turn is appended here (one JSON object per
line, next to the session journal — same engine-agnostic, no-SQLite choice).
The autopsy question ("what went wrong?", "why did you fail?") is answered
deterministically from this file, newest first, grouped by what actually
broke. Nothing here ever blocks a turn: a failed write is logged and ignored.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.failures")

#: Keep the file bounded: rotate to ``failures.jsonl.old`` past this size.
_ROTATE_BYTES = 200_000

#: How many recent failures the summary reads.
_SUMMARY_LIMIT = 8


def _failures_path(config: Any) -> Path:
    """The JSON-lines file, stored beside the session journal."""
    try:
        journal = config.resolve(
            config.get("assistant.journal_file", "data/journal.json")
        )
        return journal.parent / "failures.jsonl"
    except Exception:
        return Path("data/failures.jsonl")


def note_failure(
    config: Any,
    *,
    text: str,
    error: str,
    module: str = "",
) -> None:
    """Append one failure record.

    Args:
        config: Configuration (used only to locate the file).
        text: The user utterance that led to the failure.
        error: The exception message.
        module: The module in charge at the time, when known.
    """
    try:
        path = _failures_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _ROTATE_BYTES:
            old = path.with_suffix(path.suffix + ".old")
            if old.exists():
                old.unlink()
            path.replace(old)
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "day": datetime.now().strftime("%Y-%m-%d"),
            "text": (text or "")[:300],
            "error": (error or "")[:400],
            "module": module or "",
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # defensive: a record must never break a turn
        logger.debug("Failure record write failed: %s", exc)


def recent(config: Any, limit: int = _SUMMARY_LIMIT) -> List[Dict[str, Any]]:
    """The newest failure records, oldest first within the returned slice.

    Args:
        config: Configuration (used only to locate the file).
        limit: How many records to return.

    Returns:
        Failure dicts (newest first).
    """
    try:
        path = _failures_path(config)
        if not path.exists():
            return []
        records: List[Dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
        records.sort(key=lambda r: str(r.get("ts", "")), reverse=True)
        return records[:limit]
    except Exception as exc:  # pragma: no cover - read must never raise
        logger.debug("Failure record read failed: %s", exc)
        return []


def summary(config: Any, limit: int = _SUMMARY_LIMIT) -> Optional[str]:
    """A short spoken-friendly diagnosis of recent failures.

    Args:
        config: Configuration (used only to locate the file).
        limit: How many recent records to consider.

    Returns:
        A diagnosis paragraph, or ``None`` when there is nothing on record.
    """
    records = recent(config, limit)
    if not records:
        return None
    top = Counter(str(r.get("error", "unknown"))[:90] for r in records)
    most_common, count = top.most_common(1)[0]
    latest = records[0]
    module = f" while handling {latest.get('module') or 'a request'}"
    line = (
        f"I've logged {len(records)} stumble(s) recently. The recurring one "
        f"({count}×) is: {most_common!r}. The latest{module} was "
        f"\"{str(latest.get('text', ''))[:120]}\" and it said: "
        f"{str(latest.get('error', ''))[:160]}. "
        "Say 'look into that failure' and I'll investigate."
    )
    return line


__all__ = ["note_failure", "recent", "summary"]

# /core/threads.py
"""Open threads — the loose ends JARVIS promised to come back to.

When a reply commits to future action ("I'll check that file and get back to
you", "ik kijk ernaar en kom erop terug"), the thread is stored as a JSON
line next to the journal. "What's still open?" (wat staat er nog open) lists
them newest first; "that's sorted" (is geregeld) closes one by number or by
matching text. Engine-agnostic file storage, no model, survives restarts.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from utils.logger import get_logger

logger = get_logger("core.threads")

#: Keep the file bounded.
_ROTATE_BYTES = 150_000

#: Commitment phrasing in JARVIS's own replies — EN + NL. Group 1 is an
#: optional short subject after the verb.
_PROMISE = (
    # EN
    re.compile(
        r"\b(i'?ll|i will)\s+(?:get back|come back|follow up|look into|check|"
        r"look at|have a look|send|email|update|report|let you know|"
        r"pick this up|circle back)\b",
        re.I,
    ),
    # NL — phrased freely ("ik kijk ernaar en kom erop terug").
    re.compile(
        r"\b(?:ik\s+)?(?:kom erop terug|laat het je weten|houd je op de "
        r"hoogte|hou je op de hoogte)\b|"
        r"\b(?:ik\s+)?kijk er(?:naar| even naar)\b|"
        r"\bik\s+ga\s+(?:even\s+)?(?:kijken|nakijken|onderzoeken|uitzoeken|"
        r"melden)\b|"
        r"\bik\s+(?:stuur het|zoek het uit|zoek uit|onderzoek het)\b",
        re.I,
    ),
)

#: The close/“no longer needed” commands, EN + NL (matched on the request).
_CLOSE_PHRASES = (
    "never mind", "forget it", "cancel that", "not needed",
    "that's sorted", "that is sorted", "dat is geregeld", "is geregeld",
    "laat maar", "niet meer nodig", "kan weg", "afgevinkt", "afgehandeld",
    "afhandelen", "weg ermee", "klaar mee", "is afgerond",
)


def _path(config: Any) -> Path:
    try:
        journal = config.resolve(
            config.get("assistant.journal_file", "data/journal.json")
        )
        return journal.parent / "threads.jsonl"
    except Exception:
        return Path("data/threads.jsonl")


def _now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


def promises(response: str) -> List[str]:
    """Any promise phrase found in a reply (for tests and bookkeeping)."""
    found: List[str] = []
    for pattern in _PROMISE:
        match = pattern.search(response or "")
        if match:
            found.append(match.group(0))
    return found


def note_thread(
    config: Any,
    *,
    request: str,
    response: str,
    module: str = "",
    kind: str = "promise",
) -> bool:
    """Store one open thread if the reply committed to a follow-up.

    Args:
        config: Configuration (locates the file).
        request: The user's request.
        response: JARVIS's reply that contained the commitment.
        module: Module that handled the turn.
        kind: ``"promise"`` or another small label.

    Returns:
        True when a thread was stored (a commitment was found and it is not
        an obvious duplicate of the newest thread).
    """
    raw = (response or "").strip()
    if not raw or not promises(raw):
        return False
    try:
        path = _path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _ROTATE_BYTES:
            old = path.with_suffix(path.suffix + ".old")
            if old.exists():
                old.unlink()
            path.replace(old)
        lines = (request or "")[:140], (raw or "")[:200], module or "", kind
        entry = {
            "ts": _now(),
            "day": datetime.now().strftime("%Y-%m-%d"),
            "request": lines[0],
            "reply": lines[1],
            "module": lines[2],
            "kind": lines[3],
        }
        existing = list_threads(config, limit=1)
        if existing and existing[0].get("request") == entry["request"]:
            return False  # newest thread already covers this request
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:  # defensive: bookkeeping must never break a turn
        logger.debug("Thread note failed: %s", exc)
        return False


def list_threads(config: Any, limit: int = 12) -> List[Dict[str, Any]]:
    """The newest open threads.

    Args:
        config: Configuration (locates the file).
        limit: How many to return.

    Returns:
        Thread dicts, newest first.
    """
    try:
        path = _path(config)
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
        records.sort(key=lambda record: str(record.get("ts", "")), reverse=True)
        return records[:limit]
    except Exception as exc:  # pragma: no cover - reads never raise
        logger.debug("Thread list failed: %s", exc)
        return []


def _matches(record: Dict[str, Any], needle: str) -> bool:
    needle = needle.lower().strip()
    haystacks = [str(record.get("request", "")), str(record.get("reply", ""))]
    return any(needle and needle in haystack.lower() for haystack in haystacks)


def close_thread(config: Any, needle: str) -> Tuple[int, int]:
    """Close threads matching a number (1 = newest) or some text.

    Args:
        config: Configuration (locates the file).
        needle: e.g. ``"1"`` for the newest thread, or text to match.

    Returns:
        ``(removed, remaining)`` counts.
    """
    try:
        path = _path(config)
        if not path.exists():
            return 0, 0
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        records: List[Dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
        records.sort(key=lambda record: str(record.get("ts", "")), reverse=True)
        removed: List[Dict[str, Any]] = []
        if (needle or "").strip().isdigit():
            index = int(needle.strip()) - 1
            if 0 <= index < len(records):
                removed.append(records.pop(index))
        else:
            kept: List[Dict[str, Any]] = []
            for record in records:
                if _matches(record, needle):
                    removed.append(record)
                else:
                    kept.append(record)
            records = kept
        remaining = len(records)
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return len(removed), remaining
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Thread close failed: %s", exc)
        return 0, 0


def is_close_command(text: str) -> bool:
    """Whether an utterance reads as closing loose ends rather than a promise."""
    lowered = (text or "").lower().strip()
    lowered = lowered.lstrip("0123456789. ")  # "afvinken 2", "close #1"
    return any(phrase in lowered for phrase in _CLOSE_PHRASES) or bool(
        re.match(r"^(?:close|done|clear|afvinken|weg|klaar)\b", lowered)
    )


__all__ = [
    "close_thread",
    "is_close_command",
    "list_threads",
    "note_thread",
    "promises",
]

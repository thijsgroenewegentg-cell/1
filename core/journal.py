# /core/journal.py
"""A tiny, always-on session journal so JARVIS can answer "what were we doing?".

Every completed turn appends one JSON line to ``assistant.journal_file``:
when it happened, what the user asked (truncated), which module handled it
and which tools ran. That is enough to rebuild a day ("you finished three
todos, rendered the donut, and asked about the weather") without a model,
without the vector memory, and even if the embedding database was wiped.

The file is append-only and pruned by rotation when it grows past a size
cap, so it stays cheap for years.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.journal")

#: Rotate once the live file passes this many bytes.
_ROTATE_BYTES = 300_000

#: How long an entry's user text may be when stored.
_MAX_TEXT = 120


def _journal_path(config: Any) -> Path:
    """Resolve ``assistant.journal_file`` against the config root.

    Args:
        config: The global configuration (or a plain dict in tests).

    Returns:
        The absolute-ish path of the journal file.
    """
    raw = str(config.get("assistant.journal_file", "data/journal.json") or "")
    resolve = getattr(config, "resolve", None)
    if callable(resolve):
        return resolve(raw)
    return Path(raw).expanduser()


def _entries_from(path: Path) -> List[Dict[str, Any]]:
    """Read every journal line from one file.

    Args:
        path: The journal file.

    Returns:
        A list of entries in written order.
    """
    if not path.is_file():
        return []
    entries: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if isinstance(entry, dict) and entry.get("ts"):
                    entries.append(entry)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Journal read failed: %s", exc)
    return entries


def note_turn(
    config: Any,
    *,
    text: str,
    response: str,
    module: str,
    tools: Optional[List[str]] = None,
    ok: bool = True,
) -> None:
    """Append one completed turn to the journal.

    Args:
        config: Configuration holding ``assistant.journal_file``.
        text: What the user asked.
        response: What JARVIS answered.
        module: The module that handled the turn (or ``"conversation"``).
        tools: Tool references that ran during the turn.
        ok: Whether the turn produced a usable reply.
    """
    path = _journal_path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _ROTATE_BYTES:
            old = path.with_suffix(path.suffix + ".old")
            if old.exists():
                old.unlink()
            os.replace(path, old)
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "day": datetime.now().strftime("%Y-%m-%d"),
            "text": (text or "")[:_MAX_TEXT],
            "response": (response or "")[:_MAX_TEXT],
            "module": module or "conversation",
            "tools": [str(tool) for tool in (tools or [])][:8],
            "ok": bool(ok),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # defensive: journaling must never break a turn
        logger.debug("Journal write failed: %s", exc)


def _load(config: Any) -> List[Dict[str, Any]]:
    """Read the journal, including a rotated predecessor if any."""
    path = _journal_path(config)
    return _entries_from(path.with_suffix(path.suffix + ".old")) + _entries_from(path)


def events_on(config: Any, day: str) -> List[Dict[str, Any]]:
    """Return the journal entries for one calendar day.

    Args:
        config: Configuration holding ``assistant.journal_file``.
        day: ``YYYY-MM-DD``.

    Returns:
        Entries for that day, oldest first.
    """
    return [entry for entry in _load(config) if str(entry.get("day", "")) == day]


def _friendly_day(day: str) -> str:
    """Turn ``YYYY-MM-DD`` into ``Tuesday 8 September``-style text."""
    try:
        moment = datetime.strptime(day, "%Y-%m-%d")
    except Exception:
        return day
    return f"{moment:%A} {moment.day} {moment:%B}"


def day_before(day: str, delta: int = 1) -> str:
    """Return the date ``delta`` days before ``day``.

    Args:
        day: ``YYYY-MM-DD``.
        delta: How many days to go back.

    Returns:
        The earlier date as ``YYYY-MM-DD``.
    """
    try:
        moment = datetime.strptime(day, "%Y-%m-%d")
    except Exception:
        moment = datetime.now()
    return (moment - timedelta(days=delta)).strftime("%Y-%m-%d")


def recap(config: Any, day: str, sample: int = 4) -> str:
    """Summarise one day of activity as a spoken sentence.

    Args:
        config: Configuration holding ``assistant.journal_file``.
        day: ``YYYY-MM-DD``.
        sample: How many recent requests to quote.

    Returns:
        A short human summary, safe to speak.
    """
    entries = events_on(config, day)
    if not entries:
        return f"{_friendly_day(day)} is quiet in the journal — nothing recorded."
    modules: Dict[str, int] = {}
    tools: Dict[str, int] = {}
    for entry in entries:
        module = str(entry.get("module", "conversation"))
        modules[module] = modules.get(module, 0) + 1
        for tool in entry.get("tools", []) or []:
            tools[str(tool)] = tools.get(str(tool), 0) + 1
    top_modules = ", ".join(
        f"{name} ({count}×)" for name, count in
        sorted(modules.items(), key=lambda item: item[1], reverse=True)[:3]
    )
    top_tools = ", ".join(
        tool for tool, _count in
        sorted(tools.items(), key=lambda item: item[1], reverse=True)[:4]
    )
    recent = "; ".join(
        f"\"{entry.get('text', '')}\"" for entry in entries[-sample:]
    )
    parts = [
        f"{_friendly_day(day)}: {len(entries)} exchange(s)",
    ]
    if top_modules:
        parts.append(f"mainly {top_modules}")
    if top_tools:
        parts.append(f"tools used: {top_tools}")
    parts.append(f"the last few were {recent}.")
    return " ".join(parts)


def brief_line(config: Any, day: str) -> str:
    """A one-liner for the morning briefing about the previous day.

    Args:
        config: Configuration holding ``assistant.journal_file``.
        day: The day to summarise (usually yesterday).

    Returns:
        A compact line, or ``""`` when nothing was recorded.
    """
    entries = events_on(config, day)
    if not entries:
        return ""
    completed = sum(1 for entry in entries if entry.get("ok"))
    tools: Dict[str, int] = {}
    for entry in entries:
        for tool in entry.get("tools", []) or []:
            tools[str(tool)] = tools.get(str(tool), 0) + 1
    tool_names = ", ".join(
        tool for tool, _count in
        sorted(tools.items(), key=lambda item: item[1], reverse=True)[:3]
    )
    line = f"Yesterday: {len(entries)} request(s), {completed} answered well."
    if tool_names:
        line += f" Tools that got used: {tool_names}."
    return line


def search(config: Any, topic: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Find journal entries mentioning a topic, newest first.

    Keyword search over the journal lines (user text and replies) — no model,
    no vector store. Used to answer "what did I say about X?" with receipts.

    Args:
        config: Configuration holding ``assistant.journal_file``.
        topic: What the user is asking about (a phrase or several words).
        limit: Maximum entries to return.

    Returns:
        Matching entries (newest first), each a dict with ``ts``, ``day``,
        ``module``, ``text`` and ``response``.
    """
    raw = (topic or "").strip().lower()
    if not raw:
        return []
    # Stopwords add noise; only content words count as searchable tokens.
    stop = {
        "about", "and", "the", "that", "with", "from", "was", "were", "did",
        "you", "your", "i", "my", "me", "we", "it", "is", "are", "on", "in",
        "for", "of", "a", "an", "to", "have", "has", "had", "what", "when",
        "say", "said", "tell", "told", "talked", "mention", "mentioned",
        "remember", "do", "does", "this", "these", "those", "there", "not",
    }
    tokens = [word for word in re.findall(r"[a-z0-9']+", raw)
              if word not in stop and len(word) > 2]
    if not tokens:
        return []

    scored: List[tuple] = []
    for entry in _load(config):
        haystack = (
            f"{entry.get('text', '')} {entry.get('response', '')}".lower()
        )
        hits = sum(1 for word in tokens if word in haystack)
        if not hits:
            continue
        scored.append((hits, str(entry.get("ts", "")), entry))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [entry for _hits, _ts, entry in scored[:limit]]


__all__ = [
    "brief_line",
    "day_before",
    "events_on",
    "note_turn",
    "recap",
    "search",
]

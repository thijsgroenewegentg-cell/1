# /core/unified_search.py
"""One query, everything searched — offline.

"Waar stond dat ook alweer?" / "where did I write about X?" searches every
place JARVIS keeps your data in a single pass:

* todos, reminders, notes (SQLite, shared productivity database),
* stored facts and past conversations (SQLite ``facts``/``conversations``),
* the session journal file,
* the learned profile (name, standing corrections, routines),
* armed macros (trigger phrases).

Everything is keyword matching over local files/databases — no model, no
embeddings, no network. Hits are grouped by source so the reply reads as a
receipt list the user can trust.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.journal import _load as _load_journal
from utils.logger import get_logger

logger = get_logger("core.unified_search")

#: Words that carry no search meaning.
_STOP = {
    "the", "a", "an", "and", "of", "to", "you", "your", "that", "about",
    "where", "did", "was", "were", "what", "when", "which", "who", "how",
    "de", "het", "een", "en", "van", "dat", "wat", "waar", "stond", "staat",
    "ook", "nog", "alweer", "had", "heb", "hebben", "met", "voor", "over",
    "ik", "je", "mijn", "jouw", "naar", "op", "in", "is", "zijn", "niet",
    "ook alweer", "everything", "search", "zoek", "alle", "alles",
    "i", "we", "us", "my", "me", "write", "schreef", "geschreven", "noteerde",
}

#: Query words used for matching, from the raw user phrase.
def _tokens(query: str) -> List[str]:
    return [
        token for token in re.findall(r"[a-z0-9à-ÿ']+", (query or "").lower())
        if len(token) > 1 and token not in _STOP
    ]


def _day(ts: str) -> str:
    raw = (ts or "")[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return (raw or "") or ""


def _hit(source: str, when: str, text: str, detail: str = "") -> Dict[str, str]:
    return {"source": source, "when": when, "text": (text or "").strip(),
            "detail": (detail or "").strip()}


def _scan_sqlite(db_path: Path, tokens: List[str]) -> List[Dict[str, str]]:
    """Match open todos, reminders, notes, facts and past conversations."""
    hits: List[Dict[str, str]] = []
    try:
        if not db_path.exists():
            return hits
        connection = sqlite3.connect(str(db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            def match(hay: str) -> bool:
                hay = (hay or "").lower()
                return any(token in hay for token in tokens)

            rows = connection.execute(
                "SELECT id, task, due FROM todos WHERE done = 0"
            ).fetchall()
            for row in rows:
                if match(row["task"]):
                    hits.append(_hit(
                        "todo", "", row["task"],
                        f"#{row['id']}" + (f" (due {row['due']})" if row["due"] else ""),
                    ))

            rows = connection.execute(
                "SELECT id, text, due FROM reminders WHERE fired = 0"
            ).fetchall()
            for row in rows:
                if match(row["text"]):
                    hits.append(_hit("reminder", "", row["text"],
                                     f"due {row['due']}"))

            rows = connection.execute(
                "SELECT id, title, body, updated FROM notes"
            ).fetchall()
            for row in rows:
                if match(row["title"]) or match(row["body"]):
                    hits.append(_hit(
                        "note", _day(row["updated"] or ""),
                        (row["title"] or "") or (row["body"] or "")[:90],
                        (row["body"] or "")[:140] if row["title"] else "",
                    ))

            rows = connection.execute(
                "SELECT content, category, timestamp FROM facts"
            ).fetchall()
            for row in rows:
                if match(row["content"]):
                    hits.append(_hit(
                        "fact", _day(row["timestamp"] or ""), row["content"],
                        f"category {row['category']}",
                    ))

            rows = connection.execute(
                "SELECT content, timestamp, role FROM conversations "
                "ORDER BY timestamp DESC LIMIT 800"
            ).fetchall()
            for row in rows:
                if match(row["content"]):
                    hits.append(_hit(
                        "history", _day(row["timestamp"] or ""),
                        (row["content"] or "")[:160], row["role"] or "",
                    ))
        finally:
            connection.close()
    except Exception as exc:
        logger.debug("Unified SQLite scan failed: %s", exc)
    return hits


def _scan_journal(config: Any, tokens: List[str]) -> List[Dict[str, str]]:
    try:
        hits: List[Dict[str, str]] = []
        for entry in _load_journal(config):
            text = str(entry.get("text", ""))
            response = str(entry.get("response", ""))
            if any(token in text.lower() or token in response.lower()
                   for token in tokens):
                hits.append(_hit(
                    "journal", str(entry.get("day", "")), text[:120],
                    response[:90],
                ))
        return hits[-5:][::-1]
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Unified journal scan failed: %s", exc)
        return []


def _scan_profile(brain: Any, tokens: List[str]) -> List[Dict[str, str]]:
    hits: List[Dict[str, str]] = []
    try:
        dutch = getattr(brain, "current_language", lambda: "en")() == "nl"
        preferences = brain.preferences
        name_line = (f"jouw naam is {preferences.user_name()}" if dutch
                     else f"your name is {preferences.user_name()}")
        for candidate in [name_line, *preferences.corrections()]:
            if any(token in candidate.lower() for token in tokens):
                hits.append(_hit("profile", "", candidate))
        for routine, entry in preferences.routines()[:10]:
            text = f"Bij \"{routine}\": {dict(entry).get('params', {})}" if dutch \
                else f"For {routine}: {dict(entry).get('params', {})}"
            if any(token in text.lower() for token in tokens):
                hits.append(_hit("routine", "", text))
    except Exception:
        pass
    return hits


def _scan_macros(brain: Any, tokens: List[str]) -> List[Dict[str, str]]:
    hits: List[Dict[str, str]] = []
    try:
        macros = getattr(brain, "macros", None)
        if macros is None:
            return hits
        listing = macros.list() if hasattr(macros, "list") else []
        if isinstance(listing, dict):
            items = listing.items()
        else:
            items = []
            for row in listing:
                items.append((
                    str(row.get("trigger", "")) if isinstance(row, dict) else str(row),
                    row,
                ))
        for trigger, _entry in items:
            text = f"macro \"{trigger}\""
            if any(token in trigger.lower() for token in tokens):
                hits.append(_hit("macro", "", text))
    except Exception:
        pass
    return hits


def search_all(brain: Any, query: str) -> List[Dict[str, str]]:
    """Search every local source for ``query``.

    Args:
        brain: The assistant (config, preferences, macros).
        query: What the user is looking for.

    Returns:
        Hit dicts, grouped by source; each source newest-first and capped.
    """
    tokens = _tokens(query)
    if not tokens:
        return []
    db_path = Path(brain.config.resolve(
        brain.config.get("database.path", "data/jarvis.db")
    ))
    grouped: List[Tuple[str, List[Dict[str, str]]]] = [
        ("journal", _scan_journal(brain.config, tokens)),
        ("what I remember", _scan_profile(brain, tokens)),
        ("macros", _scan_macros(brain, tokens)),
    ]
    by_source: Dict[str, List[Dict[str, str]]] = {}
    for hit in _scan_sqlite(db_path, tokens):
        by_source.setdefault(str(hit["source"]), []).append(hit)
    for source, rows in by_source.items():
        grouped.append((source, rows))

    ordered: List[Dict[str, str]] = []
    for _label, rows in grouped:
        rows_sorted = sorted(rows, key=lambda r: r.get("when", ""), reverse=True)
        ordered.extend(rows_sorted[:8])
    return ordered[:40]


_LABELS = {
    "todo": "taken", "reminder": "herinneringen", "note": "notities",
    "fact": "feiten", "journal": "dagboek", "history": "gesprek",
    "profile": "wat ik onthoud", "routine": "gewoontes", "macro": "macro's",
}


def render(hits: List[Dict[str, str]], language: str = "en") -> str:
    """Format hits into a grouped, spoken-friendly answer."""
    if not hits:
        return ""
    dutch = language == "nl"
    groups: Dict[str, List[Dict[str, str]]] = {}
    for hit in hits:
        groups.setdefault(hit["source"], []).append(hit)

    def header(source: str) -> str:
        if dutch:
            return f"[{_LABELS.get(source, 'gevonden')}]"
        return f"[{source}]"

    lines: List[str] = []
    for source in ("todo", "reminder", "note", "fact", "journal", "history",
                   "profile", "routine", "macro", "open tasks"):
        rows = groups.pop(source, None)
        if not rows:
            continue
        lines.append(header(source))
        for row in rows[:4]:
            when = f" ({row['when']})" if row.get("when") else ""
            text = (row.get("text") or "")[:150]
            lines.append(f"  •{when} {text}")
    for source, rows in groups.items():
        lines.append(header(source))
        for row in rows[:4]:
            when = f" ({row['when']})" if row.get("when") else ""
            lines.append(f"  •{when} {(row.get('text') or '')[:150]}")
    return "\n".join(lines)


def json_dump(hits: List[Dict[str, str]]) -> str:
    """JSON form for callers that want structured output."""
    return json.dumps(hits, ensure_ascii=False, indent=1)


__all__ = ["json_dump", "render", "search_all"]

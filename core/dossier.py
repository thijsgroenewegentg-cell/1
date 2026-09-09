# /core/dossier.py
"""Topic dossiers — "catch me up on X" from everything JARVIS knows.

Before a meeting or decision, ``brief me over de verbouwing`` assembles one
compact brief about a person, project or subject straight from his local
stores: the journal receipts (first/last mention, recent exchanges), stored
facts, notes and open promises (threads). Keyword matching only, offline.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Dict, List, Optional

from core import threads
from core.journal import _load as load_journal
from utils.logger import get_logger

logger = get_logger("core.dossier")

#: Words that carry no dossier meaning.
_STOP = {
    "the", "a", "an", "of", "to", "you", "your", "me", "my", "it", "is",
    "are", "was", "were", "and", "but", "for", "with", "over", "about",
    "de", "het", "een", "van", "dat", "wat", "mij", "mijn", "je", "jouw",
    "ik", "we", "en", "maar", "naar", "op", "in",
}


def _tokens(topic: str) -> List[str]:
    return [
        token for token in re.findall(r"[a-z0-9à-ÿ']+", (topic or "").lower())
        if len(token) > 1 and token not in _STOP
    ]


def _scan_sqlite(
    db_path: Any, tokens: List[str]
) -> Dict[str, List[Dict[str, str]]]:
    """Facts and notes that mention the topic."""
    out: Dict[str, List[Dict[str, str]]] = {"facts": [], "notes": []}
    try:
        connection = sqlite3.connect(str(db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            def match(hay: str) -> bool:
                hay = (hay or "").lower()
                return any(token in hay for token in tokens)

            for row in connection.execute(
                "SELECT content, timestamp FROM facts ORDER BY rowid"
            ).fetchall():
                if match(row["content"]):
                    out["facts"].append({
                        "text": str(row["content"])[:120],
                        "when": str(row["timestamp"] or "")[:10],
                    })
            for row in connection.execute(
                "SELECT title, updated FROM notes ORDER BY rowid"
            ).fetchall():
                if match(str(row["title"] or "")):
                    out["notes"].append({
                        "text": str(row["title"])[:90],
                        "when": str(row["updated"] or "")[:10],
                    })
        finally:
            connection.close()
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Dossier DB scan failed: %s", exc)
    return out


def dossier(config: Any, topic: str, language: str = "en",
            limit: int = 5) -> Optional[str]:
    """Build the "fill me in on X" brief.

    Args:
        config: Configuration.
        topic: The person/project/subject.
        language: ``"nl"`` or anything else (English).
        limit: How many recent mentions to quote.

    Returns:
        A formatted brief, or ``None`` when JARVIS truly has nothing on the
        topic (or the topic is empty filler).
    """
    dutch = language == "nl"
    clean = (topic or "").strip(" ?.!:,-")
    if not clean or clean.lower() in {"de", "het", "the", "a", "an", "je",
                                      "me", "mij"}:
        return None
    tokens = _tokens(clean)
    if not tokens:
        return None

    mentions: List[Dict[str, str]] = []
    for entry in load_journal(config):
        text = str(entry.get("text", ""))
        response = str(entry.get("response", ""))
        if any(token in text.lower() or token in response.lower()
               for token in tokens):
            mentions.append({
                "day": str(entry.get("day", ""))[:10],
                "text": text[:110],
                "response": response[:70],
            })
    mentions = mentions[-limit:]

    open_promises: List[Dict[str, Any]] = []
    for record in threads.list_threads(config, limit=50):
        hay = (str(record.get("request", "")) + " " +
               str(record.get("reply", ""))).lower()
        if any(token in hay for token in tokens):
            open_promises.append(record)

    sqlite_hits = _scan_sqlite(
        config.resolve(config.get("database.path", "data/jarvis.db")), tokens
    )

    total = len(mentions) + len(open_promises) + len(sqlite_hits["facts"]) \
        + len(sqlite_hits["notes"])
    if total == 0:
        return None

    lines: List[str] = []
    if dutch:
        lines.append(f"Dossier over \"{clean}\":")
    else:
        lines.append(f"File on \"{clean}\":")
    if mentions:
        first = mentions[0]["day"] or "?"
        last = mentions[-1]["day"] or "?"
        if dutch:
            lines.append(
                f"- dagboek: {len(mentions)} vermelding(en), eerste {first}, "
                f"laatste {last}:"
            )
        else:
            lines.append(
                f"- journal mentions ({len(mentions)}: first {first}, "
                f"last {last}):"
            )
        for entry in reversed(mentions[-3:]):
            lines.append(f"  • {entry['day']} — \"{entry['text']}\"")
    if sqlite_hits["facts"]:
        lines.append("- feiten:" if dutch else "- facts:")
        for fact in sqlite_hits["facts"][:4]:
            when = f" ({fact['when']})" if fact["when"] else ""
            lines.append(f"  •{when} {fact['text']}")
    if sqlite_hits["notes"]:
        lines.append("- notities:" if dutch else "- notes:")
        for note in sqlite_hits["notes"][:4]:
            when = f" ({note['when']})" if note["when"] else ""
            lines.append(f"  •{when} {note['text']}")
    if open_promises:
        lines.append("- open promise(s):" if not dutch else
                     "- openstaande belofte(n):")
        for record in open_promises[:3]:
            lines.append(f"  • \"{str(record.get('request', ''))[:80]}\"")
    if dutch:
        lines.append("Zeg 'wat staat er nog open' voor de volledige lijst of "
                     "'zoek overal naar X' voor elk detail.")
    else:
        lines.append("Say 'what's still open' for the full list, or 'search "
                     "everywhere for X' for every detail.")
    return "\n".join(lines)


__all__ = ["dossier"]

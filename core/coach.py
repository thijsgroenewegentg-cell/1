# /core/coach.py
"""Improvement coach — JARVIS reads his own records and suggests habits.

"what should we improve?" turns his stored history into concrete coaching
lines: repeated failure signatures (same module, same error text), stale
open threads, corrections already in force, and simple usage pointers.
Everything is read from local files/DBs — no model, no network.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional

from core import failures, threads
from utils.logger import get_logger

logger = get_logger("core.coach")


def _stale_days(config: Any, record: Dict[str, Any]) -> Optional[int]:
    """Whole days since an open thread was noted (None when unknown)."""
    raw = str(record.get("ts", "")) or str(record.get("day", ""))
    try:
        moment = datetime.fromisoformat(raw)
    except Exception:
        return None
    return max(0, (datetime.now() - moment).days)


def _failure_signatures(config: Any, limit: int = 60) -> List[Dict[str, Any]]:
    """Group the recent failure log into (module, error) signatures."""
    counts: Counter = Counter()
    samples: Dict[Any, str] = {}
    for entry in failures.recent(config, limit=limit):
        module = str(entry.get("module", "") or "unknown")
        error = str(entry.get("error", "") or "unknown")
        error = re.sub(r"\s+", " ", error)[:80]
        key = (module, error)
        counts[key] += 1
        samples.setdefault(key, str(entry.get("text", ""))[:70])
    return [{
        "module": module, "error": error, "times": times,
        "request": samples[(module, error)],
    } for (module, error), times in counts.most_common(4)]


def digest(brain: Any, language: str = "en") -> str:
    """Build the coaching briefing from JARVIS's own stored records.

    Args:
        brain: The assistant (config, preferences).
        language: ``"nl"`` or anything else (English).

    Returns:
        A multi-line briefing with concrete suggestions, or an honest
        "nothing to improve" note when the records are clean.
    """
    config = brain.config
    dutch = language == "nl"
    lines: List[str] = []

    signatures = _failure_signatures(config)
    if signatures:
        worst = signatures[0]
        if dutch:
            lines.append(f"Meest herhaalde fout: {worst['times']}x in "
                         f"{worst['module']} — {worst['error']}.")
        else:
            lines.append(f"Most repeated failure: {worst['times']}x in "
                         f"{worst['module']} — {worst['error']}.")
        if worst["times"] >= 2:
            lines.append(
                "Suggestie: geef me een concreet voorbeeld ('doe het zo: …') "
                "of corrigeer me — ik maak er een blijvende regel van."
                if dutch else
                "Suggestion: give me one concrete example ('do it like this: "
                "…') or correct me — I'll turn it into a standing rule."
            )

    open_threads = threads.list_threads(config)
    stale = [(record, days) for record in open_threads
             if (days := _stale_days(config, record)) is not None and days >= 1]
    if stale:
        oldest = max(stale, key=lambda pair: pair[1])
        request = str(oldest[0].get("request", ""))[:60]
        if dutch:
            lines.append(
                f"Een openstaande zaak ligt er al {oldest[1]} dag(en): "
                f"\"{request}\"."
            )
            lines.append("Zeg 'is geregeld' om hem af te vinken of vraag me "
                         "hem op te volgen.")
        else:
            lines.append(
                f"One open thread has been dangling for {oldest[1]} day(s): "
                f"\"{request}\"."
            )
            lines.append("Say 'that's sorted' to close it, or ask me to "
                         "follow up on it.")

    corrections = brain.preferences.corrections(limit=20)
    if corrections:
        latest = corrections[0]
        if dutch:
            lines.append(f"Staande correctie van kracht: \"{latest}\".")
        else:
            lines.append(f"Standing correction in force: \"{latest}\".")

    if not lines:
        if dutch:
            return (
                "Goed nieuws: uit mijn logs komen geen herhaalde fouten, "
                "geen verwaarloosde zaken en geen correcties naar voren. "
                "Blijf me uitdagen — dan vind ik vanzelf iets om beter te "
                "doen."
            )
        return (
            "Good news: no repeated failures, neglected threads or "
            "corrections in my records. Keep challenging me and I'll "
            "find something to improve on my own."
        )

    if dutch:
        lines.append("Coach-modus: zeg 'wat kunnen we verbeteren' om dit "
                     "overzicht op te vragen.")
    else:
        lines.append("Coach mode: ask 'what should we improve?' any time to "
                     "get this digest.")
    return "\n".join(lines)


__all__ = ["digest"]

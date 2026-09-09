# /core/recap.py
"""End-of-day recap — what *you* got done today.

"recap my day" / "wat heb ik vandaag gedaan" tallies today straight from the
local stores: turns in the journal, todos completed, reminders that fired,
notes written, facts stored and open threads started — plus what is still
dangling so the evening ends with a clear next step. No model, no network.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core import threads
from core.journal import _load as load_journal
from utils.logger import get_logger

logger = get_logger("core.recap")


def _day_bounds(now: Optional[datetime] = None) -> tuple[str, str]:
    moment = now or datetime.now()
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def recap(config: Any, language: str = "en", now: Optional[datetime] = None
          ) -> str:
    """Build the day recap.

    Args:
        config: Configuration.
        language: ``"nl"`` or anything else (English).
        now: Reference moment (defaults to the current time).

    Returns:
        A formatted recap. Always returns something — an empty day is an
        honest "nothing happened" note.
    """
    dutch = language == "nl"
    moment = now or datetime.now()
    day = moment.strftime("%Y-%m-%d")
    start, end = _day_bounds(moment)

    journal_turns = [
        entry for entry in load_journal(config)
        if str(entry.get("day", "")) == day
    ]
    started_today = [
        record for record in threads.list_threads(config, limit=50)
        if str(record.get("day", "")) == day
    ]

    counts: Dict[str, int] = {
        "todos_done": 0, "reminders_fired": 0, "notes": 0, "facts": 0,
    }
    completed: List[str] = []
    notes: List[str] = []
    db_path = config.resolve(config.get("database.path", "data/jarvis.db"))
    try:
        connection = sqlite3.connect(str(db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            present = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "todos" in present:
                for row in connection.execute(
                    "SELECT task FROM todos WHERE done = 1 AND completed >= ? "
                    "AND completed < ? ORDER BY completed", (start, end),
                ).fetchall():
                    counts["todos_done"] += 1
                    completed.append(str(row["task"])[:80])
            if "reminders" in present:
                counts["reminders_fired"] = connection.execute(
                    "SELECT COUNT(*) FROM reminders WHERE fired = 1 "
                    "AND due >= ? AND due < ?", (start, end),
                ).fetchone()[0]
            if "notes" in present:
                for row in connection.execute(
                    "SELECT title FROM notes WHERE created >= ? "
                    "AND created < ? ORDER BY created", (start, end),
                ).fetchall():
                    counts["notes"] += 1
                    notes.append(str(row["title"] or "")[:80])
            if "facts" in present:
                counts["facts"] = connection.execute(
                    "SELECT COUNT(*) FROM facts WHERE timestamp >= ? "
                    "AND timestamp < ?", (start, end),
                ).fetchone()[0]
        finally:
            connection.close()
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Recap DB scan failed: %s", exc)

    dangling = threads.list_threads(config, limit=3)
    overdue = _overdue_reminders(config, moment)

    lines: List[str] = []
    if dutch:
        weekdays = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag",
                    "zaterdag", "zondag"]
        months = ["januari", "februari", "maart", "april", "mei", "juni",
                  "juli", "augustus", "september", "oktober", "november",
                  "december"]
        lines.append(f"Jouw dag, {weekdays[moment.weekday()]} "
                     f"{moment.day} {months[moment.month - 1]} ({day}):")
    else:
        lines.append(f"Your day, {moment:%A %d %B} ({day}):")
    lines.append(f"• {len(journal_turns)} beurt(en) met mij" if dutch
                 else f"• {len(journal_turns)} turn(s) with me")
    if completed:
        lines.append(f"• {counts['todos_done']} taak/taken afgerond:" if dutch
                     else f"• {counts['todos_done']} todo(s) completed:")
        for task in completed[:4]:
            lines.append(f"   – {task}")
    elif counts["todos_done"]:
        lines.append(f"• {counts['todos_done']} taak/taken afgerond" if dutch
                     else f"• {counts['todos_done']} todo(s) completed")
    lines.append(
        f"• {counts['reminders_fired']} herinnering(en) afgegaan, "
        f"{counts['notes']} notitie(s), {counts['facts']} feit(en) opgeslagen"
        if dutch else
        f"• {counts['reminders_fired']} reminder(s) fired, "
        f"{counts['notes']} note(s), {counts['facts']} fact(s) stored"
    )
    if notes:
        for title in notes[:3]:
            lines.append(f"   – {title}")
    if started_today:
        lines.append(
            f"• {len(started_today)} openstaande zaak/acties vandaag geopend"
            if dutch else
            f"• {len(started_today)} open thread(s) started today"
        )
    if dangling or overdue:
        if dutch:
            lines.append("Nog openstaand:")
        else:
            lines.append("Still open:")
        for record in dangling:
            lines.append(f"   – \"{str(record.get('request', ''))[:70]}\"")
        if overdue and len(lines) < 9:
            lines.append(
                "   – " + (f"{len(overdue)} herinnering(en) over tijd"
                           if dutch else
                           f"{len(overdue)} reminder(s) past due")
            )
        if dutch:
            lines.append("Zeg 'wat staat er nog open' of 'is geregeld' om "
                         "af te vinken.")
        else:
            lines.append("Say 'what's still open' or 'that's sorted' to "
                         "close them.")
    else:
        lines.append(
            "Niets meer open — dag kan dicht."
            if dutch else
            "Nothing dangling — the day can close."
        )
    return "\n".join(lines)


def _overdue_reminders(config: Any, moment: datetime) -> List[Dict[str, Any]]:
    """Unfired reminders whose due moment has passed."""
    try:
        db_path = config.resolve(config.get("database.path", "data/jarvis.db"))
        connection = sqlite3.connect(str(db_path), timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT text, due FROM reminders WHERE fired = 0 AND due <= ? "
                "ORDER BY due", (moment.isoformat(timespec="seconds"),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()
    except Exception:  # pragma: no cover
        return []


__all__ = ["recap"]

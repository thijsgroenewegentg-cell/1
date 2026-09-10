# /core/presence.py
"""What JARVIS already knows — surfaced without being asked.

The journal, open threads, last Blender scene and learned habits already
exist. This module turns them into one short block the model (and the
greeting) can use on the next turn, so "what were we doing" does not have
to be asked first.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List

from core import journal, threads


def spoken(config: Any, *, dutch: bool = False, blender_last: str = "") -> str:
    """One sentence for a greeting. Empty when there is nothing to mention."""
    bits: List[str] = []
    yesterday = journal.day_before(datetime.now().strftime("%Y-%m-%d"))
    recap = journal.brief_line(config, yesterday, dutch=dutch)
    if recap:
        bits.append(recap)
    open_threads = threads.list_threads(config, limit=1)
    if open_threads:
        request = str(open_threads[0].get("request") or "").strip()
        if request:
            if dutch:
                bits.append(f"Nog open: {request}.")
            else:
                bits.append(f"Still open: {request}.")
    last = (blender_last or "").strip()
    if last:
        name = last.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if dutch:
            bits.append(f"Laatste Blender-scene: {name}.")
        else:
            bits.append(f"Last Blender scene: {name}.")
    return " ".join(bits[:2])


def block(
    config: Any,
    *,
    dutch: bool = False,
    blender_last: str = "",
    habits: str = "",
) -> str:
    """A prompt-ready briefing of what is already on file.

    Args:
        config: Locates the journal and threads files.
        dutch: Write the labels in Dutch.
        blender_last: Path of the most recent .blend, if any.
        habits: Learned-habits summary from :class:`Preferences`.

    Returns:
        A short block, or an empty string when nothing is on file.
    """
    lines: List[str] = []
    heading = (
        "Already on file (use this without being asked when it is relevant):"
        if not dutch
        else "Al bekend (gebruik dit uit jezelf wanneer het relevant is):"
    )
    yesterday = journal.day_before(datetime.now().strftime("%Y-%m-%d"))
    recap = journal.brief_line(config, yesterday, dutch=dutch)
    if recap:
        lines.append(f"- {recap}")
    today = datetime.now().strftime("%Y-%m-%d")
    today_line = journal.brief_line(config, today, dutch=dutch)
    if today_line:
        # brief_line says "Yesterday" even for today — rephrase.
        count = len(journal.events_on(config, today))
        if count:
            if dutch:
                lines.append(f"- Vandaag al {count} verzoek(en) in het journaal.")
            else:
                lines.append(f"- Today so far: {count} request(s) in the journal.")
    for record in threads.list_threads(config, limit=3):
        request = str(record.get("request") or "").strip()
        if request:
            if dutch:
                lines.append(f"- Open draad: {request}")
            else:
                lines.append(f"- Open thread: {request}")
    last = (blender_last or "").strip()
    if last:
        if dutch:
            lines.append(f"- Laatste Blender-scene: {last}")
        else:
            lines.append(f"- Last Blender scene: {last}")
    habit_lines = [line.strip() for line in (habits or "").splitlines() if line.strip()]
    for line in habit_lines[:3]:
        lines.append(line if line.startswith("-") else f"- {line}")
    if not lines:
        return ""
    return heading + "\n" + "\n".join(lines)


__all__ = ["block", "spoken"]

# /core/proactive.py
"""Time-aware check-ins, topic watches and hardware alerts.

All of it is local and model-free. The productivity scheduler polls
:func:`due_messages` on every tick; the web console asks
:func:`briefing_due` once a day. Quiet hours are enforced by the caller.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.proactive")

_DEFAULT_HOURS = (9, 14, 18)


def _path(config: Any) -> Path:
    """JSON file holding watches and 'already did this today' flags."""
    try:
        return config.resolve("data/proactive.json")
    except Exception:
        return Path("data/proactive.json")


def load_state(config: Any) -> Dict[str, Any]:
    """Read the proactive state, or an empty document."""
    path = _path(config)
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("Could not read proactive state: %s", exc)
    return {"watches": [], "hw": {}}


def save_state(config: Any, state: Dict[str, Any]) -> None:
    """Persist the proactive state. Never raises."""
    path = _path(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not write proactive state: %s", exc)


def watches(config: Any) -> List[str]:
    """Topics currently being watched, oldest first."""
    items = load_state(config).get("watches") or []
    topics: List[str] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            topics.append(item.strip())
        elif isinstance(item, dict) and str(item.get("topic") or "").strip():
            topics.append(str(item["topic"]).strip())
    return topics


def add_watch(config: Any, topic: str) -> bool:
    """Start watching ``topic``. Returns False when it was already there."""
    topic = " ".join((topic or "").split()).strip().lower()
    if len(topic) < 2 or len(topic) > 80:
        return False
    state = load_state(config)
    current = watches(config)
    if topic in {item.lower() for item in current}:
        return False
    rows = list(state.get("watches") or [])
    rows.append({"topic": topic, "seen": []})
    state["watches"] = rows
    save_state(config, state)
    return True


def remove_watch(config: Any, topic: str) -> bool:
    """Stop watching ``topic``. Returns False when it was not watched."""
    needle = " ".join((topic or "").split()).strip().lower()
    if not needle:
        return False
    state = load_state(config)
    rows = list(state.get("watches") or [])
    kept = []
    removed = False
    for item in rows:
        name = item if isinstance(item, str) else str((item or {}).get("topic") or "")
        if name.strip().lower() == needle:
            removed = True
            continue
        kept.append(item)
    if not removed:
        return False
    state["watches"] = kept
    save_state(config, state)
    return True


def briefing_due(config: Any, today: str = "") -> bool:
    """True when today's morning briefing has not been delivered yet."""
    day = today or datetime.now().strftime("%Y-%m-%d")
    return str(load_state(config).get("briefing_day") or "") != day


def mark_briefing_delivered(config: Any, today: str = "") -> None:
    """Remember that today's briefing went out."""
    state = load_state(config)
    state["briefing_day"] = today or datetime.now().strftime("%Y-%m-%d")
    save_state(config, state)


def check_in_hours(config: Any) -> List[int]:
    """Hours (0-23) when a check-in may fire."""
    raw = config.get("assistant.check_in_hours", list(_DEFAULT_HOURS))
    hours: List[int] = []
    if isinstance(raw, str):
        raw = [bit.strip() for bit in raw.split(",") if bit.strip()]
    for item in raw or _DEFAULT_HOURS:
        try:
            hour = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23 and hour not in hours:
            hours.append(hour)
    return hours or list(_DEFAULT_HOURS)


def check_in_due(config: Any, now: Optional[datetime] = None) -> Optional[int]:
    """Return the current check-in hour if it has not fired today, else None."""
    if not config.get("assistant.check_ins", True):
        return None
    moment = now or datetime.now()
    hour = moment.hour
    if hour not in check_in_hours(config):
        return None
    state = load_state(config)
    day = moment.strftime("%Y-%m-%d")
    if str(state.get("check_in_day") or "") == day and int(state.get("check_in_slot") or -1) == hour:
        return None
    return hour


def mark_check_in(config: Any, hour: int, now: Optional[datetime] = None) -> None:
    """Remember that this hour's check-in went out."""
    moment = now or datetime.now()
    state = load_state(config)
    state["check_in_day"] = moment.strftime("%Y-%m-%d")
    state["check_in_slot"] = int(hour)
    save_state(config, state)


def check_in_line(hour: int, *, tasks: int = 0, dutch: bool = False) -> str:
    """One short, time-of-day check-in. Instant, no model."""
    if hour < 12:
        part = "Goedemorgen" if dutch else "Good morning"
    elif hour < 18:
        part = "Goedemiddag" if dutch else "Good afternoon"
    else:
        part = "Goedenavond" if dutch else "Good evening"
    if tasks <= 0:
        extra = "Niets open op de lijst." if dutch else "Nothing open on the list."
    elif dutch:
        extra = f"{tasks} open taak{'en' if tasks != 1 else ''}."
    else:
        extra = f"{tasks} open task{'s' if tasks != 1 else ''}."
    return f"{part} — {extra}"


def watch_due(config: Any, now: Optional[datetime] = None) -> bool:
    """True once a day after 08:30, when there is at least one watch."""
    if not watches(config):
        return False
    moment = now or datetime.now()
    if moment.hour < 8 or (moment.hour == 8 and moment.minute < 30):
        return False
    day = moment.strftime("%Y-%m-%d")
    return str(load_state(config).get("watch_day") or "") != day


def mark_watch_run(config: Any, now: Optional[datetime] = None) -> None:
    """Remember that today's topic-watch pass ran."""
    state = load_state(config)
    state["watch_day"] = (now or datetime.now()).strftime("%Y-%m-%d")
    save_state(config, state)


def remember_headlines(config: Any, topic: str, titles: List[str]) -> List[str]:
    """Return titles not seen before for ``topic``, and store them.

    Args:
        config: Configuration (locates the state file).
        topic: The watch keyword.
        titles: Fresh headlines.

    Returns:
        Titles that are new since the last pass.
    """
    needle = topic.strip().lower()
    state = load_state(config)
    rows = list(state.get("watches") or [])
    fresh: List[str] = []
    updated = []
    for item in rows:
        if isinstance(item, str):
            item = {"topic": item, "seen": []}
        name = str(item.get("topic") or "").strip().lower()
        seen = [str(title).strip() for title in (item.get("seen") or []) if str(title).strip()]
        if name == needle:
            for title in titles:
                text = str(title or "").strip()
                if text and text not in seen:
                    fresh.append(text)
                    seen.append(text)
            item = {"topic": name, "seen": seen[-20:]}
        updated.append(item)
    state["watches"] = updated
    save_state(config, state)
    return fresh


def read_hardware() -> Dict[str, float]:
    """CPU / RAM / temperature snapshot. Empty when psutil is missing."""
    try:
        import psutil
    except Exception:
        return {}
    reading: Dict[str, float] = {
        "cpu": float(psutil.cpu_percent(interval=None) or 0.0),
        "ram": float(psutil.virtual_memory().percent or 0.0),
        "temp": 0.0,
    }
    try:
        sensors = psutil.sensors_temperatures() or {}
        for entries in sensors.values():
            if entries and getattr(entries[0], "current", None):
                reading["temp"] = float(entries[0].current)
                break
    except Exception:
        pass
    return reading


def hardware_messages(config: Any, reading: Optional[Dict[str, float]] = None) -> List[str]:
    """Voice-ready alerts for readings that just crossed a threshold.

    Hysteresis: a hot signal stays silent until it has dropped 8 points
    below the threshold, so a machine sitting at 91% does not nag every tick.
    """
    if not config.get("assistant.hardware_alerts", True):
        return []
    snapshot = reading if reading is not None else read_hardware()
    if not snapshot:
        return []
    cpu_lim = float(config.get("assistant.cpu_alert", 90) or 90)
    ram_lim = float(config.get("assistant.ram_alert", 90) or 90)
    state = load_state(config)
    flags = dict(state.get("hw") or {})
    messages: List[str] = []

    def _cross(key: str, value: float, limit: float, label: str) -> None:
        if limit <= 0:
            return
        hot = bool(flags.get(key))
        if value >= limit and not hot:
            flags[key] = True
            messages.append(f"{label} at {value:.0f}% — over the {limit:.0f}% mark.")
        elif value <= max(0.0, limit - 8) and hot:
            flags[key] = False

    _cross("cpu", float(snapshot.get("cpu") or 0.0), cpu_lim, "CPU")
    _cross("ram", float(snapshot.get("ram") or 0.0), ram_lim, "RAM")
    state["hw"] = flags
    save_state(config, state)
    return messages


__all__ = [
    "add_watch",
    "briefing_due",
    "check_in_due",
    "check_in_hours",
    "check_in_line",
    "hardware_messages",
    "load_state",
    "mark_briefing_delivered",
    "mark_check_in",
    "mark_watch_run",
    "read_hardware",
    "remember_headlines",
    "remove_watch",
    "save_state",
    "watch_due",
    "watches",
]

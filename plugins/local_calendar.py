"""Private local calendar plugin using a small standards-based ICS file.

It needs no Google/Microsoft account and stores events under the user's home
folder. A future sync plugin can use the same events without changing MARK's
conversation tools.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


PLUGIN = {
    "name": "local_calendar",
    "description": (
        "Manage a private local calendar without cloud credentials. Add, list, "
        "find and remove appointments or reminders. Use this for calendar requests "
        "when the user has not explicitly asked for Google or Microsoft Calendar."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "add | list | today | find | remove",
            },
            "title": {"type": "STRING", "description": "Event title"},
            "date": {"type": "STRING", "description": "Date as YYYY-MM-DD"},
            "time": {"type": "STRING", "description": "Local start time as HH:MM"},
            "duration": {"type": "INTEGER", "description": "Duration in minutes (default: 60)"},
            "location": {"type": "STRING", "description": "Optional location"},
            "query": {"type": "STRING", "description": "Text to find or remove"},
            "event_id": {"type": "STRING", "description": "UID returned by a previous calendar result"},
        },
        "required": ["action"],
    },
}


_CALENDAR_ENV = "MARK_CALENDAR_FILE"


def _calendar_config() -> dict:
    try:
        from memory.config_manager import get_plugin_config
        value = get_plugin_config("local_calendar")
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _calendar_path() -> Path:
    raw = os.environ.get(_CALENDAR_ENV, "").strip() or str(
        _calendar_config().get("file_path", "")
    ).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "Documents" / "MARK" / "calendar.ics").resolve()


def _escape(value: str) -> str:
    return (str(value or "").replace("\\", "\\\\")
            .replace(";", "\\;").replace(",", "\\,")
            .replace("\n", "\\n"))


def _unescape(value: str) -> str:
    return (str(value or "").replace("\\n", "\n")
            .replace("\\,", ",").replace("\\;", ";")
            .replace("\\\\", "\\"))


def _parse_dt(value: str) -> datetime | None:
    raw = str(value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return None


def _ics_dt(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%Y%m%dT%H%M%S")
    except ValueError:
        return None


def _read_events() -> list[dict]:
    path = _calendar_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

    events: list[dict] = []
    current: dict | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current and current.get("uid") and current.get("start"):
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.split(";", 1)[0].upper()
        if key == "UID":
            current["uid"] = value.strip()
        elif key == "SUMMARY":
            current["title"] = _unescape(value)
        elif key == "LOCATION":
            current["location"] = _unescape(value)
        elif key == "DTSTART":
            current["start"] = _ics_dt(value)
        elif key == "DTEND":
            current["end"] = _ics_dt(value)
    return events


def _write_events(events: list[dict]) -> None:
    path = _calendar_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//MARK//Local Calendar//EN"]
    for event in sorted(events, key=lambda e: e["start"]):
        start = event["start"]
        end = event["end"]
        rows.extend([
            "BEGIN:VEVENT",
            f"UID:{event['uid']}",
            f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%S')}",
            f"DTSTART:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{end.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{_escape(event.get('title', ''))}",
        ])
        if event.get("location"):
            rows.append(f"LOCATION:{_escape(event['location'])}")
        rows.append("END:VEVENT")
    rows.append("END:VCALENDAR")
    content = "\r\n".join(rows) + "\r\n"
    fd, temp_name = tempfile.mkstemp(prefix="mark-calendar-", suffix=".ics", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except Exception:
            pass


def _format_event(event: dict) -> str:
    start = event["start"].strftime("%Y-%m-%d %H:%M")
    location = f" — {event['location']}" if event.get("location") else ""
    return f"{start} · {event.get('title', '(untitled)')}{location} [{event['uid'][:8]}]"


def _select(events: list[dict], query: str) -> list[dict]:
    q = str(query or "").strip().lower()
    if not q:
        return events
    return [e for e in events if q in e.get("title", "").lower()
            or q in e.get("location", "").lower()
            or q in e.get("uid", "").lower()]


def _test_calendar(values: dict) -> tuple[bool, str]:
    raw = str(values.get("file_path", "")).strip()
    path = Path(raw).expanduser().resolve() if raw else _calendar_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not path.is_file():
            return False, f"Calendar path is not a file: {path}"
        return True, f"Local calendar is ready: {path}"
    except Exception as exc:
        return False, f"Calendar path is not writable: {exc}"


PLUGIN_SETTINGS = {
    "namespace": "local_calendar",
    "title": "CALENDAR — LOCAL ICS",
    "note": (
        "Events stay in a local ICS file. A configured path is used unless "
        "MARK_CALENDAR_FILE is set in the environment."
    ),
    "fields": [
        {"key": "file_path", "label": "Calendar file", "placeholder": "~/Documents/MARK/calendar.ics"},
        {"key": "default_duration", "label": "Default duration (minutes)", "default": 60},
    ],
    "action": {"label": "CHECK CALENDAR FILE", "run": _test_calendar},
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "list")).strip().lower()
    events = _read_events()
    now = datetime.now()

    if action == "add":
        title = str(params.get("title", "")).strip()
        date = str(params.get("date", "")).strip()
        clock = str(params.get("time", "09:00")).strip()
        start = _parse_dt(f"{date} {clock}")
        if not title or start is None:
            return "To add a calendar event I need a title, date YYYY-MM-DD and time HH:MM."
        configured_duration = _calendar_config().get("default_duration", 60)
        try:
            minutes = max(1, min(24 * 60, int(params.get("duration", configured_duration))))
        except (TypeError, ValueError):
            minutes = 60
        event_id = "mark-" + hashlib.sha1(
            f"{title}|{start.isoformat()}|{now.timestamp()}".encode()
        ).hexdigest()[:16]
        event = {
            "uid": event_id,
            "title": title,
            "start": start,
            "end": start + timedelta(minutes=minutes),
            "location": str(params.get("location", "")).strip(),
        }
        events.append(event)
        _write_events(events)
        result = f"Added: {_format_event(event)}. Calendar file: {_calendar_path()}"
    elif action == "today":
        chosen = [e for e in events if e["start"].date() == now.date()]
        result = "Today's calendar is empty." if not chosen else "Today:\n" + "\n".join(_format_event(e) for e in chosen)
    elif action == "find":
        chosen = _select(events, params.get("query") or params.get("title"))
        result = "No matching calendar events." if not chosen else "Matches:\n" + "\n".join(_format_event(e) for e in chosen[:20])
    elif action == "remove":
        query = params.get("event_id") or params.get("query") or params.get("title")
        chosen = _select(events, query)
        if not chosen:
            result = "No matching calendar event was found."
        else:
            target = chosen[0]
            events.remove(target)
            _write_events(events)
            result = f"Removed: {_format_event(target)}"
    elif action == "list":
        chosen = [e for e in events if e["start"] >= now - timedelta(minutes=1)]
        result = "The calendar is empty." if not chosen else "Upcoming:\n" + "\n".join(_format_event(e) for e in chosen[:20])
    else:
        return "Unknown calendar action. Use add, list, today, find or remove."

    if player:
        try:
            player.write_log(f"[Calendar] {action}")
        except Exception:
            pass
    return result

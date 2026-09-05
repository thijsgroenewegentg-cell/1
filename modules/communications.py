# /modules/communications.py
"""Email (IMAP/SMTP) and calendar (.ics) — free, standards-based, no vendor APIs.

Email uses Python's stdlib ``imaplib``/``smtplib``, so any provider works
(Gmail with an app password, Outlook, Fastmail, a self-hosted box…). The
password is *never* stored in the config file — it is read from the environment
variable named by ``email.password_env``.

Calendar reads iCalendar (.ics) files from disk and from "secret address"
export URLs (Google Calendar, Outlook, Nextcloud all publish these for free),
plus a local .ics you can write events into. The VEVENT parser is hand-rolled,
so no extra dependency is required.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import os
import re
import smtplib
import ssl
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import ensure_dir, parse_when, run_blocking, truncate

ICS_DATE = "%Y%m%d"
ICS_DATETIME = "%Y%m%dT%H%M%S"


@dataclass
class CalendarEvent:
    """A single calendar entry parsed from an iCalendar VEVENT."""

    summary: str
    start: datetime
    end: Optional[datetime] = None
    location: str = ""
    description: str = ""
    all_day: bool = False
    source: str = ""
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)

    def describe(self) -> str:
        """Human-readable one-liner for this event."""
        if self.all_day:
            when = self.start.strftime("%a %d %b (all day)")
        else:
            when = self.start.strftime("%a %d %b %H:%M")
            if self.end:
                when += self.end.strftime("–%H:%M")
        place = f" @ {self.location}" if self.location else ""
        return f"{when} — {self.summary}{place}"

    def to_dict(self) -> Dict[str, Any]:
        """Serialisable representation."""
        return {
            "summary": self.summary,
            "start": self.start.isoformat(timespec="minutes"),
            "end": self.end.isoformat(timespec="minutes") if self.end else "",
            "location": self.location,
            "all_day": self.all_day,
            "source": self.source,
            "uid": self.uid,
        }


def _unfold(raw: str) -> List[str]:
    """Undo iCalendar line folding (continuation lines start with space/tab)."""
    lines: List[str] = []
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape(value: str) -> str:
    """Decode iCalendar text escapes."""
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _parse_ics_datetime(value: str, params: str) -> Tuple[Optional[datetime], bool]:
    """Parse a DTSTART/DTEND value into a naive local datetime.

    Args:
        value: The property value, e.g. ``20260105T140000Z``.
        params: The parameter part of the property, e.g. ``;VALUE=DATE``.

    Returns:
        ``(datetime or None, all_day)``.
    """
    value = value.strip()
    all_day = "VALUE=DATE" in params.upper() or (len(value) == 8 and "T" not in value)
    try:
        if all_day:
            return datetime.strptime(value[:8], ICS_DATE), True
        if value.endswith("Z"):
            parsed = datetime.strptime(value[:15], ICS_DATETIME)
            offset = datetime.now() - datetime.utcnow()
            return parsed + timedelta(seconds=round(offset.total_seconds() / 60) * 60), False
        return datetime.strptime(value[:15], ICS_DATETIME), False
    except Exception:
        return None, all_day


def parse_ics(raw: str, source: str = "") -> List[CalendarEvent]:
    """Parse iCalendar text into events (VEVENT only, recurrence expanded daily/weekly).

    Args:
        raw: The .ics file contents.
        source: Label recorded on each event (file name or URL).

    Returns:
        A list of :class:`CalendarEvent`, possibly empty.
    """
    events: List[CalendarEvent] = []
    current: Optional[Dict[str, Any]] = None
    for line in _unfold(raw):
        stripped = line.strip()
        if stripped == "BEGIN:VEVENT":
            current = {"all_day": False}
            continue
        if stripped == "END:VEVENT":
            if current and current.get("start") and current.get("summary"):
                event = CalendarEvent(
                    summary=current["summary"],
                    start=current["start"],
                    end=current.get("end"),
                    location=current.get("location", ""),
                    description=current.get("description", ""),
                    all_day=bool(current.get("all_day")),
                    source=source,
                    uid=current.get("uid") or uuid.uuid4().hex,
                )
                events.append(event)
                rrule = str(current.get("rrule", "")).upper()
                if "FREQ=" in rrule:
                    events.extend(_expand_recurrence(event, rrule))
            current = None
            continue
        if current is None or ":" not in stripped:
            continue

        name, _, value = stripped.partition(":")
        params = ""
        if ";" in name:
            name, _, params = name.partition(";")
        key = name.upper()
        if key == "SUMMARY":
            current["summary"] = _unescape(value)
        elif key == "LOCATION":
            current["location"] = _unescape(value)
        elif key == "DESCRIPTION":
            current["description"] = _unescape(value)
        elif key == "UID":
            current["uid"] = value.strip()
        elif key == "RRULE":
            current["rrule"] = value.strip()
        elif key == "DTSTART":
            parsed, all_day = _parse_ics_datetime(value, params)
            if parsed:
                current["start"] = parsed
                current["all_day"] = all_day
        elif key == "DTEND":
            parsed, _ = _parse_ics_datetime(value, params)
            if parsed:
                current["end"] = parsed
    return events


def _expand_recurrence(event: CalendarEvent, rrule: str, horizon_days: int = 60
                       ) -> List[CalendarEvent]:
    """Expand simple DAILY/WEEKLY/MONTHLY rules within a short horizon."""
    match = re.search(r"FREQ=([A-Z]+)", rrule)
    if not match:
        return []
    freq = match.group(1)
    interval_match = re.search(r"INTERVAL=(\d+)", rrule)
    interval = int(interval_match.group(1)) if interval_match else 1
    step = {"DAILY": timedelta(days=interval), "WEEKLY": timedelta(weeks=interval),
            "MONTHLY": timedelta(days=30 * interval)}.get(freq)
    if step is None:
        return []

    until: Optional[datetime] = None
    until_match = re.search(r"UNTIL=(\d{8})", rrule)
    if until_match:
        try:
            until = datetime.strptime(until_match.group(1), ICS_DATE)
        except Exception:
            until = None

    horizon = datetime.now() + timedelta(days=horizon_days)
    duration = (event.end - event.start) if event.end else None
    occurrences: List[CalendarEvent] = []
    cursor = event.start + step
    while cursor <= horizon and len(occurrences) < 120:
        if until and cursor > until:
            break
        occurrences.append(
            CalendarEvent(
                summary=event.summary,
                start=cursor,
                end=cursor + duration if duration else None,
                location=event.location,
                description=event.description,
                all_day=event.all_day,
                source=event.source,
                uid=f"{event.uid}-{cursor:%Y%m%d}",
            )
        )
        cursor += step
    return occurrences


class Communications(BaseModule):
    """Read and send mail over IMAP/SMTP and read calendars from .ics sources."""

    name = "communications"
    description = (
        "Email and calendar: check the inbox over IMAP, summarise unread mail, send mail "
        "over SMTP (only when explicitly enabled), and read the user's calendar from .ics "
        "files or secret calendar URLs."
    )
    intent_examples = [
        "check my email",
        "any unread mail from my boss",
        "what's on my calendar today",
        "when is my next meeting",
        "send an email to alice@example.com saying I'll be late",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Load mail and calendar settings."""
        super().__init__(config, llm=llm, security=security)
        mail = config.section("email")
        self.mail_enabled: bool = bool(mail.get("enabled", False))
        self.imap_host: str = str(mail.get("imap_host", ""))
        self.imap_port: int = int(mail.get("imap_port", 993))
        self.smtp_host: str = str(mail.get("smtp_host", ""))
        self.smtp_port: int = int(mail.get("smtp_port", 587))
        self.user: str = str(mail.get("user", ""))
        self.password_env: str = str(mail.get("password_env", "JARVIS_EMAIL_PASSWORD"))
        self.mailbox: str = str(mail.get("mailbox", "INBOX"))
        self.fetch_limit: int = int(mail.get("fetch_limit", 10))
        self.allow_send: bool = bool(mail.get("allow_send", False))

        cal = config.section("calendar")
        self.calendar_enabled: bool = bool(cal.get("enabled", True))
        self.calendar_files: List[str] = list(cal.get("files", []) or [])
        self.calendar_urls: List[str] = list(cal.get("urls", []) or [])
        self.local_ics: Path = config.resolve(cal.get("local_file", "data/jarvis.ics"))
        self.look_ahead: int = int(cal.get("look_ahead_days", 7))
        self._calendar_cache: Tuple[float, List[CalendarEvent]] = (0.0, [])

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing used when no LLM is available."""
        text = strip_command_prefix(command)
        lowered = text.lower()
        if "status" in lowered and ("mail" in lowered or "calendar" in lowered
                                     or "comms" in lowered):
            return "comms_status", {}
        if "summar" in lowered and ("mail" in lowered or "inbox" in lowered):
            return "summarize_inbox", {}
        if "send" in lowered and ("mail" in lowered or "@" in lowered):
            match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
            return "send_email", {"to": match.group(0) if match else "", "subject": "",
                                  "body": text}
        if any(word in lowered for word in ("email", "inbox", "mail")):
            return "check_email", {"unread_only": "unread" in lowered}
        if any(word in lowered for word in ("add", "schedule", "book", "put")) and any(
            word in lowered for word in ("calendar", "event", "meeting", "appointment")
        ):
            return "add_event", {"title": text, "when": text}
        if "next meeting" in lowered or "next event" in lowered:
            return "next_event", {}
        if any(word in lowered for word in ("calendar", "schedule", "meeting", "agenda",
                                            "appointment")):
            days = 1 if "today" in lowered else self.look_ahead
            return "upcoming_events", {"days": days}
        return "upcoming_events", {"days": self.look_ahead}

    # ------------------------------------------------------------------ email
    @property
    def password(self) -> str:
        """Mail password from the configured environment variable."""
        return os.environ.get(self.password_env, "")

    def _mail_problem(self) -> Optional[str]:
        """Explain why mail can't be used, or ``None`` if it can."""
        if not self.mail_enabled:
            return ("Email is switched off, sir. Enable it under 'email:' in config.yaml "
                    "and set your IMAP/SMTP details.")
        if not self.imap_host or not self.user:
            return "Email is enabled but imap_host or user is blank in config.yaml."
        if not self.password:
            return (f"No password found. Export it first: "
                    f"export {self.password_env}='your-app-password' "
                    f"(use an app password, not your main password).")
        return None

    @staticmethod
    def _decode(value: Optional[str]) -> str:
        """Decode an RFC 2047 encoded header."""
        if not value:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    @staticmethod
    def _body_of(message: email.message.Message) -> str:
        """Extract the best-effort plain-text body of a message."""
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain" and "attachment" not in str(
                    part.get("Content-Disposition", "")
                ):
                    try:
                        payload = part.get_payload(decode=True) or b""
                        return payload.decode(part.get_content_charset() or "utf-8",
                                              errors="replace")
                    except Exception:
                        continue
            return ""
        try:
            payload = message.get_payload(decode=True) or b""
            return payload.decode(message.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            return str(message.get_payload())

    def _fetch(self, unread_only: bool, limit: int, sender: str = "") -> List[Dict[str, Any]]:
        """Blocking IMAP fetch of the most recent messages."""
        context = ssl.create_default_context()
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=context) as client:
            client.login(self.user, self.password)
            client.select(self.mailbox, readonly=True)
            criteria: List[str] = ["UNSEEN"] if unread_only else ["ALL"]
            if sender:
                criteria = ["FROM", f'"{sender}"'] + (["UNSEEN"] if unread_only else [])
            status, data = client.search(None, *criteria)
            if status != "OK":
                return []
            ids = data[0].split()[-limit:]
            messages: List[Dict[str, Any]] = []
            for message_id in reversed(ids):
                status, payload = client.fetch(message_id, "(RFC822)")
                if status != "OK" or not payload or not isinstance(payload[0], tuple):
                    continue
                parsed = email.message_from_bytes(payload[0][1])
                body = self._body_of(parsed)
                messages.append(
                    {
                        "from": self._decode(parsed.get("From")),
                        "subject": self._decode(parsed.get("Subject")) or "(no subject)",
                        "date": self._decode(parsed.get("Date")),
                        "body": truncate(body.strip(), 1500),
                    }
                )
            return messages

    @tool(
        description="Check the inbox over IMAP and list recent or unread messages.",
        params={
            "unread_only": {"type": "boolean", "description": "Only unread mail",
                            "default": True},
            "limit": {"type": "integer", "description": "How many messages", "default": 10},
            "sender": {"type": "string", "description": "Filter by sender", "default": ""},
        },
        untrusted=True,
        keywords=["check my email", "check my mail", "any new mail", "unread mail", "my inbox",
                  "read my email"],
        examples=['check_email(unread_only=true, limit=5)'],
    )
    async def check_email(
        self, unread_only: bool = True, limit: int = 10, sender: str = ""
    ) -> ModuleResult:
        """List recent messages from the configured mailbox."""
        problem = self._mail_problem()
        if problem:
            return ModuleResult.fail(problem)
        try:
            messages = await run_blocking(
                self._fetch, unread_only, max(1, min(int(limit or self.fetch_limit), 50)), sender
            )
        except Exception as exc:
            return ModuleResult.fail(f"IMAP refused me: {truncate(str(exc), 200)}")

        if not messages:
            state = "unread " if unread_only else ""
            return ModuleResult(
                success=True,
                output=f"No {state}mail in {self.mailbox}. Enjoy the silence, sir.",
                speak=f"No {state}mail.",
                data={"messages": []},
            )

        lines = [
            f"{index}. {item['subject']}\n   from {item['from']} · {item['date']}"
            for index, item in enumerate(messages, 1)
        ]
        state = "unread " if unread_only else "recent "
        return ModuleResult(
            success=True,
            output=f"{len(messages)} {state}message(s):\n" + "\n".join(lines),
            speak=f"You have {len(messages)} {state}messages. "
                  f"The latest is '{truncate(messages[0]['subject'], 80)}'.",
            data={"messages": messages},
        )

    @tool(
        description="Summarise unread mail into a short briefing.",
        params={"limit": {"type": "integer", "description": "Messages to read",
                          "default": 5}},
        untrusted=True,
        keywords=["summarize my email", "summarise my inbox", "what's in my inbox",
                  "email briefing"],
    )
    async def summarize_inbox(self, limit: int = 5) -> ModuleResult:
        """Fetch unread mail and have the local LLM condense it."""
        result = await self.check_email(unread_only=True, limit=limit)
        if not result.success:
            return result
        messages = result.data.get("messages", [])
        if not messages:
            return result
        if self.llm is None or not getattr(self.llm, "available", False):
            return result

        digest = "\n\n".join(
            f"From: {item['from']}\nSubject: {item['subject']}\n{truncate(item['body'], 600)}"
            for item in messages
        )
        summary = await self.llm.complete(
            "Summarise these emails for a busy person. One line each: who, what they want, "
            "and whether it needs a reply. Flag anything urgent first.\n\n" + digest,
            temperature=0.3,
            max_tokens=500,
        )
        body = summary.strip() or result.output
        return ModuleResult(
            success=True, output=body, speak=truncate(body, 600),
            data={"messages": messages},
        )

    def _send(self, to: str, subject: str, body: str) -> None:
        """Blocking SMTP send with STARTTLS (or implicit TLS on port 465)."""
        message = EmailMessage()
        message["From"] = self.user
        message["To"] = to
        message["Subject"] = subject
        message["Date"] = email.utils.formatdate(localtime=True)
        message["Message-ID"] = email.utils.make_msgid()
        message.set_content(body)

        context = ssl.create_default_context()
        if self.smtp_port == 465:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context) as server:
                server.login(self.user, self.password)
                server.send_message(message)
            return
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(self.user, self.password)
            server.send_message(message)

    @tool(
        description="Send an email over SMTP (requires email.allow_send).",
        params={
            "to": {"type": "string", "description": "Recipient address", "required": True},
            "subject": {"type": "string", "description": "Subject line", "default": ""},
            "body": {"type": "string", "description": "Message body", "required": True},
        },
        dangerous=True,
        keywords=["send an email", "email him", "email her", "reply to that email",
                  "send a mail to"],
        examples=['send_email(to="alice@example.com", subject="Late", body="Running 10 late.")'],
    )
    async def send_email(self, to: str, body: str, subject: str = "") -> ModuleResult:
        """Send a message, provided sending is explicitly enabled."""
        problem = self._mail_problem()
        if problem:
            return ModuleResult.fail(problem)
        if not self.allow_send:
            return ModuleResult.fail(
                "Sending is disabled for your protection. Set email.allow_send: true in "
                "config.yaml if you'd like me to speak on your behalf."
            )
        if not to or "@" not in to:
            return ModuleResult.fail("I need a valid recipient address, sir.")
        if not self.smtp_host:
            return ModuleResult.fail("No smtp_host configured.")

        subject = subject or "(no subject)"
        try:
            await run_blocking(self._send, to, subject, body)
        except Exception as exc:
            return ModuleResult.fail(f"SMTP rejected the message: {truncate(str(exc), 200)}")
        return ModuleResult(
            success=True,
            output=f"Sent '{subject}' to {to}.",
            speak="Message sent, sir.",
            data={"to": to, "subject": subject},
        )

    # --------------------------------------------------------------- calendar
    async def _load_events(self, refresh: bool = False) -> List[CalendarEvent]:
        """Load and merge events from every configured calendar source."""
        if not self.calendar_enabled:
            return []
        now = datetime.now().timestamp()
        cached_at, cached = self._calendar_cache
        if not refresh and cached and now - cached_at < 300:
            return cached

        events: List[CalendarEvent] = []
        paths = [Path(item).expanduser() for item in self.calendar_files]
        if self.local_ics.exists():
            paths.append(self.local_ics)
        for path in paths:
            try:
                if path.exists():
                    raw = await run_blocking(path.read_text, "utf-8", "replace")
                    events.extend(parse_ics(raw, source=path.name))
            except Exception as exc:
                self.log.debug("Calendar file %s failed: %s", path, exc)

        for url in self.calendar_urls:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    events.extend(parse_ics(response.text, source="remote"))
            except Exception as exc:
                self.log.debug("Calendar URL failed: %s", truncate(str(exc), 120))

        events.sort(key=lambda item: item.start)
        self._calendar_cache = (now, events)
        return events

    @tool(
        description="List upcoming calendar events.",
        params={
            "days": {"type": "integer", "description": "Days to look ahead", "default": 7},
            "refresh": {"type": "boolean", "description": "Bypass the 5-minute cache",
                        "default": False},
        },
        untrusted=True,
        keywords=["my calendar", "my schedule", "what's on today", "agenda", "my meetings",
                  "appointments", "events this week"],
        examples=["upcoming_events(days=1)"],
    )
    async def upcoming_events(self, days: int = 7, refresh: bool = False) -> ModuleResult:
        """Show everything scheduled in the next ``days`` days."""
        if not self.calendar_enabled:
            return ModuleResult.fail("The calendar module is switched off in config.yaml.")
        events = await self._load_events(refresh=refresh)
        if not events:
            return ModuleResult(
                success=True,
                output="No calendar sources have any events. Add .ics files or a secret "
                "calendar URL under 'calendar:' in config.yaml, or say "
                "'add an event' to use the local calendar.",
                speak="Your calendar appears to be gloriously empty.",
                data={"events": []},
            )

        now = datetime.now()
        horizon = now + timedelta(days=max(1, int(days or 1)))
        window = [
            event for event in events
            if event.start >= now.replace(hour=0, minute=0, second=0, microsecond=0)
            and event.start <= horizon
        ]
        if not window:
            return ModuleResult(
                success=True,
                output=f"Nothing scheduled in the next {days} day(s), sir.",
                speak=f"Nothing in the next {days} days.",
                data={"events": []},
            )

        grouped: Dict[date, List[CalendarEvent]] = {}
        for event in window:
            grouped.setdefault(event.start.date(), []).append(event)
        lines: List[str] = []
        for day in sorted(grouped):
            label = "Today" if day == now.date() else (
                "Tomorrow" if day == now.date() + timedelta(days=1)
                else day.strftime("%A %d %B")
            )
            lines.append(label)
            lines += [f"  {event.describe()}" for event in grouped[day]]

        first = window[0]
        return ModuleResult(
            success=True,
            output="\n".join(lines),
            speak=f"{len(window)} event(s) coming up. Next: {first.describe()}.",
            data={"events": [event.to_dict() for event in window]},
        )

    @tool(
        description="Report the very next calendar event.",
        params={},
        untrusted=True,
        keywords=["next meeting", "next event", "when is my next", "what's next"],
    )
    async def next_event(self) -> ModuleResult:
        """Find the next event that hasn't started yet."""
        events = await self._load_events()
        now = datetime.now()
        future = [event for event in events if event.start >= now]
        if not future:
            return ModuleResult(
                success=True,
                output="Nothing else on the calendar, sir. The rest of the day is yours.",
                speak="Nothing else scheduled.",
                data={},
            )
        event = future[0]
        delta = event.start - now
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        countdown = f"{hours}h {minutes}m" if hours else f"{minutes}m"
        return ModuleResult(
            success=True,
            output=f"{event.describe()} — in {countdown}."
            + (f"\n{truncate(event.description, 300)}" if event.description else ""),
            speak=f"Next up in {countdown}: {event.summary}.",
            data=event.to_dict(),
        )

    @tool(
        description="Add an event to the local .ics calendar.",
        params={
            "title": {"type": "string", "description": "Event title", "required": True},
            "when": {"type": "string", "description": "When, e.g. 'tomorrow at 3pm'",
                     "required": True},
            "duration_minutes": {"type": "integer", "description": "Length in minutes",
                                 "default": 60},
            "location": {"type": "string", "description": "Where", "default": ""},
        },
        keywords=["add to my calendar", "schedule a meeting", "put it in my calendar",
                  "book a slot"],
        examples=['add_event(title="Dentist", when="friday at 9am")'],
    )
    async def add_event(
        self, title: str, when: str, duration_minutes: int = 60, location: str = ""
    ) -> ModuleResult:
        """Append a VEVENT to the local calendar file."""
        start = parse_when(when)
        if start is None:
            return ModuleResult.fail(
                f"I couldn't work out when '{when}' is. Try 'tomorrow at 3pm' or "
                "'2026-09-12 14:00'."
            )
        end = start + timedelta(minutes=max(5, int(duration_minutes or 60)))
        uid = f"{uuid.uuid4().hex}@jarvis.local"
        block = "\n".join(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{datetime.now():%Y%m%dT%H%M%S}",
                f"DTSTART:{start:%Y%m%dT%H%M%S}",
                f"DTEND:{end:%Y%m%dT%H%M%S}",
                f"SUMMARY:{title.replace(',', chr(92) + ',')}",
                *( [f"LOCATION:{location}"] if location else [] ),
                "END:VEVENT",
            ]
        )

        def _write() -> None:
            ensure_dir(self.local_ics.parent)
            if self.local_ics.exists():
                content = self.local_ics.read_text(encoding="utf-8", errors="replace")
                if "END:VCALENDAR" in content:
                    content = content.replace("END:VCALENDAR", f"{block}\nEND:VCALENDAR")
                else:
                    content = f"{content.rstrip()}\n{block}\nEND:VCALENDAR\n"
            else:
                content = (
                    "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//JARVIS//Local Calendar//EN\n"
                    f"{block}\nEND:VCALENDAR\n"
                )
            self.local_ics.write_text(content, encoding="utf-8")

        try:
            await run_blocking(_write)
        except Exception as exc:
            return ModuleResult.fail(f"Couldn't write the calendar file: {exc}")
        self._calendar_cache = (0.0, [])
        return ModuleResult(
            success=True,
            output=f"Added '{title}' on {start:%a %d %b at %H:%M} to {self.local_ics.name}.",
            speak=f"'{title}' is in your calendar for {start:%A at %H:%M}.",
            data={"title": title, "start": start.isoformat(timespec="minutes"), "uid": uid},
        )

    @tool(
        description="Report whether email and calendar are configured and reachable.",
        params={},
        keywords=["email status", "calendar status", "is my mail configured"],
    )
    async def comms_status(self) -> ModuleResult:
        """Diagnose the mail and calendar configuration."""
        mail_problem = self._mail_problem()
        events = await self._load_events()
        lines = [
            "Email: " + (mail_problem or
                         f"configured for {self.user} at {self.imap_host} "
                         f"(sending {'enabled' if self.allow_send else 'disabled'})"),
            f"Calendar: {'enabled' if self.calendar_enabled else 'disabled'} · "
            f"{len(self.calendar_files)} file(s), {len(self.calendar_urls)} URL(s), "
            f"local file {self.local_ics} · {len(events)} event(s) loaded",
        ]
        return ModuleResult(
            success=True,
            output="\n".join(lines),
            data={"email_ready": mail_problem is None, "events": len(events)},
        )


__all__ = ["Communications", "CalendarEvent", "parse_ics"]

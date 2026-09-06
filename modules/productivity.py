# /modules/productivity.py
"""Todos, reminders, timers, notes and the daily briefing — all SQLite backed."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, ClassVar, Dict, List, Optional, Tuple

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import (
    IS_MACOS,
    IS_WINDOWS,
    ensure_dir,
    friendly_when,
    human_duration,
    parse_duration,
    parse_when,
    run_blocking,
    run_command,
    safe_filename,
    slugify,
    truncate,
    which,
)
from utils.scheduler import Scheduler

SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT NOT NULL,
    priority TEXT DEFAULT 'normal',
    due TEXT,
    tags TEXT DEFAULT '',
    done INTEGER DEFAULT 0,
    created TEXT,
    completed TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    due TEXT NOT NULL,
    fired INTEGER DEFAULT 0,
    created TEXT,
    repeat TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    body TEXT,
    tags TEXT DEFAULT '',
    created TEXT,
    updated TEXT
);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT NOT NULL,
    action TEXT NOT NULL,
    params TEXT DEFAULT '{}',
    rule TEXT NOT NULL,
    next_run TEXT NOT NULL,
    last_run TEXT DEFAULT '',
    enabled INTEGER DEFAULT 1,
    runs INTEGER DEFAULT 0,
    created TEXT
);
CREATE TABLE IF NOT EXISTS routines (
    name TEXT PRIMARY KEY,
    steps TEXT NOT NULL,
    created TEXT
);
CREATE TABLE IF NOT EXISTS deferred_notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created TEXT
);
CREATE INDEX IF NOT EXISTS idx_todos_done ON todos(done);
CREATE INDEX IF NOT EXISTS idx_reminders_fired ON reminders(fired);
CREATE INDEX IF NOT EXISTS idx_schedules_next ON schedules(enabled, next_run);
"""

#: Weekday names accepted in schedule rules, Monday first.
WEEKDAYS: Dict[str, int] = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


@dataclass
class ScheduleRule:
    """A parsed recurring-schedule rule.

    Attributes:
        kind: ``daily``, ``weekly``, ``weekdays``, ``weekends``, ``hourly``,
            ``interval`` or ``once``.
        hour: Hour of day for time-based rules.
        minute: Minute of the hour.
        weekdays: Which weekdays the job may run on (Monday = 0).
        seconds: Interval length for ``interval`` rules.
        text: The original phrase, kept for display.
    """

    kind: str = "daily"
    hour: int = 8
    minute: int = 0
    weekdays: Tuple[int, ...] = ()
    seconds: int = 0
    text: str = ""

    def describe(self) -> str:
        """Human-readable version of the rule."""
        clock = f"{self.hour:02d}:{self.minute:02d}"
        if self.kind == "interval":
            return f"every {human_duration(self.seconds)}"
        if self.kind == "hourly":
            return f"every hour at :{self.minute:02d}"
        if self.kind == "weekdays":
            return f"every weekday at {clock}"
        if self.kind == "weekends":
            return f"every weekend day at {clock}"
        if self.kind == "weekly" and self.weekdays:
            names = ", ".join(
                ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"][day]
                for day in self.weekdays
            )
            return f"every {names} at {clock}"
        if self.kind == "once":
            return f"once at {clock}"
        return f"every day at {clock}"

    def next_after(self, moment: datetime) -> datetime:
        """Return the first firing time strictly after ``moment``.

        Args:
            moment: The reference time.

        Returns:
            The next datetime this rule fires.
        """
        if self.kind == "interval":
            return moment + timedelta(seconds=max(30, self.seconds))
        if self.kind == "hourly":
            candidate = moment.replace(minute=self.minute, second=0, microsecond=0)
            if candidate <= moment:
                candidate += timedelta(hours=1)
            return candidate

        allowed: Tuple[int, ...] = self.weekdays
        if self.kind == "weekdays":
            allowed = (0, 1, 2, 3, 4)
        elif self.kind == "weekends":
            allowed = (5, 6)
        elif self.kind in ("daily", "once") or not allowed:
            allowed = (0, 1, 2, 3, 4, 5, 6)

        candidate = moment.replace(hour=self.hour, minute=self.minute,
                                   second=0, microsecond=0)
        if candidate <= moment:
            candidate += timedelta(days=1)
        for _ in range(8):
            if candidate.weekday() in allowed:
                return candidate
            candidate += timedelta(days=1)
        return candidate


def _too_soon(last_run: Any, now: datetime, rule: ScheduleRule) -> bool:
    """Whether a job already ran within the current period.

    When the local clock jumps backwards (the end of daylight saving) the same
    wall-clock hour happens twice, which would otherwise fire an hourly or
    daily job a second time. A job is considered already done if its previous
    run was less than half a period ago.

    Args:
        last_run: The stored ISO timestamp of the previous run, if any.
        now: The current time.
        rule: The rule being evaluated.

    Returns:
        True when the job should be skipped this time round.
    """
    if not last_run:
        return False
    try:
        previous = datetime.fromisoformat(str(last_run))
    except Exception:
        return False
    period = {
        "interval": max(30, rule.seconds),
        "hourly": 3600,
    }.get(rule.kind, 86400)
    elapsed = (now - previous).total_seconds()
    return 0 <= elapsed < period / 2


def parse_quiet_hours(text: str) -> Optional[Tuple[int, int]]:
    """Parse ``"22:30-07:00"`` into minutes-since-midnight bounds.

    Args:
        text: The configured window, empty to disable.

    Returns:
        ``(start, end)`` in minutes, or ``None`` when unset or unparsable.
    """
    match = re.match(
        r"\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|to|until|–)\s*"
        r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$",
        (text or "").lower(),
    )
    if not match:
        return None

    def _minutes(hour_text: str, minute_text: Optional[str],
                 meridiem: Optional[str]) -> Optional[int]:
        hour = int(hour_text)
        minute = int(minute_text or 0)
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour * 60 + minute

    start = _minutes(match.group(1), match.group(2), match.group(3))
    end = _minutes(match.group(4), match.group(5), match.group(6))
    if start is None or end is None:
        return None
    return start, end


def parse_schedule(text: str) -> Optional[ScheduleRule]:
    """Turn "every weekday at 8am" into a :class:`ScheduleRule`.

    Understands: ``every day/morning/evening at HH:MM``, ``every weekday``,
    ``every weekend``, ``every monday``, ``every hour``, ``every 30 minutes``,
    ``daily at 7``, ``hourly``, and bare times like ``at 18:30``.

    Args:
        text: The phrase the user said.

    Returns:
        A parsed rule, or ``None`` when nothing recognisable was found.
    """
    lowered = " ".join((text or "").lower().split())
    if not lowered:
        return None

    hour, minute = 8, 0
    clock = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered)
    explicit_time = False
    if clock and ("at " in lowered or clock.group(3) or ":" in clock.group(0)):
        candidate_hour = int(clock.group(1))
        candidate_minute = int(clock.group(2) or 0)
        meridiem = clock.group(3)
        if meridiem == "pm" and candidate_hour < 12:
            candidate_hour += 12
        elif meridiem == "am" and candidate_hour == 12:
            candidate_hour = 0
        if 0 <= candidate_hour <= 23 and 0 <= candidate_minute <= 59:
            hour, minute, explicit_time = candidate_hour, candidate_minute, True

    if "morning" in lowered and not explicit_time:
        hour, minute = 8, 0
    elif "afternoon" in lowered and not explicit_time:
        hour, minute = 14, 0
    elif ("evening" in lowered or "tonight" in lowered) and not explicit_time:
        hour, minute = 19, 0
    elif "night" in lowered and not explicit_time:
        hour, minute = 22, 0
    elif "noon" in lowered:
        hour, minute = 12, 0

    interval = re.search(
        r"every\s+(\d+)\s*(second|sec|minute|min|hour|hr|day)s?\b", lowered
    )
    if interval:
        amount = int(interval.group(1))
        unit = interval.group(2)
        factor = {"second": 1, "sec": 1, "minute": 60, "min": 60,
                  "hour": 3600, "hr": 3600, "day": 86400}[unit]
        return ScheduleRule(kind="interval", seconds=amount * factor, text=lowered)

    if re.search(r"\b(hourly|every hour)\b", lowered):
        return ScheduleRule(kind="hourly", minute=minute, text=lowered)
    if "weekday" in lowered or "work day" in lowered or "workday" in lowered:
        return ScheduleRule(kind="weekdays", hour=hour, minute=minute, text=lowered)
    if "weekend" in lowered:
        return ScheduleRule(kind="weekends", hour=hour, minute=minute, text=lowered)

    days = tuple(sorted({
        number for name, number in WEEKDAYS.items()
        if re.search(rf"\b{name}s?\b", lowered)
    }))
    if days:
        return ScheduleRule(kind="weekly", hour=hour, minute=minute,
                            weekdays=days, text=lowered)

    if re.search(r"\b(every ?day|daily|each day|every morning|every evening|"
                 r"every afternoon|every night)\b", lowered):
        return ScheduleRule(kind="daily", hour=hour, minute=minute, text=lowered)
    if explicit_time:
        return ScheduleRule(kind="daily", hour=hour, minute=minute, text=lowered)
    return None


class Productivity(BaseModule):
    """Personal organisation: tasks, reminders, timers, notes, briefings."""

    name = "productivity"
    description = (
        "Personal productivity: todo list, reminders with notifications, timers and a "
        "stopwatch, note taking with search, and a daily briefing."
    )
    intent_examples: ClassVar[List[str]] = [
        "add buy milk to my todo list",
        "remind me to call mom at 5pm",
        "set a timer for 10 minutes",
        "take a note: the wifi password is hunter2",
        "give me my daily briefing",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Open the SQLite database and prepare in-memory timers."""
        super().__init__(config, llm=llm, security=security)
        self.db_path: Path = config.resolve(config.get("database.path", "data/jarvis.db"))
        ensure_dir(self.db_path.parent)
        self.notes_dir: Path = config.path_for("notes")
        self.timers: Dict[str, Dict[str, Any]] = {}
        self.stopwatches: Dict[str, Dict[str, Any]] = {}
        self.notifier: Optional[Callable[[str], Any]] = None
        self.brain: Any = None
        self.catch_up_on_start: bool = bool(config.get("productivity.catch_up_on_start", True))
        self.scheduler_interval: int = max(
            5, int(config.get("productivity.scheduler_interval", 15) or 15)
        )
        self.quiet_hours: Optional[Tuple[int, int]] = parse_quiet_hours(
            str(config.get("productivity.quiet_hours", "") or "")
        )
        self._scheduler_task: Optional[asyncio.Task] = None
        #: APScheduler when it is installed, an asyncio fallback when it is not.
        self._scheduler = Scheduler(
            timezone=str(config.get("user.timezone", "") or ""),
            prefer_apscheduler=bool(config.get("productivity.use_apscheduler", True)),
        )
        self._init_db()

    # ------------------------------------------------------------------ infra
    def _connect(self) -> sqlite3.Connection:
        """Open a configured SQLite connection."""
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_db(self) -> None:
        """Create tables if they do not exist."""
        try:
            with self._connect() as connection:
                connection.executescript(SCHEMA)
        except Exception as exc:
            self.log.error("Could not initialise productivity tables: %s", exc)

    def set_notifier(self, notifier: Optional[Callable[[str], Any]]) -> None:
        """Register the callback used to announce reminders and timers."""
        self.notifier = notifier

    async def setup(self) -> None:
        """Start the background scheduler and report anything missed."""
        if not self._scheduler.running:
            engine = self._scheduler.start()
            self._scheduler.every(
                self.scheduler_interval, self._tick,
                job_id="productivity-tick", name="reminder and schedule poll",
            )
            self.log.debug("Reminder scheduler started (%s engine).", engine)
        if self.catch_up_on_start:
            await self._catch_up()

    async def _catch_up(self) -> None:
        """Report reminders and jobs that came due while JARVIS was off.

        A reminder that fired into an empty room is worse than useless, so on
        every start-up JARVIS looks for overdue items and mentions them once,
        rather than silently swallowing them or firing a dozen alerts at once.
        """
        try:
            missed = await run_blocking(self._collect_missed)
        except Exception as exc:  # pragma: no cover - defensive
            self.log.debug("Catch-up failed: %s", exc)
            return
        if not missed:
            return
        if len(missed) == 1:
            await self._announce(f"While I was away: {missed[0]}")
        else:
            listed = "; ".join(missed[:5])
            extra = f" (and {len(missed) - 5} more)" if len(missed) > 5 else ""
            await self._announce(f"While I was away, {len(missed)} things came due: "
                                 f"{listed}{extra}")

    def _collect_missed(self) -> List[str]:
        """Mark overdue reminders and jobs as handled, returning descriptions."""
        found: List[str] = []
        now = datetime.now()
        stamp = now.isoformat(timespec="seconds")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, text, due FROM reminders WHERE fired = 0 AND due <= ? "
                "ORDER BY due", (stamp,),
            ).fetchall()
            for row in rows:
                try:
                    due = datetime.fromisoformat(row["due"])
                    late = human_duration((now - due).total_seconds())
                except Exception:
                    late = "a while"
                found.append(f"{row['text']} ({late} ago)")
                connection.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],))

            jobs = connection.execute(
                "SELECT id, description, rule, next_run FROM schedules "
                "WHERE enabled = 1 AND next_run <= ?", (stamp,),
            ).fetchall()
            for job in jobs:
                rule = parse_schedule(job["rule"]) or ScheduleRule(text=job["rule"])
                connection.execute(
                    "UPDATE schedules SET next_run = ? WHERE id = ?",
                    (rule.next_after(now).isoformat(timespec="seconds"), job["id"]),
                )
                found.append(f"the scheduled '{job['description']}' was skipped")
        return found

    async def shutdown(self) -> None:
        """Cancel the scheduler and any running timers."""
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except (asyncio.CancelledError, Exception):
                pass
            self._scheduler_task = None
        for entry in list(self.timers.values()):
            task = entry.get("task")
            if task:
                task.cancel()
        self.timers.clear()

    def in_quiet_hours(self, moment: Optional[datetime] = None) -> bool:
        """Whether proactive announcements should stay silent right now.

        Args:
            moment: The time to test (defaults to now).

        Returns:
            True inside the configured ``productivity.quiet_hours`` window.
        """
        if not self.quiet_hours:
            return False
        moment = moment or datetime.now()
        minutes = moment.hour * 60 + moment.minute
        start, end = self.quiet_hours
        if start == end:
            return False
        if start < end:
            return start <= minutes < end
        return minutes >= start or minutes < end  # window crosses midnight

    async def _announce_proactive(self, message: str) -> None:
        """Announce something JARVIS decided to say, respecting quiet hours.

        Explicit reminders always come through — you asked for those. Anything
        JARVIS raises on its own initiative is held until the quiet window
        closes rather than waking the house.

        Args:
            message: The text to deliver.
        """
        if self.in_quiet_hours():
            self.log.info("Quiet hours — holding: %s", truncate(message, 80))
            await run_blocking(self._defer_notice, message)
            return
        await self._announce(message)

    def _defer_notice(self, message: str) -> None:
        """Store an announcement to be delivered once quiet hours end."""
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO deferred_notices (text, created) VALUES (?, ?)",
                    (message, datetime.now().isoformat(timespec="seconds")),
                )
        except Exception as exc:  # pragma: no cover - defensive
            self.log.debug("Could not defer a notice: %s", exc)

    def _take_deferred(self) -> List[str]:
        """Pop every held announcement."""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT id, text FROM deferred_notices ORDER BY id"
                ).fetchall()
                if rows:
                    connection.execute("DELETE FROM deferred_notices")
                return [row["text"] for row in rows]
        except Exception as exc:  # pragma: no cover - defensive
            self.log.debug("Could not read deferred notices: %s", exc)
            return []

    async def _flush_deferred(self) -> None:
        """Deliver anything held back during quiet hours."""
        if self.in_quiet_hours():
            return
        held = await run_blocking(self._take_deferred)
        if not held:
            return
        if len(held) == 1:
            await self._announce(f"Held from quiet hours: {held[0]}")
        else:
            await self._announce(
                f"{len(held)} things were held during quiet hours: " + "; ".join(held[:5])
            )

    async def _announce(self, message: str) -> None:
        """Speak/print a notification and raise a desktop toast."""
        self.log.info("Notification: %s", message)
        if self.notifier is not None:
            try:
                result = self.notifier(message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                self.log.debug("Notifier failed: %s", exc)
        await self._desktop_notify("JARVIS", message)

    @staticmethod
    async def _desktop_notify(title: str, message: str) -> None:
        """Best-effort native desktop notification."""
        try:
            if IS_MACOS:
                script = f'display notification "{message}" with title "{title}"'
                await run_command(["osascript", "-e", script], timeout=10)
            elif IS_WINDOWS:
                script = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$n=New-Object System.Windows.Forms.NotifyIcon; "
                    "$n.Icon=[System.Drawing.SystemIcons]::Information; "
                    "$n.Visible=$true; "
                    f"$n.ShowBalloonTip(8000,'{title}','{message}','Info')"
                )
                await run_command(["powershell", "-NoProfile", "-Command", script], timeout=10)
            elif which("notify-send"):
                await run_command(["notify-send", title, message], timeout=10)
        except Exception:
            pass

    async def _tick(self) -> None:
        """One scheduler pass: fire due reminders and jobs, flush held speech.

        Called by :class:`utils.scheduler.Scheduler` every
        ``productivity.scheduler_interval`` seconds. Never raises — a failure
        here would silently kill every future reminder.
        """
        try:
            for row in await run_blocking(self._pop_due_reminders):
                await self._announce(f"Reminder: {row['text']}")
            for job in await run_blocking(self._pop_due_jobs):
                await self._run_job(job)
            await self._flush_deferred()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.log.debug("Scheduler hiccup: %s", exc)

    async def _scheduler_loop(self) -> None:
        """Poll in a plain loop — used only if the Scheduler cannot start."""
        while True:
            try:
                await asyncio.sleep(self.scheduler_interval)
                await self._tick()
            except asyncio.CancelledError:
                break

    def _pop_due_jobs(self) -> List[Dict[str, Any]]:
        """Return scheduled jobs that are due, and reschedule them."""
        jobs: List[Dict[str, Any]] = []
        try:
            now = datetime.now()
            stamp = now.isoformat(timespec="seconds")
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM schedules WHERE enabled = 1 AND next_run <= ?", (stamp,)
                ).fetchall()
                for row in rows:
                    job = dict(row)
                    rule = parse_schedule(job["rule"]) or ScheduleRule(text=job["rule"])
                    following = rule.next_after(now)
                    # Local clocks can repeat an hour when daylight saving ends;
                    # never run the same job twice inside one of its periods.
                    if _too_soon(job.get("last_run"), now, rule):
                        connection.execute(
                            "UPDATE schedules SET next_run = ? WHERE id = ?",
                            (following.isoformat(timespec="seconds"), job["id"]),
                        )
                        continue
                    connection.execute(
                        "UPDATE schedules SET next_run = ?, last_run = ?, runs = runs + 1 "
                        "WHERE id = ?",
                        (following.isoformat(timespec="seconds"), stamp, job["id"]),
                    )
                    jobs.append(job)
        except Exception as exc:
            self.log.debug("Could not read the schedule: %s", exc)
        return jobs

    async def _run_job(self, job: Dict[str, Any]) -> None:
        """Execute one scheduled job and announce the outcome.

        Args:
            job: The row from the ``schedules`` table.
        """
        action = str(job.get("action") or "").strip()
        description = str(job.get("description") or action)
        try:
            params = json.loads(job.get("params") or "{}")
            if not isinstance(params, dict):
                params = {}
        except Exception:
            params = {}
        self.log.info("Running scheduled job '%s' (%s).", description, action)
        try:
            spoken = await self._perform(action, params, description)
        except Exception as exc:
            self.log.warning("Scheduled job '%s' failed: %s", description, exc)
            spoken = f"The scheduled '{description}' failed: {truncate(str(exc), 120)}"
        if spoken:
            await self._announce_proactive(spoken)

    async def _perform(self, action: str, params: Dict[str, Any],
                       description: str) -> str:
        """Carry out one scheduled action and return what to say about it.

        Args:
            action: ``say:…``, ``ask:…``, ``routine:…`` or ``module.tool``.
            params: Parameters for a tool action.
            description: Human label used in the spoken result.

        Returns:
            The text to announce (empty to stay silent).
        """
        if action.startswith("say:"):
            return action[4:].strip() or description

        if action.startswith("ask:"):
            question = action[4:].strip()
            if self.brain is None:
                return question
            reply = await self.brain.process(question)
            return truncate(reply, 600)

        if action.startswith("routine:"):
            return await self._perform_routine(action[8:].strip())

        if self.brain is not None and hasattr(self.brain, "dispatch"):
            result = await self.brain.dispatch(action, params)
        else:
            result = await self.call_tool(action.split(".")[-1], params)
        spoken = result.spoken() if hasattr(result, "spoken") else str(result)
        return f"{description}: {truncate(spoken, 600)}"

    async def _perform_routine(self, name: str) -> str:
        """Run every step of a named routine in order.

        Args:
            name: The routine's name.

        Returns:
            A combined announcement, or an error when the routine is unknown.
        """
        steps = await run_blocking(self._read_routine, name)
        if steps is None:
            return f"The routine '{name}' no longer exists, sir."
        pieces: List[str] = []
        for step in steps:
            action, params = self._resolve_action(step)
            try:
                spoken = await self._perform(action, params, step)
            except Exception as exc:
                self.log.warning("Routine step '%s' failed: %s", step, exc)
                spoken = f"{step} failed"
            if spoken:
                pieces.append(spoken)
        if not pieces:
            return f"The routine '{name}' had nothing to do, sir."
        return f"{name.capitalize()}. " + " ".join(pieces)

    def _read_routine(self, name: str) -> Optional[List[str]]:
        """Return a routine's steps, or ``None`` when it does not exist."""
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT steps FROM routines WHERE name = ?", (name.strip().lower(),)
                ).fetchone()
        except Exception as exc:  # pragma: no cover - defensive
            self.log.debug("Could not read routine '%s': %s", name, exc)
            return None
        if row is None:
            return None
        try:
            steps = json.loads(row["steps"])
        except Exception:
            return None
        return [str(step) for step in steps if str(step).strip()]

    @tool(
        description=(
            "Schedule something to happen regularly — a briefing every weekday morning, "
            "a question answered every hour, a nudge every Friday."
        ),
        params={
            "when": {"type": "string", "required": True,
                     "description": "'every weekday at 8am', 'daily at 19:00', "
                                    "'every 30 minutes', 'every monday at 9'"},
            "what": {"type": "string", "required": True,
                     "description": "What to do: plain words to say, a question to answer, "
                                    "a 'name routine', or a module.tool reference"},
            "params": {"type": "object", "default": {},
                       "description": "Optional parameters for a module.tool action"},
        },
        keywords=["every day at", "every morning", "every weekday", "every monday",
                  "schedule a", "schedule my", "recurring reminder", "every hour",
                  "each morning", "from now on every"],
        examples=['schedule_recurring(when="every weekday at 8am", what="daily briefing")'],
    )
    async def schedule_recurring(self, when: str, what: str,
                                 params: Optional[Dict[str, Any]] = None) -> ModuleResult:
        """Create a repeating job.

        Args:
            when: A phrase describing the repetition.
            what: A tool reference, a routine, a question, or words to say.
            params: Explicit parameters when ``what`` names a tool.

        Returns:
            Confirmation including the next firing time.
        """
        rule = parse_schedule(when)
        if rule is None:
            return ModuleResult.fail(
                "I could not read that schedule, sir. Try 'every weekday at 8am', "
                "'daily at 19:30', 'every monday at 9' or 'every 30 minutes'."
            )

        target = (what or "").strip()
        if not target:
            return ModuleResult.fail("And what should I do at that time, sir?")

        action, resolved = self._resolve_action(target)
        if isinstance(params, dict) and params:
            resolved = {**resolved, **params}
        if action.startswith("routine:"):
            name = action[8:]
            if await run_blocking(self._read_routine, name) is None:
                return ModuleResult.fail(
                    f"There is no routine called '{name}', sir. Create it first with "
                    f"'create a {name} routine that does …'."
                )
        next_run = rule.next_after(datetime.now())
        encoded = json.dumps(resolved, ensure_ascii=False)

        def _insert() -> int:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO schedules (description, action, params, rule, next_run, "
                    "created) VALUES (?, ?, ?, ?, ?, ?)",
                    (truncate(target, 120), action, encoded, when.strip(),
                     next_run.isoformat(timespec="seconds"),
                     datetime.now().isoformat(timespec="seconds")),
                )
                return int(cursor.lastrowid or 0)

        job_id = await run_blocking(_insert)
        return ModuleResult(
            success=True,
            output=(
                f"Scheduled #{job_id}: {truncate(target, 100)}\n"
                f"  when : {rule.describe()}\n"
                f"  next : {next_run:%A %d %B at %H:%M}\n"
                f"  action: {action}"
                + (f" {encoded}" if resolved else "")
            ),
            speak=f"Done, sir. {rule.describe().capitalize()}, starting "
                  f"{friendly_when(next_run)}.",
            data={"id": job_id, "next_run": next_run.isoformat(), "action": action,
                  "params": resolved},
        )

    #: Plain-English names for tools a schedule commonly calls.
    ACTION_SHORTCUTS: ClassVar[Dict[str, str]] = {
        "daily briefing": "productivity.daily_briefing",
        "morning briefing": "productivity.daily_briefing",
        "briefing": "productivity.daily_briefing",
        "brief me": "productivity.daily_briefing",
        "my todos": "productivity.list_todos",
        "my todo list": "productivity.list_todos",
        "my tasks": "productivity.list_todos",
        "my reminders": "productivity.list_reminders",
        "the weather": "web_search.weather",
        "weather": "web_search.weather",
        "the forecast": "web_search.weather",
        "the news": "web_search.news",
        "news": "web_search.news",
        "the headlines": "web_search.news",
        "my email": "communications.check_email",
        "my inbox": "communications.summarize_inbox",
        "my calendar": "communications.upcoming_events",
        "my agenda": "communications.upcoming_events",
        "system stats": "system_control.system_stats",
        "the time": "system_control.current_time",
    }

    #: Which parameter carries the free-text argument of a shortcut tool.
    ACTION_ARGUMENTS: ClassVar[Dict[str, str]] = {
        "web_search.weather": "location",
        "web_search.news": "topic",
        "web_search.search": "query",
    }

    @classmethod
    def _resolve_action(cls, target: str) -> Tuple[str, Dict[str, Any]]:
        """Turn what the user asked for into an executable action.

        Args:
            target: The user's phrasing.

        Returns:
            A ``(action, params)`` pair where action is ``module.tool``,
            ``routine:<name>``, ``ask:<question>`` or ``say:<words>``.
        """
        cleaned = " ".join((target or "").strip().split())
        if not cleaned:
            return "say:", {}

        # An explicit tool reference, optionally with a plain argument.
        direct = re.fullmatch(r"([a-z_]+\.[a-z_]+)(?:\s+(.+))?", cleaned)
        if direct:
            reference = direct.group(1)
            argument = (direct.group(2) or "").strip()
            key = cls.ACTION_ARGUMENTS.get(reference)
            if argument and key:
                return reference, {key: argument}
            return reference, {}

        lowered = cleaned.lower()
        routine = re.fullmatch(
            r"(?:(?:please\s+)?(?:run|start|do|execute|perform)\s+)?"
            r"(?:the\s+|my\s+)?(.+?)\s+routine", lowered,
        )
        if routine:
            return f"routine:{routine.group(1).strip()}", {}

        # Longest phrases first so "the weather" beats "weather".
        for phrase in sorted(cls.ACTION_SHORTCUTS, key=len, reverse=True):
            reference = cls.ACTION_SHORTCUTS[phrase]
            match = re.search(rf"(?:^|\b){re.escape(phrase)}\b", lowered)
            if not match:
                continue
            remainder = (lowered[: match.start()] + " " + lowered[match.end():]).strip()
            # Only accept filler around the phrase, never a whole other sentence.
            argument = ""
            key = cls.ACTION_ARGUMENTS.get(reference)
            if key:
                tail = lowered[match.end():]
                detail = re.search(r"\b(?:in|for|about|on|at|regarding)\s+(.+)$", tail)
                if detail:
                    # Slice the original text so "Paris" keeps its capital P.
                    argument = cleaned[match.end() + detail.start(1):].strip(" ?.!,")
                    remainder = remainder.replace(detail.group(0).strip(), "").strip()
            filler = re.sub(
                r"\b(?:give|tell|show|read|send|get|fetch|check|run|do|does|and|then|"
                r"also|with|me|my|the|a|an|please|out|loud|today's|todays|current|"
                r"latest|update|report)\b", "", remainder,
            ).strip(" ,.?!")
            if filler:
                continue  # too much left over — treat it as a question instead
            return reference, ({key: argument} if key and argument else {})

        first_word = lowered.split(" ")[0]
        if lowered.endswith("?") or first_word in {
            "what", "when", "how", "who", "where", "why", "which",
            "is", "are", "do", "does", "did", "can", "should", "tell", "explain",
        }:
            return f"ask:{cleaned}", {}
        return f"say:{cleaned}", {}

    @tool(
        description=(
            "Create a named routine: several things done in one go, like a morning "
            "routine that reads the briefing, the weather and the news."
        ),
        params={
            "name": {"type": "string", "required": True, "description": "Routine name"},
            "steps": {"type": "string", "required": True,
                      "description": "Steps separated by ';', ',' or ' then '"},
        },
        keywords=["create a routine", "make a routine", "define a routine",
                  "morning routine", "evening routine", "set up a routine"],
        examples=['create_routine(name="morning", steps="daily briefing; the weather; the news")'],
    )
    async def create_routine(self, name: str, steps: str) -> ModuleResult:
        """Define or replace a multi-step routine.

        Args:
            name: What to call it.
            steps: The steps, separated by ``;``, ``,`` or ``then``.

        Returns:
            A summary of how each step was interpreted.
        """
        key = " ".join((name or "").strip().lower().split())
        if not key:
            return ModuleResult.fail("What should I call this routine, sir?")
        pieces = self._split_steps(steps or "")
        if not pieces:
            return ModuleResult.fail(
                "A routine needs at least one step, sir. For example: "
                "'the daily briefing; the weather; the news'."
            )

        encoded = json.dumps(pieces, ensure_ascii=False)

        def _save() -> None:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO routines (name, steps, created) VALUES (?, ?, ?) "
                    "ON CONFLICT(name) DO UPDATE SET steps = excluded.steps",
                    (key, encoded, datetime.now().isoformat(timespec="seconds")),
                )

        await run_blocking(_save)
        lines = [f"Routine '{key}' — {len(pieces)} step(s):"]
        for index, piece in enumerate(pieces, 1):
            action, params = self._resolve_action(piece)
            detail = f" {json.dumps(params)}" if params else ""
            lines.append(f"  {index}. {piece}  →  {action}{detail}")
        lines.append(f"Run it with 'run my {key} routine', or schedule it.")
        return ModuleResult(
            success=True,
            output="\n".join(lines),
            speak=f"Saved the {key} routine, sir. {len(pieces)} steps.",
            data={"name": key, "steps": pieces},
        )

    @tool(
        description="Run a named routine now.",
        params={"name": {"type": "string", "required": True, "description": "Routine name"}},
        keywords=["run my routine", "run the routine", "start my routine",
                  "do my morning routine", "do my evening routine"],
    )
    async def run_routine(self, name: str) -> ModuleResult:
        """Execute every step of a routine immediately.

        Args:
            name: The routine to run.

        Returns:
            The combined output of every step.
        """
        key = " ".join((name or "").strip().lower().split())
        steps = await run_blocking(self._read_routine, key)
        if steps is None:
            known = await run_blocking(self._routine_names)
            hint = f" I know: {', '.join(known)}." if known else ""
            return ModuleResult.fail(f"No routine called '{key}', sir.{hint}")
        spoken = await self._perform_routine(key)
        return ModuleResult.ok(spoken, name=key, steps=steps)

    @tool(
        description="List or delete saved routines.",
        params={
            "delete": {"type": "string", "default": "",
                       "description": "Name of a routine to delete"},
        },
        keywords=["list routines", "my routines", "what routines", "delete the routine"],
    )
    async def routines(self, delete: str = "") -> ModuleResult:
        """Show every routine, or remove one.

        Args:
            delete: Name of a routine to delete instead of listing.

        Returns:
            The routine list, or confirmation of the deletion.
        """
        if delete.strip():
            key = " ".join(delete.strip().lower().split())

            def _delete() -> int:
                with self._connect() as connection:
                    cursor = connection.execute(
                        "DELETE FROM routines WHERE name = ?", (key,)
                    )
                    return int(cursor.rowcount or 0)

            removed = await run_blocking(_delete)
            if not removed:
                return ModuleResult.fail(f"No routine called '{key}', sir.")
            return ModuleResult.ok(f"Deleted the '{key}' routine.", deleted=key)

        def _read() -> List[Dict[str, Any]]:
            with self._connect() as connection:
                return [dict(row) for row in connection.execute(
                    "SELECT name, steps FROM routines ORDER BY name"
                ).fetchall()]

        rows = await run_blocking(_read)
        if not rows:
            return ModuleResult.ok(
                "No routines yet, sir. Try: 'create a morning routine that does the "
                "daily briefing, the weather and the news'.",
                routines=[],
            )
        lines = [f"{len(rows)} routine(s):"]
        for row in rows:
            try:
                steps = json.loads(row["steps"])
            except Exception:
                steps = []
            lines.append(f"  {row['name']}: " + " → ".join(str(step) for step in steps))
        return ModuleResult.ok("\n".join(lines), routines=rows)

    @classmethod
    def _split_steps(cls, steps: str) -> List[str]:
        """Split a spoken routine description into individual steps.

        ``;``, ``,`` and ``then`` always separate steps. The word "and" only
        separates them when both halves name something JARVIS can actually do,
        so "the news about pensions and taxes" stays one step while "my todos
        and the weather" becomes two.

        Args:
            steps: The raw phrase.

        Returns:
            The cleaned list of steps.
        """
        rough = [
            piece.strip(" ,.")
            for piece in re.split(r";|\bthen\b|,", steps or "")
            if piece.strip(" ,.")
        ]
        final: List[str] = []
        for piece in rough:
            piece = re.sub(r"^(?:and|also|plus)\s+", "", piece, flags=re.IGNORECASE).strip()
            if piece:
                final.extend(cls._split_on_and(piece))
        return [piece for piece in final if piece]

    @classmethod
    def _split_on_and(cls, piece: str) -> List[str]:
        """Split one phrase on "and", but only between recognisable actions.

        Args:
            piece: A single candidate step.

        Returns:
            One or more steps.
        """
        for match in re.finditer(r"\s+and\s+", piece, flags=re.IGNORECASE):
            left = piece[: match.start()].strip()
            right = piece[match.end():].strip()
            if not left or not right:
                continue
            if cls._resolve_action(left)[0].startswith("say:"):
                continue
            right_parts = cls._split_on_and(right)
            if not cls._resolve_action(right_parts[0])[0].startswith("say:"):
                return [left, *right_parts]
        return [piece]

    def _routine_names(self) -> List[str]:
        """Return every saved routine name."""
        try:
            with self._connect() as connection:
                return [row["name"] for row in connection.execute(
                    "SELECT name FROM routines ORDER BY name"
                ).fetchall()]
        except Exception:
            return []

    @tool(
        description="List everything on the recurring schedule.",
        params={},
        keywords=["list schedules", "what is scheduled", "my schedule",
                  "recurring jobs", "what do you run automatically"],
    )
    async def list_schedules(self) -> ModuleResult:
        """Show every recurring job with its next run time."""
        def _read() -> List[Dict[str, Any]]:
            with self._connect() as connection:
                return [dict(row) for row in connection.execute(
                    "SELECT * FROM schedules ORDER BY enabled DESC, next_run"
                ).fetchall()]

        rows = await run_blocking(_read)
        if not rows:
            return ModuleResult.ok(
                "Nothing is scheduled, sir. Try: 'every weekday at 8am, give me my "
                "daily briefing'.",
                schedules=[],
            )
        lines = [f"{len(rows)} scheduled job(s):"]
        for row in rows:
            rule = parse_schedule(row["rule"])
            when = rule.describe() if rule else row["rule"]
            state = "" if row["enabled"] else "  [paused]"
            try:
                nxt = datetime.fromisoformat(row["next_run"])
                next_text = f"{nxt:%a %d %b %H:%M}"
            except Exception:
                next_text = row["next_run"]
            lines.append(
                f"  #{row['id']:<3} {truncate(row['description'], 40):42} {when:26} "
                f"next {next_text}{state}"
            )
        return ModuleResult.ok("\n".join(lines), schedules=rows)

    @tool(
        description="Cancel or pause a scheduled job.",
        params={
            "job_id": {"type": "integer", "description": "Job number", "default": 0},
            "description": {"type": "string", "description": "…or match on its text",
                            "default": ""},
            "pause": {"type": "boolean", "description": "Pause instead of deleting",
                      "default": False},
        },
        keywords=["cancel the schedule", "stop the daily", "unschedule",
                  "pause the schedule", "delete the schedule"],
    )
    async def cancel_schedule(self, job_id: int = 0, description: str = "",
                              pause: bool = False) -> ModuleResult:
        """Remove or pause a recurring job.

        Args:
            job_id: The job number from :meth:`list_schedules`.
            description: Alternative match on the job's text.
            pause: Keep the job but stop it running.

        Returns:
            Confirmation of what changed.
        """
        def _apply() -> Optional[Dict[str, Any]]:
            with self._connect() as connection:
                row = None
                if job_id:
                    row = connection.execute(
                        "SELECT * FROM schedules WHERE id = ?", (int(job_id),)
                    ).fetchone()
                elif description.strip():
                    row = connection.execute(
                        "SELECT * FROM schedules WHERE description LIKE ? ORDER BY id DESC",
                        (f"%{description.strip()}%",),
                    ).fetchone()
                if row is None:
                    return None
                if pause:
                    connection.execute(
                        "UPDATE schedules SET enabled = 0 WHERE id = ?", (row["id"],)
                    )
                else:
                    connection.execute("DELETE FROM schedules WHERE id = ?", (row["id"],))
                return dict(row)

        row = await run_blocking(_apply)
        if row is None:
            return ModuleResult.fail("I could not find that scheduled job, sir.")
        verb = "Paused" if pause else "Cancelled"
        return ModuleResult.ok(
            f"{verb} #{row['id']}: {row['description']}.", id=row["id"], paused=pause
        )

    def _pop_due_reminders(self) -> List[Dict[str, Any]]:
        """Mark due reminders as fired and return them."""
        rows: List[Dict[str, Any]] = []
        try:
            now = datetime.now().isoformat(timespec="seconds")
            with self._connect() as connection:
                cursor = connection.execute(
                    "SELECT id, text, due, repeat FROM reminders WHERE fired = 0 AND due <= ?",
                    (now,),
                )
                rows = [dict(row) for row in cursor.fetchall()]
                for row in rows:
                    if row.get("repeat"):
                        seconds = parse_duration(row["repeat"]) or 86400
                        next_due = (datetime.now() + timedelta(seconds=seconds)).isoformat(
                            timespec="seconds"
                        )
                        connection.execute(
                            "UPDATE reminders SET due = ? WHERE id = ?", (next_due, row["id"])
                        )
                    else:
                        connection.execute(
                            "UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],)
                        )
        except Exception as exc:
            self.log.debug("Reminder poll failed: %s", exc)
        return rows

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing with parameter extraction (used without an LLM)."""
        text = strip_command_prefix(command)
        lowered = text.lower()

        # -- recurring schedules (before reminders: "remind me every day…") ---
        if any(phrase in lowered for phrase in
               ("list schedules", "my schedules", "what is scheduled", "what's scheduled",
                "scheduled jobs", "recurring jobs", "show my schedule")):
            return "list_schedules", {}
        if any(phrase in lowered for phrase in
               ("cancel the schedule", "cancel schedule", "unschedule", "stop the schedule",
                "pause the schedule", "delete the schedule", "cancel the recurring")):
            number = re.search(r"#?(\d+)", lowered)
            return "cancel_schedule", {
                "job_id": int(number.group(1)) if number else 0,
                "description": "" if number else re.sub(
                    r".*(?:schedule[d]?|recurring)\s*", "", lowered).strip(),
                "pause": "pause" in lowered,
            }
        day_word = r"(?:mon|tues|wednes|thurs|fri|satur|sun)day"
        recurring = re.search(
            r"\b((?:every\s+(?:day|morning|afternoon|evening|night|weekday|weekends?|"
            r"hour|\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?)|"
            + day_word + r"(?:\s*(?:,|and)\s*" + day_word + r")*)"
            r"|hourly|daily|each\s+(?:day|morning|evening|weekday))"
            r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?)",
            lowered,
        )
        defining_routine = re.search(
            r"\b(?:create|make|define|set up|save)\s+(?:a|an|my|the)?\s*[\w -]*routine\b",
            lowered,
        )
        if recurring:
            # "give me my daily briefing" asks for a briefing now — it is not a
            # standing order. A bare "daily"/"hourly" only means a schedule if
            # something else in the sentence actually asks for one.
            bare = recurring.group(1).strip() in ("daily", "hourly")
            asks = any(word in lowered for word in
                       ("schedule", "remind", "every", "each", "from now on"))
            if bare and not asks:
                recurring = None

        if recurring and not defining_routine and parse_schedule(recurring.group(1)) is not None:
            when = recurring.group(1).strip()
            rest = (text[: recurring.start(1)] + " " + text[recurring.end(1):]).strip(" ,.")
            rest = re.sub(
                r"^(?:please\s+)?(?:can you\s+|could you\s+)?"
                r"(?:remind me|schedule|set up|give me|tell me|run|do)\s+(?:me\s+)?(?:to\s+)?",
                "", rest.strip(), flags=re.IGNORECASE,
            ).strip(" ,.")
            return "schedule_recurring", {"when": when, "what": rest or "check in"}

        # -- routines ---------------------------------------------------------
        routine_create = re.search(
            r"\b(?:create|make|define|set up|save)\s+(?:a|an|my|the)?\s*([\w -]+?)\s+routine"
            r"(?:\s+(?:that|which|to|doing|with|:)\s*)?(.*)$", lowered,
        )
        if routine_create and routine_create.group(2).strip():
            body = text[len(text) - len(routine_create.group(2)):].strip()
            body = re.sub(r"^(?:that|which)?\s*(?:does|do|runs|run|is)?\s*[:,]?\s*", "",
                          body, flags=re.IGNORECASE).strip()
            return "create_routine", {"name": routine_create.group(1).strip(),
                                      "steps": body or routine_create.group(2).strip()}
        if any(phrase in lowered for phrase in
               ("list routines", "list my routines", "my routines", "what routines")):
            return "routines", {}
        routine_delete = re.search(r"\bdelete\s+(?:the\s+|my\s+)?([\w -]+?)\s+routine", lowered)
        if routine_delete:
            return "routines", {"delete": routine_delete.group(1).strip()}
        routine_run = re.search(
            r"\b(?:run|start|do|execute)\s+(?:the\s+|my\s+)?([\w -]+?)\s+routine", lowered)
        if routine_run:
            return "run_routine", {"name": routine_run.group(1).strip()}

        # -- reminders -------------------------------------------------------
        reminder = re.search(
            r"\bremind\s+(?:me\s+)?(?:to\s+|that\s+|about\s+)?(.+)", lowered
        )
        if reminder or "reminder" in lowered:
            body = reminder.group(1) if reminder else lowered
            when_match = re.search(
                r"\b(in\s+.+|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?.*|tomorrow.*|tonight.*)$", body
            )
            when = when_match.group(1).strip() if when_match else ""
            what = body[: when_match.start()].strip(" ,") if when_match else body.strip()
            if when:
                return "add_reminder", {"text": what or body, "when": when}
            return "list_reminders", {}

        # -- timers ----------------------------------------------------------
        if "timer" in lowered or "countdown" in lowered or "alarm in" in lowered:
            if any(word in lowered for word in ("cancel", "stop", "kill")):
                return "cancel_timer", {"timer": "all"}
            if any(word in lowered for word in ("list", "running", "left", "remaining", "check")):
                return "list_timers", {}
            duration = re.search(
                r"(?:for|of|in)?\s*([\d.]+\s*"
                r"(?:hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b|\d+)", lowered)
            label = re.search(r"\bcalled\s+([\w -]+)", lowered)
            return "start_timer", {
                "duration": duration.group(1).strip() if duration else lowered,
                "label": label.group(1).strip() if label else "",
            }

        if "stopwatch" in lowered or "stop watch" in lowered:
            # The noun "stopwatch" contains "stop", so a naive substring test
            # turned "start a stopwatch" into a stop request. Decide the verb
            # from what is left once the noun is removed.
            rest = lowered.replace("stopwatch", " ").replace("stop watch", " ")
            action = (
                "stop" if re.search(r"\b(stop|end|finish|reset|halt)\b", rest) else
                "lap" if "lap" in rest else
                "check" if re.search(r"\b(check|how long|status|elapsed|so far)\b", rest)
                else "start"
            )
            return "stopwatch", {"action": action}

        # -- notes -----------------------------------------------------------
        note = re.search(r"\b(?:take a note|note that|note:|write down|jot down)\s*[:,]?\s*(.+)",
                         lowered)
        if note:
            index = lowered.index(note.group(1))
            return "add_note", {"content": text[index:].strip()}
        if "note" in lowered and any(w in lowered for w in
                                     ("find", "search", "show", "my", "what")):
            keyword = re.sub(r".*notes?\s*(about|on|for|containing)?\s*", "", lowered).strip()
            return "search_notes", {"query": keyword}

        # -- briefing --------------------------------------------------------
        if any(phrase in lowered for phrase in ("briefing", "brief me", "my day", "agenda")):
            return "daily_briefing", {}

        # -- todos -----------------------------------------------------------
        completion = re.search(
            r"\b(?:mark|tick|cross)\s+(?:off\s+)?(.+?)\s*(?:as\s+)?(?:done|complete[d]?|off)?$",
            lowered,
        )
        if completion and any(word in lowered for word in
                              ("done with", "completed", "finished", "mark ")):
            return "complete_todo", {"task": completion.group(1).strip()}

        if any(word in lowered for word in ("delete", "remove", "scrap")) and (
            "task" in lowered or "todo" in lowered
        ):
            target = re.sub(r".*(?:task|todo)s?\s*", "", lowered).strip() or lowered
            return "delete_todo", {"task": target}

        add_task = re.search(
            r"\b(?:add|put|append)\s+(.+?)\s+(?:to|on|onto|in)\s+(?:my\s+)?(?:to-?do|task)",
            lowered,
        )
        if add_task:
            start = lowered.index(add_task.group(1))
            task_text = text[start : start + len(add_task.group(1))].strip()
            urgent = any(w in lowered for w in ("urgent", "important", "asap"))
            priority = "high" if urgent else "normal"
            return "add_todo", {"task": task_text, "priority": priority}

        if re.search(r"\b(?:add|new)\s+(?:a\s+)?(?:task|todo)\b", lowered):
            task_text = re.sub(r".*\b(?:task|todo)\b\s*[:,]?\s*", "", text, flags=re.IGNORECASE)
            if task_text.strip():
                return "add_todo", {"task": task_text.strip()}

        if any(phrase in lowered for phrase in
               ("my todo", "todo list", "my tasks", "what tasks", "what's on my list",
                "show tasks", "list tasks")):
            return "list_todos", {}

        return None

    # ------------------------------------------------------------------ todos
    @tool(
        description="Add a task to the todo list.",
        params={
            "task": {"type": "string", "description": "The task", "required": True},
            "priority": {"type": "string", "description": "low/normal/high", "default": "normal"},
            "due": {"type": "string", "description": "Optional due date/time", "default": ""},
            "tags": {"type": "string", "description": "Comma separated tags", "default": ""},
        },
        keywords=["add task", "add todo", "to do", "put on my list", "new task", "remember to buy"],
        examples=['add_todo(task="buy milk", priority="high")'],
    )
    async def add_todo(
        self, task: str, priority: str = "normal", due: str = "", tags: str = ""
    ) -> ModuleResult:
        """Insert a task into the todo table."""
        text = (task or "").strip()
        if not text:
            return ModuleResult.fail("What task should I add?")
        due_iso = ""
        if due:
            parsed = parse_when(due)
            due_iso = parsed.isoformat(timespec="minutes") if parsed else str(due)

        def _insert() -> int:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO todos (task, priority, due, tags, created)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (
                        text,
                        str(priority or "normal").lower(),
                        due_iso,
                        str(tags or ""),
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                return int(cursor.lastrowid or 0)

        task_id = await run_blocking(_insert)
        suffix = f" (due {due_iso})" if due_iso else ""
        return ModuleResult.ok(f"Added task #{task_id}: {text}{suffix}", id=task_id)

    @tool(
        description="List todo items.",
        params={
            "show_done": {"type": "boolean", "description": "Include completed", "default": False},
            "limit": {"type": "integer", "description": "Max items", "default": 20},
        },
        keywords=["my todos", "todo list", "what are my tasks", "show tasks", "what's on my list"],
    )
    async def list_todos(self, show_done: bool = False, limit: int = 20) -> ModuleResult:
        """Return outstanding (or all) tasks."""

        def _select() -> List[Dict[str, Any]]:
            query = (
                "SELECT id, task, priority, due, done FROM todos"
                + ("" if show_done else " WHERE done = 0")
                + " ORDER BY done ASC,"
                " CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,"
                " id DESC LIMIT ?"
            )
            with self._connect() as connection:
                return [dict(row) for row in connection.execute(query, (int(limit),)).fetchall()]

        rows = await run_blocking(_select)
        if not rows:
            return ModuleResult(
                success=True,
                output="Your todo list is empty. Suspiciously so.",
                data={"todos": []},
            )
        lines = []
        for row in rows:
            mark = "✓" if row["done"] else "•"
            flag = " [high]" if row["priority"] == "high" else ""
            due = f" (due {row['due']})" if row["due"] else ""
            lines.append(f"{mark} #{row['id']} {row['task']}{flag}{due}")
        open_count = sum(1 for row in rows if not row["done"])
        return ModuleResult(
            success=True,
            output="\n".join(lines),
            speak=f"You have {open_count} open task{'s' if open_count != 1 else ''}: "
            + "; ".join(row["task"] for row in rows[:5] if not row["done"]),
            data={"todos": rows},
        )

    @tool(
        description="Mark a todo item as done (by id or by matching text).",
        params={"task": {"type": "string", "description": "Task id or text", "required": True}},
        keywords=["mark done", "complete task", "finished", "tick off", "cross off", "done with"],
    )
    async def complete_todo(self, task: str) -> ModuleResult:
        """Complete a task by id or fuzzy text match."""
        needle = str(task or "").strip()
        if not needle:
            return ModuleResult.fail("Which task?")

        def _complete() -> Optional[Dict[str, Any]]:
            with self._connect() as connection:
                row = None
                if needle.lstrip("#").isdigit():
                    row = connection.execute(
                        "SELECT id, task FROM todos WHERE id = ? AND done = 0",
                        (int(needle.lstrip("#")),),
                    ).fetchone()
                if row is None:
                    row = connection.execute(
                        "SELECT id, task FROM todos WHERE done = 0 AND task LIKE ?"
                        " ORDER BY id DESC LIMIT 1",
                        (f"%{needle}%",),
                    ).fetchone()
                if row is None:
                    return None
                connection.execute(
                    "UPDATE todos SET done = 1, completed = ? WHERE id = ?",
                    (datetime.now().isoformat(timespec="seconds"), row["id"]),
                )
                return dict(row)

        row = await run_blocking(_complete)
        if row is None:
            return ModuleResult.fail(f"No open task matching '{needle}'.")
        return ModuleResult.ok(f"Marked '{row['task']}' as done.", id=row["id"])

    @tool(
        description="Delete a todo item permanently.",
        params={"task": {"type": "string", "description": "Task id or text", "required": True}},
        keywords=["delete task", "remove todo", "scrap that task"],
    )
    async def delete_todo(self, task: str) -> ModuleResult:
        """Remove a task from the list."""
        needle = str(task or "").strip()

        def _delete() -> int:
            with self._connect() as connection:
                if needle.lstrip("#").isdigit():
                    cursor = connection.execute(
                        "DELETE FROM todos WHERE id = ?", (int(needle.lstrip("#")),)
                    )
                else:
                    cursor = connection.execute(
                        "DELETE FROM todos WHERE task LIKE ?", (f"%{needle}%",)
                    )
                return cursor.rowcount or 0

        removed = await run_blocking(_delete)
        if not removed:
            return ModuleResult.fail(f"Nothing matched '{needle}'.")
        return ModuleResult.ok(f"Deleted {removed} task(s).")

    # -------------------------------------------------------------- reminders
    @tool(
        description="Create a reminder that fires at a given time.",
        params={
            "text": {"type": "string", "description": "What to be reminded of", "required": True},
            "when": {
                "type": "string",
                "description": "e.g. 'in 20 minutes', 'at 5pm', 'tomorrow at 09:00'",
                "required": True,
            },
            "repeat": {
                "type": "string",
                "description": "Optional repeat interval like '1 day'",
                "default": "",
            },
        },
        keywords=["remind me", "reminder", "don't let me forget", "alert me", "wake me"],
        examples=['add_reminder(text="call mom", when="at 5pm")'],
    )
    async def add_reminder(self, text: str, when: str, repeat: str = "") -> ModuleResult:
        """Schedule a reminder."""
        body = (text or "").strip()
        if not body:
            return ModuleResult.fail("What should I remind you about?")
        target = parse_when(when)
        if target is None:
            seconds = parse_duration(when)
            target = datetime.now() + timedelta(seconds=seconds) if seconds else None
        if target is None:
            return ModuleResult.fail(
                f"I couldn't work out when '{when}' is. Try 'in 20 minutes' or 'at 5pm'."
            )

        def _insert() -> int:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO reminders (text, due, created, repeat) VALUES (?, ?, ?, ?)",
                    (
                        body,
                        target.isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds"),
                        str(repeat or ""),
                    ),
                )
                return int(cursor.lastrowid or 0)

        reminder_id = await run_blocking(_insert)
        delta = human_duration((target - datetime.now()).total_seconds())
        return ModuleResult(
            success=True,
            output=f"Reminder #{reminder_id} set for {target:%A %H:%M} (in {delta}): {body}",
            speak=f"I'll remind you to {body} in {delta}.",
            data={"id": reminder_id, "due": target.isoformat(timespec="seconds")},
        )

    @tool(
        description="List upcoming reminders.",
        params={"limit": {"type": "integer", "description": "Max items", "default": 10}},
        keywords=["my reminders", "what reminders", "upcoming reminders"],
    )
    async def list_reminders(self, limit: int = 10) -> ModuleResult:
        """Show reminders that have not fired yet."""

        def _select() -> List[Dict[str, Any]]:
            with self._connect() as connection:
                return [
                    dict(row)
                    for row in connection.execute(
                        "SELECT id, text, due FROM reminders WHERE fired = 0"
                        " ORDER BY due ASC LIMIT ?",
                        (int(limit),),
                    ).fetchall()
                ]

        rows = await run_blocking(_select)
        if not rows:
            return ModuleResult(success=True, output="No pending reminders.",
                                data={"reminders": []})
        lines = [f"#{row['id']} {row['due']} — {row['text']}" for row in rows]
        return ModuleResult(success=True, output="\n".join(lines), data={"reminders": rows})

    @tool(
        description="Cancel a reminder by id or text.",
        params={"reminder": {"type": "string", "description": "Id or text", "required": True}},
        keywords=["cancel reminder", "delete reminder", "forget the reminder"],
    )
    async def cancel_reminder(self, reminder: str) -> ModuleResult:
        """Delete a pending reminder."""
        needle = str(reminder or "").strip()

        def _delete() -> int:
            with self._connect() as connection:
                if needle.lstrip("#").isdigit():
                    cursor = connection.execute(
                        "DELETE FROM reminders WHERE id = ?", (int(needle.lstrip("#")),)
                    )
                else:
                    cursor = connection.execute(
                        "DELETE FROM reminders WHERE text LIKE ?", (f"%{needle}%",)
                    )
                return cursor.rowcount or 0

        removed = await run_blocking(_delete)
        return (
            ModuleResult.ok(f"Cancelled {removed} reminder(s).")
            if removed
            else ModuleResult.fail(f"No reminder matched '{needle}'.")
        )

    # ----------------------------------------------------------------- timers
    @tool(
        description="Start a countdown timer.",
        params={
            "duration": {
                "type": "string",
                "description": "e.g. '10 minutes', '90s', '1h30m'",
                "required": True,
            },
            "label": {"type": "string", "description": "Optional timer name", "default": ""},
        },
        keywords=["set a timer", "timer for", "countdown", "alarm in", "ping me in"],
        examples=['start_timer(duration="10 minutes", label="pasta")'],
    )
    async def start_timer(self, duration: str, label: str = "") -> ModuleResult:
        """Start an asynchronous countdown that announces when it finishes."""
        seconds = parse_duration(str(duration))
        if not seconds or seconds <= 0:
            return ModuleResult.fail(
                f"'{duration}' isn't a duration I understand. Try '10 minutes'."
            )
        if seconds > 86400:
            return ModuleResult.fail("Timers are capped at 24 hours. Use a reminder instead.")

        name = (label or "").strip() or f"timer-{len(self.timers) + 1}"
        timer_id = uuid.uuid4().hex[:6]

        async def _run() -> None:
            try:
                await asyncio.sleep(seconds)
                await self._announce(
                    f"Your {name} timer is up — {human_duration(seconds)} elapsed."
                )
            except asyncio.CancelledError:
                pass
            finally:
                self.timers.pop(timer_id, None)

        task = asyncio.create_task(_run())
        self.timers[timer_id] = {
            "label": name,
            "seconds": seconds,
            "ends_at": time.time() + seconds,
            "task": task,
        }
        return ModuleResult(
            success=True,
            output=f"Timer '{name}' started for {human_duration(seconds)} (id {timer_id}).",
            speak=f"Timer set for {human_duration(seconds)}.",
            data={"id": timer_id, "seconds": seconds},
        )

    @tool(
        description="List running timers and their remaining time.",
        params={},
        keywords=["timers running", "how long left", "check timer", "time remaining"],
    )
    async def list_timers(self) -> ModuleResult:
        """Show every active timer."""
        if not self.timers:
            return ModuleResult(success=True, output="No timers running.", data={"timers": []})
        rows = []
        for timer_id, entry in self.timers.items():
            remaining = max(0, entry["ends_at"] - time.time())
            rows.append(f"{entry['label']} ({timer_id}): {human_duration(remaining)} remaining")
        return ModuleResult(success=True, output="\n".join(rows), data={"timers": rows})

    @tool(
        description="Cancel a running timer by id or label ('all' cancels everything).",
        params={"timer": {"type": "string", "description": "Timer id or label", "required": True}},
        keywords=["cancel timer", "stop timer", "kill the timer"],
    )
    async def cancel_timer(self, timer: str = "") -> ModuleResult:
        """Cancel one or all timers.

        Args:
            timer: The timer id or label. Left empty it cancels the only
                running timer, because "cancel the timer" is how people
                actually say it; with several running it asks which one.

        Returns:
            A :class:`ModuleResult` naming what was cancelled.
        """
        needle = str(timer or "").strip().lower()
        if not needle:
            if not self.timers:
                return ModuleResult.fail("There are no timers running, sir.")
            if len(self.timers) == 1:
                timer_id, entry = next(iter(self.timers.items()))
                entry["task"].cancel()
                self.timers.pop(timer_id, None)
                return ModuleResult.ok(f"Cancelled timer '{entry['label']}'.")
            labels = ", ".join(entry["label"] for entry in self.timers.values())
            return ModuleResult.fail(
                f"You have {len(self.timers)} timers running ({labels}). Which one?"
            )
        if needle in {"all", "everything", "*"}:
            count = len(self.timers)
            for entry in list(self.timers.values()):
                entry["task"].cancel()
            self.timers.clear()
            return ModuleResult.ok(f"Cancelled {count} timer(s).")
        for timer_id, entry in list(self.timers.items()):
            if needle in (timer_id.lower(), entry["label"].lower()):
                entry["task"].cancel()
                self.timers.pop(timer_id, None)
                return ModuleResult.ok(f"Cancelled timer '{entry['label']}'.")
        return ModuleResult.fail(f"No timer named '{timer}'.")

    @tool(
        description="Control the stopwatch: start, stop, lap or check.",
        params={
            "action": {"type": "string", "description": "start/stop/lap/check", "default": "start"},
            "name": {"type": "string", "description": "Stopwatch name", "default": "default"},
        },
        keywords=["stopwatch", "start timing", "how long has it been", "lap"],
    )
    async def stopwatch(self, action: str = "start", name: str = "default") -> ModuleResult:
        """Start/stop/lap a named stopwatch."""
        verb = str(action or "start").lower()
        key = str(name or "default")
        watch = self.stopwatches.get(key)

        if verb.startswith("start"):
            self.stopwatches[key] = {"start": time.time(), "laps": []}
            return ModuleResult.ok(f"Stopwatch '{key}' running.")
        if watch is None:
            return ModuleResult.fail(f"No stopwatch named '{key}' is running.")

        elapsed = time.time() - watch["start"]
        if verb.startswith("lap"):
            watch["laps"].append(elapsed)
            return ModuleResult.ok(
                f"Lap {len(watch['laps'])}: {human_duration(elapsed)} total.",
                laps=watch["laps"],
            )
        if verb.startswith("stop"):
            self.stopwatches.pop(key, None)
            laps = ", ".join(human_duration(lap) for lap in watch["laps"]) or "none"
            return ModuleResult.ok(
                f"Stopwatch '{key}' stopped at {human_duration(elapsed)}. Laps: {laps}."
            )
        return ModuleResult.ok(f"Stopwatch '{key}' is at {human_duration(elapsed)}.")

    # ------------------------------------------------------------------ notes
    @tool(
        description="Save a note (stored in SQLite and as a markdown file).",
        params={
            "content": {"type": "string", "description": "Note body", "required": True},
            "title": {"type": "string", "description": "Optional title", "default": ""},
            "tags": {"type": "string", "description": "Comma separated tags", "default": ""},
        },
        keywords=["take a note", "note that", "write down", "jot down", "save this note"],
    )
    async def add_note(self, content: str, title: str = "", tags: str = "") -> ModuleResult:
        """Persist a note."""
        body = (content or "").strip()
        if not body:
            return ModuleResult.fail("The note is empty, sir.")
        heading = (title or "").strip() or truncate(body.split("\n")[0], 60)
        stamp = datetime.now().isoformat(timespec="seconds")

        def _insert() -> int:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO notes (title, body, tags, created, updated)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (heading, body, str(tags or ""), stamp, stamp),
                )
                return int(cursor.lastrowid or 0)

        note_id = await run_blocking(_insert)

        path = self.notes_dir / safe_filename(
            f"{datetime.now():%Y%m%d}-{slugify(heading)}", ".md"
        )
        try:
            ensure_dir(self.notes_dir)
            path.write_text(f"# {heading}\n\n_{stamp}_\n\n{body}\n", encoding="utf-8")
        except Exception as exc:
            self.log.debug("Could not write note file: %s", exc)

        return ModuleResult.ok(f"Note #{note_id} saved: {heading}", id=note_id, path=str(path))

    @tool(
        description="Search saved notes by keyword.",
        params={
            "query": {"type": "string", "description": "Keyword", "default": ""},
            "limit": {"type": "integer", "description": "Max notes", "default": 10},
        },
        keywords=["find note", "search notes", "my notes", "what did i note", "show notes"],
    )
    async def search_notes(self, query: str = "", limit: int = 10) -> ModuleResult:
        """Full-text-ish search across notes."""

        def _select() -> List[Dict[str, Any]]:
            with self._connect() as connection:
                if query:
                    rows = connection.execute(
                        "SELECT id, title, body, created FROM notes"
                        " WHERE title LIKE ? OR body LIKE ? OR tags LIKE ?"
                        " ORDER BY id DESC LIMIT ?",
                        (f"%{query}%", f"%{query}%", f"%{query}%", int(limit)),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        "SELECT id, title, body, created FROM notes ORDER BY id DESC LIMIT ?",
                        (int(limit),),
                    ).fetchall()
                return [dict(row) for row in rows]

        rows = await run_blocking(_select)
        if not rows:
            return ModuleResult(
                success=True,
                output=f"No notes matching '{query}'." if query else "You have no notes yet.",
                data={"notes": []},
            )
        lines = [
            f"#{row['id']} [{row['created'][:10]}] {row['title']}: {truncate(row['body'], 160)}"
            for row in rows
        ]
        return ModuleResult(success=True, output="\n".join(lines), data={"notes": rows})

    @tool(
        description="Delete a note by id.",
        params={"note_id": {"type": "integer", "description": "Note id", "required": True}},
        keywords=["delete note", "remove note"],
    )
    async def delete_note(self, note_id: int) -> ModuleResult:
        """Remove a note from the database."""

        def _delete() -> int:
            with self._connect() as connection:
                cursor = connection.execute("DELETE FROM notes WHERE id = ?", (int(note_id),))
                return cursor.rowcount or 0

        removed = await run_blocking(_delete)
        return (
            ModuleResult.ok(f"Note #{note_id} deleted.")
            if removed
            else ModuleResult.fail(f"No note with id {note_id}.")
        )

    # --------------------------------------------------------------- briefing
    @tool(
        description="Give the daily briefing: time, weather, tasks, reminders and headlines.",
        params={},
        keywords=["daily briefing", "brief me", "morning briefing", "what's on today",
                  "status of my day", "agenda", "my day", "how does my day look"],
    )
    async def daily_briefing(self) -> ModuleResult:
        """Assemble the morning briefing from every available source."""
        now = datetime.now()
        parts: List[str] = [f"It's {now:%A %d %B}, {now:%H:%M}."]

        # Weather (optional dependency on the web module).
        if self.config.get("modules.web_search", True):
            try:
                from modules.web_search import WebSearch

                web = WebSearch(self.config, llm=self.llm, security=self.security)
                weather = await web.weather()
                if weather.success:
                    parts.append(weather.speak or weather.output.split("\n")[0])
            except Exception as exc:
                self.log.debug("Briefing weather failed: %s", exc)

        todos = await self.list_todos(limit=5)
        open_tasks = [row for row in todos.data.get("todos", []) if not row.get("done")]
        if open_tasks:
            listed = "; ".join(row["task"] for row in open_tasks[:5])
            parts.append(f"You have {len(open_tasks)} open task(s): {listed}.")
        else:
            parts.append("No outstanding tasks.")

        # Calendar (optional dependency on the communications module).
        if self.config.get("modules.communications", True) and self.config.get(
            "calendar.enabled", True
        ):
            try:
                from modules.communications import Communications

                comms = Communications(self.config, llm=self.llm, security=self.security)
                agenda = await comms.upcoming_events(days=1)
                events = agenda.data.get("events", []) if agenda.success else []
                if events:
                    listed = "; ".join(
                        f"{item['summary']} at {item['start'][11:16]}" for item in events[:4]
                    )
                    parts.append(f"{len(events)} event(s) today: {listed}.")
            except Exception as exc:
                self.log.debug("Briefing calendar failed: %s", exc)

        # Unread mail count, when email is configured.
        if self.config.get("modules.communications", True) and self.config.get(
            "email.enabled", False
        ):
            try:
                from modules.communications import Communications

                mailer = Communications(self.config, llm=self.llm, security=self.security)
                inbox = await mailer.check_email(unread_only=True, limit=5)
                unread = inbox.data.get("messages", []) if inbox.success else []
                if unread:
                    parts.append(
                        f"{len(unread)} unread email(s), the latest from "
                        f"{unread[0]['from'].split('<')[0].strip()}."
                    )
            except Exception as exc:
                self.log.debug("Briefing email failed: %s", exc)

        reminders = await self.list_reminders(limit=3)
        pending = reminders.data.get("reminders", [])
        if pending:
            parts.append(
                "Upcoming reminders: "
                + "; ".join(f"{row['text']} at {row['due'][11:16]}" for row in pending)
                + "."
            )

        if self.config.get("modules.web_search", True):
            try:
                from modules.web_search import WebSearch

                web = WebSearch(self.config, llm=self.llm, security=self.security)
                news = await web.news(limit=3)
                if news.success:
                    headlines = news.data.get("headlines", [])
                    if headlines:
                        parts.append(
                            "In the news: "
                            + "; ".join(item["title"] for item in headlines[:3])
                            + "."
                        )
            except Exception as exc:
                self.log.debug("Briefing news failed: %s", exc)

        text = " ".join(parts)
        return ModuleResult(success=True, output=text, speak=text, data={"parts": parts})


__all__ = ["Productivity"]

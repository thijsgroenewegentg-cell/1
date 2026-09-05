# /modules/productivity.py
"""Todos, reminders, timers, notes and the daily briefing — all SQLite backed."""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import (
    IS_MACOS,
    IS_WINDOWS,
    ensure_dir,
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
CREATE INDEX IF NOT EXISTS idx_todos_done ON todos(done);
CREATE INDEX IF NOT EXISTS idx_reminders_fired ON reminders(fired);
"""


class Productivity(BaseModule):
    """Personal organisation: tasks, reminders, timers, notes, briefings."""

    name = "productivity"
    description = (
        "Personal productivity: todo list, reminders with notifications, timers and a "
        "stopwatch, note taking with search, and a daily briefing."
    )
    intent_examples = [
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
        self._scheduler_task: Optional[asyncio.Task] = None
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
        """Start the background reminder scheduler."""
        if self._scheduler_task is None or self._scheduler_task.done():
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())

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

    async def _scheduler_loop(self) -> None:
        """Poll for due reminders every 15 seconds."""
        self.log.debug("Reminder scheduler started.")
        while True:
            try:
                await asyncio.sleep(15)
                due = await run_blocking(self._pop_due_reminders)
                for row in due:
                    await self._announce(f"Reminder: {row['text']}")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.log.debug("Scheduler hiccup: %s", exc)

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
            duration = re.search(r"(?:for|of|in)?\s*([\d.]+\s*(?:hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b|\d+)", lowered)
            label = re.search(r"\bcalled\s+([\w -]+)", lowered)
            return "start_timer", {
                "duration": duration.group(1).strip() if duration else lowered,
                "label": label.group(1).strip() if label else "",
            }

        if "stopwatch" in lowered:
            action = (
                "stop" if "stop" in lowered else
                "lap" if "lap" in lowered else
                "check" if any(w in lowered for w in ("check", "how long")) else
                "start"
            )
            return "stopwatch", {"action": action}

        # -- notes -----------------------------------------------------------
        note = re.search(r"\b(?:take a note|note that|note:|write down|jot down)\s*[:,]?\s*(.+)",
                         lowered)
        if note:
            index = lowered.index(note.group(1))
            return "add_note", {"content": text[index:].strip()}
        if "note" in lowered and any(w in lowered for w in ("find", "search", "show", "my", "what")):
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
        if any(word in lowered for word in ("done with", "completed", "finished", "mark ")) and completion:
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
            priority = "high" if any(w in lowered for w in ("urgent", "important", "asap")) else "normal"
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
            return ModuleResult(success=True, output="No pending reminders.", data={"reminders": []})
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
    async def cancel_timer(self, timer: str) -> ModuleResult:
        """Cancel one or all timers."""
        needle = str(timer or "").strip().lower()
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
                  "status of my day", "agenda"],
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

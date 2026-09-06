# /utils/scheduler.py
"""Scheduling that prefers APScheduler and works fine without it.

JARVIS has to fire reminders, run recurring jobs and poll for overdue work on
a machine that may not have APScheduler installed — the installer's minimal
profile skips it. So this wrapper offers one API with two engines behind it:

* **APScheduler** (``AsyncIOScheduler``) when it imports — proper cron and
  interval triggers, misfire grace, job introspection.
* **A built-in asyncio fallback** otherwise — the same three trigger types,
  implemented with ``asyncio.sleep`` loops, so behaviour does not change.

:meth:`Scheduler.engine` tells you which one is in use, and ``--doctor``
reports it.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from utils.logger import get_logger

logger = get_logger("utils.scheduler")

JobFunc = Callable[[], Union[Awaitable[None], None]]

try:  # pragma: no cover - depends on what is installed
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    HAS_APSCHEDULER = True
except Exception:  # pragma: no cover - the fallback is the tested path here
    HAS_APSCHEDULER = False
    AsyncIOScheduler = None  # type: ignore[misc, assignment]
    CronTrigger = None  # type: ignore[misc, assignment]
    DateTrigger = None  # type: ignore[misc, assignment]
    IntervalTrigger = None  # type: ignore[misc, assignment]


@dataclass
class JobInfo:
    """What the scheduler knows about one job.

    Attributes:
        id: Unique job identifier.
        name: Human-readable description.
        kind: ``interval``, ``cron`` or ``date``.
        next_run: When it fires next, if known.
        paused: Whether it is currently suspended.
        runs: How many times it has fired.
    """

    id: str
    name: str = ""
    kind: str = "interval"
    next_run: Optional[datetime] = None
    paused: bool = False
    runs: int = 0

    def describe(self) -> str:
        """One line suitable for a status table."""
        when = self.next_run.strftime("%a %H:%M:%S") if self.next_run else "unknown"
        state = "paused" if self.paused else f"next {when}"
        return f"{self.name or self.id} ({self.kind}, {state})"


@dataclass
class _FallbackJob:
    """A job the built-in engine runs itself."""

    info: JobInfo
    func: JobFunc
    seconds: float = 0.0
    at: Optional[datetime] = None
    cron: Dict[str, Any] = field(default_factory=dict)
    task: Optional["asyncio.Task[None]"] = None


class Scheduler:
    """Run callables later, repeatedly, or on a cron-like rule."""

    def __init__(self, timezone: str = "", prefer_apscheduler: bool = True) -> None:
        """Create a scheduler (nothing runs until :meth:`start`).

        Args:
            timezone: Optional timezone name for APScheduler.
            prefer_apscheduler: Set False to force the built-in engine, which
                is what the tests do so both paths stay honest.
        """
        self.timezone = timezone
        self._use_ap = bool(HAS_APSCHEDULER and prefer_apscheduler)
        self._ap: Any = None
        self._jobs: Dict[str, _FallbackJob] = {}
        self._started = False

    @property
    def engine(self) -> str:
        """``"apscheduler"`` or ``"builtin"``."""
        return "apscheduler" if self._use_ap else "builtin"

    @property
    def running(self) -> bool:
        """True once :meth:`start` has been called and not shut down."""
        return self._started

    # ------------------------------------------------------------- lifecycle
    def start(self) -> str:
        """Start the engine.

        Returns:
            The engine name actually in use — APScheduler can fail to start on
            an odd event loop, in which case this falls back silently.
        """
        if self._started:
            return self.engine
        if self._use_ap:
            try:
                kwargs: Dict[str, Any] = {}
                if self.timezone:
                    kwargs["timezone"] = self.timezone
                self._ap = AsyncIOScheduler(**kwargs)
                self._ap.start()
            except Exception as error:
                logger.debug("APScheduler would not start (%s); using the fallback.", error)
                self._ap = None
                self._use_ap = False
        self._started = True
        logger.debug("Scheduler started with the %s engine.", self.engine)
        return self.engine

    async def shutdown(self) -> None:
        """Stop every job and release the engine."""
        self._started = False
        if self._ap is not None:
            with contextlib.suppress(Exception):
                self._ap.shutdown(wait=False)
            self._ap = None
        for job in list(self._jobs.values()):
            if job.task is not None:
                job.task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await job.task
        self._jobs.clear()

    # ---------------------------------------------------------- adding jobs
    def every(self, seconds: float, func: JobFunc, job_id: str = "",
              name: str = "") -> JobInfo:
        """Run ``func`` every ``seconds`` seconds.

        Args:
            seconds: Interval length; values below one second are clamped.
            func: Sync or async callable taking no arguments.
            job_id: Optional identifier (generated when omitted).
            name: Human-readable description.

        Returns:
            The :class:`JobInfo` describing the scheduled job.
        """
        seconds = max(1.0, float(seconds))
        job_id = job_id or f"every-{seconds:g}-{len(self._jobs)}"
        info = JobInfo(id=job_id, name=name or job_id, kind="interval",
                       next_run=datetime.now() + timedelta(seconds=seconds))
        if self._ap is not None:
            self._ap.add_job(
                self._wrap(func, info), IntervalTrigger(seconds=seconds),
                id=job_id, name=info.name, replace_existing=True,
                misfire_grace_time=60, coalesce=True,
            )
            self._jobs[job_id] = _FallbackJob(info=info, func=func, seconds=seconds)
            return info
        job = _FallbackJob(info=info, func=func, seconds=seconds)
        self._jobs[job_id] = job
        job.task = self._spawn(self._run_interval(job))
        return info

    def at(self, when: datetime, func: JobFunc, job_id: str = "",
           name: str = "") -> JobInfo:
        """Run ``func`` once, at a specific moment.

        Args:
            when: When to fire; a past time fires as soon as possible.
            func: Sync or async callable.
            job_id: Optional identifier.
            name: Human-readable description.

        Returns:
            The :class:`JobInfo`.
        """
        job_id = job_id or f"at-{when:%Y%m%d%H%M%S}-{len(self._jobs)}"
        info = JobInfo(id=job_id, name=name or job_id, kind="date", next_run=when)
        if self._ap is not None:
            self._ap.add_job(
                self._wrap(func, info, once=True), DateTrigger(run_date=when),
                id=job_id, name=info.name, replace_existing=True,
                misfire_grace_time=300,
            )
            self._jobs[job_id] = _FallbackJob(info=info, func=func, at=when)
            return info
        job = _FallbackJob(info=info, func=func, at=when)
        self._jobs[job_id] = job
        job.task = self._spawn(self._run_once(job))
        return info

    def cron(self, func: JobFunc, job_id: str = "", name: str = "", hour: int = 0,
             minute: int = 0, day_of_week: str = "") -> JobInfo:
        """Run ``func`` on a daily/weekly clock rule.

        Args:
            func: Sync or async callable.
            job_id: Optional identifier.
            name: Human-readable description.
            hour: Hour of day, 0-23.
            minute: Minute of the hour.
            day_of_week: APScheduler-style day list, e.g. ``"mon-fri"`` or
                ``"sat,sun"``. Empty means every day.

        Returns:
            The :class:`JobInfo`.
        """
        job_id = job_id or f"cron-{hour:02d}{minute:02d}-{len(self._jobs)}"
        spec = {"hour": hour, "minute": minute, "day_of_week": day_of_week}
        info = JobInfo(id=job_id, name=name or job_id, kind="cron",
                       next_run=self._next_cron(datetime.now(), spec))
        if self._ap is not None:
            trigger = (
                CronTrigger(hour=hour, minute=minute, day_of_week=day_of_week)
                if day_of_week else CronTrigger(hour=hour, minute=minute)
            )
            self._ap.add_job(
                self._wrap(func, info), trigger, id=job_id, name=info.name,
                replace_existing=True, misfire_grace_time=300, coalesce=True,
            )
            self._jobs[job_id] = _FallbackJob(info=info, func=func, cron=spec)
            return info
        job = _FallbackJob(info=info, func=func, cron=spec)
        self._jobs[job_id] = job
        job.task = self._spawn(self._run_cron(job))
        return info

    def from_rule(self, rule: Any, func: JobFunc, job_id: str = "",
                  name: str = "") -> JobInfo:
        """Schedule from a :class:`modules.productivity.ScheduleRule`.

        Bridges JARVIS's own natural-language schedule parser ("every weekday
        at 9am") onto whichever engine is running.

        Args:
            rule: Anything with ``kind``, ``hour``, ``minute``, ``weekdays``
                and ``seconds`` attributes.
            func: Sync or async callable.
            job_id: Optional identifier.
            name: Human-readable description.

        Returns:
            The :class:`JobInfo`.
        """
        kind = getattr(rule, "kind", "daily")
        hour = int(getattr(rule, "hour", 8))
        minute = int(getattr(rule, "minute", 0))
        weekdays = tuple(getattr(rule, "weekdays", ()) or ())
        seconds = int(getattr(rule, "seconds", 0) or 0)
        label = name or getattr(rule, "text", "") or job_id

        if kind == "interval" and seconds:
            return self.every(seconds, func, job_id=job_id, name=label)
        if kind == "hourly":
            return self.every(3600, func, job_id=job_id, name=label)
        if kind == "once":
            target = datetime.now().replace(hour=hour, minute=minute, second=0,
                                            microsecond=0)
            if target <= datetime.now():
                target += timedelta(days=1)
            return self.at(target, func, job_id=job_id, name=label)

        names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        if kind == "weekdays":
            days = "mon-fri"
        elif kind == "weekends":
            days = "sat,sun"
        elif kind == "weekly" and weekdays:
            days = ",".join(names[day] for day in weekdays)
        else:
            days = ""
        return self.cron(func, job_id=job_id, name=label, hour=hour, minute=minute,
                         day_of_week=days)

    # -------------------------------------------------------- managing jobs
    def remove(self, job_id: str) -> bool:
        """Cancel and forget one job.

        Args:
            job_id: The identifier returned when it was added.

        Returns:
            True when a job was removed.
        """
        job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        if self._ap is not None:
            with contextlib.suppress(Exception):
                self._ap.remove_job(job_id)
        if job.task is not None:
            job.task.cancel()
        return True

    def pause(self, job_id: str) -> bool:
        """Suspend a job without forgetting it."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.info.paused = True
        if self._ap is not None:
            with contextlib.suppress(Exception):
                self._ap.pause_job(job_id)
        return True

    def resume(self, job_id: str) -> bool:
        """Un-pause a job."""
        job = self._jobs.get(job_id)
        if job is None:
            return False
        job.info.paused = False
        if self._ap is not None:
            with contextlib.suppress(Exception):
                self._ap.resume_job(job_id)
        return True

    def jobs(self) -> List[JobInfo]:
        """Every known job, newest last."""
        if self._ap is not None:
            for scheduled in self._ap.get_jobs():
                job = self._jobs.get(scheduled.id)
                if job is not None:
                    job.info.next_run = getattr(scheduled, "next_run_time", None)
        return [job.info for job in self._jobs.values()]

    def job(self, job_id: str) -> Optional[JobInfo]:
        """Look up one job's state."""
        job = self._jobs.get(job_id)
        return job.info if job else None

    # ------------------------------------------------------ internal engine
    def _spawn(self, coro: Any) -> "asyncio.Task[None]":
        """Create a task, tolerating being called before the loop exists."""
        return asyncio.ensure_future(coro)

    def _wrap(self, func: JobFunc, info: JobInfo, once: bool = False) -> Callable[[], Any]:
        """Wrap a job so failures are logged and run counts stay accurate."""
        async def runner() -> None:
            """Execute one firing of the job."""
            if info.paused:
                return
            info.runs += 1
            try:
                outcome = func()
                if asyncio.iscoroutine(outcome):
                    await outcome
            except asyncio.CancelledError:
                raise
            except Exception as error:  # one bad job must not stop the rest
                logger.debug("Scheduled job %s failed: %s", info.id, error)
            if once:
                self._jobs.pop(info.id, None)

        return runner

    async def _run_interval(self, job: _FallbackJob) -> None:
        """Fallback engine: fire every ``job.seconds`` seconds."""
        runner = self._wrap(job.func, job.info)
        while True:
            try:
                await asyncio.sleep(job.seconds)
                job.info.next_run = datetime.now() + timedelta(seconds=job.seconds)
                await runner()
            except asyncio.CancelledError:
                return

    async def _run_once(self, job: _FallbackJob) -> None:
        """Fallback engine: fire once at ``job.at``."""
        runner = self._wrap(job.func, job.info, once=True)
        delay = max(0.0, ((job.at or datetime.now()) - datetime.now()).total_seconds())
        try:
            await asyncio.sleep(delay)
            await runner()
        except asyncio.CancelledError:
            return

    async def _run_cron(self, job: _FallbackJob) -> None:
        """Fallback engine: fire on the next matching clock time, forever."""
        runner = self._wrap(job.func, job.info)
        while True:
            try:
                target = self._next_cron(datetime.now(), job.cron)
                job.info.next_run = target
                await asyncio.sleep(max(1.0, (target - datetime.now()).total_seconds()))
                await runner()
                # Guard against firing twice inside the same minute.
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return

    @staticmethod
    def _next_cron(now: datetime, spec: Dict[str, Any]) -> datetime:
        """Compute the next firing time for a simple cron spec.

        Args:
            now: The reference moment.
            spec: ``hour``, ``minute`` and ``day_of_week`` keys.

        Returns:
            The next matching datetime, strictly after ``now``.
        """
        names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        raw = str(spec.get("day_of_week", "") or "").strip().lower()
        allowed = set(range(7))
        if raw:
            allowed = set()
            for part in raw.split(","):
                part = part.strip()
                if "-" in part:
                    first, _, last = part.partition("-")
                    if first in names and last in names:
                        start, end = names.index(first), names.index(last)
                        allowed.update(
                            range(start, end + 1) if start <= end
                            else list(range(start, 7)) + list(range(0, end + 1))
                        )
                elif part in names:
                    allowed.add(names.index(part))
            allowed = allowed or set(range(7))

        candidate = now.replace(hour=int(spec.get("hour", 0)),
                                minute=int(spec.get("minute", 0)),
                                second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        for _ in range(8):
            if candidate.weekday() in allowed:
                return candidate
            candidate += timedelta(days=1)
        return candidate


def _now_like(moment: datetime) -> datetime:
    """Return "now" with the same awareness as ``moment``.

    APScheduler hands back timezone-aware times while the fallback engine uses
    naive ones; subtracting the two raises. This makes them comparable.

    Args:
        moment: The datetime to match.

    Returns:
        The current time, aware or naive to match.
    """
    if moment.tzinfo is not None:
        return datetime.now(moment.tzinfo)
    return datetime.now()


#: Module-level convenience for code that just wants "call this in N seconds".
async def run_later(seconds: float, func: JobFunc) -> None:
    """Await ``seconds`` and then run ``func`` once, swallowing its errors.

    Args:
        seconds: How long to wait.
        func: Sync or async callable taking no arguments.
    """
    await asyncio.sleep(max(0.0, seconds))
    try:
        outcome = func()
        if asyncio.iscoroutine(outcome):
            await outcome
    except Exception as error:
        logger.debug("Deferred call failed: %s", error)


def humanise_next(info: Optional[JobInfo]) -> str:
    """Describe when a job fires next, in words.

    Args:
        info: The job, or ``None``.

    Returns:
        Something like ``"in 4 minutes"`` — or ``"never"``.
    """
    if info is None or info.next_run is None:
        return "never"
    seconds = (info.next_run - _now_like(info.next_run)).total_seconds()
    if seconds < 0:
        return "now"
    if seconds < 90:
        return f"in {int(seconds)} seconds"
    if seconds < 5400:
        return f"in {int(seconds / 60)} minutes"
    return info.next_run.strftime("at %H:%M on %A")


__all__ = [
    "HAS_APSCHEDULER",
    "JobInfo",
    "Scheduler",
    "humanise_next",
    "run_later",
]

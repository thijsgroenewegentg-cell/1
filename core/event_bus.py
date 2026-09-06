# /core/event_bus.py
"""A tiny async pub/sub so modules can talk without importing each other.

The brain publishes what it is doing; anything that cares can listen. That is
how the web UI shows a live "thinking…" state, how the voice interface knows a
turn ended, and how a plugin can react to a timer firing without the timer
knowing the plugin exists.

Design rules learned the hard way:

* A slow or broken subscriber must never break the publisher — every handler is
  wrapped, and an exception is logged, not raised.
* Handlers may be sync or async; both are awaited correctly.
* ``publish`` never blocks the caller for longer than the slowest handler, and
  :meth:`emit` does not block it at all.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.event_bus")

#: Subscribe to this to see every event.
WILDCARD = "*"

Handler = Callable[["Event"], Any]


@dataclass
class Event:
    """Something that happened, with whatever context came with it.

    Attributes:
        name: Dotted event name, e.g. ``turn.finished``.
        data: Arbitrary payload.
        at: Unix timestamp of publication.
        source: Who published it, for debugging.
    """

    name: str
    data: Dict[str, Any] = field(default_factory=dict)
    at: float = field(default_factory=time.time)
    source: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        """Read one field of the payload."""
        return self.data.get(key, default)


class EventBus:
    """In-process publish/subscribe with a short replayable history."""

    def __init__(self, history: int = 200) -> None:
        """Create a bus.

        Args:
            history: How many recent events to keep for :meth:`recent`.
        """
        self._handlers: Dict[str, List[Handler]] = defaultdict(list)
        self._history: Deque[Event] = deque(maxlen=max(1, history))
        self._tasks: set = set()
        self.enabled = True

    # ------------------------------------------------------------ subscribing
    def subscribe(self, name: str, handler: Handler) -> Callable[[], None]:
        """Register a handler for an event name (or :data:`WILDCARD`).

        Args:
            name: Event name to listen for, ``"*"`` for everything.
            handler: Sync or async callable taking one :class:`Event`.

        Returns:
            A function that unsubscribes this handler again.
        """
        self._handlers[name].append(handler)

        def unsubscribe() -> None:
            """Remove the handler registered above."""
            with contextlib.suppress(ValueError):
                self._handlers[name].remove(handler)

        return unsubscribe

    def unsubscribe(self, name: str, handler: Handler) -> bool:
        """Remove one handler.

        Args:
            name: The event name it was registered under.
            handler: The exact callable that was registered.

        Returns:
            True if it was found and removed.
        """
        try:
            self._handlers[name].remove(handler)
            return True
        except ValueError:
            return False

    def subscriber_count(self, name: Optional[str] = None) -> int:
        """Count handlers for one event, or for all of them."""
        if name is None:
            return sum(len(items) for items in self._handlers.values())
        return len(self._handlers.get(name, [])) + len(self._handlers.get(WILDCARD, []))

    # ------------------------------------------------------------- publishing
    async def publish(self, name: str, /, source: str = "", **data: Any) -> Event:
        """Deliver an event to every matching handler and wait for them.

        A handler that raises is logged and skipped; the others still run.

        Args:
            name: Event name.
            source: Optional publisher label.
            **data: The payload.

        Returns:
            The published :class:`Event`.
        """
        event = Event(name=name, data=dict(data), source=source)
        self._history.append(event)
        if not self.enabled:
            return event

        for handler in list(self._handlers.get(name, [])) + list(
            self._handlers.get(WILDCARD, [])
        ):
            try:
                outcome = handler(event)
                if inspect.isawaitable(outcome):
                    await outcome
            except Exception as error:  # a listener must never break the publisher
                logger.debug("Event handler for %s failed: %s", name, error)
        return event

    def emit(self, name: str, /, source: str = "", **data: Any) -> Optional[Event]:
        """Fire and forget: publish without awaiting the handlers.

        Safe to call from synchronous code. When no event loop is running the
        event is still recorded in the history and handlers are skipped.

        Args:
            name: Event name.
            source: Optional publisher label.
            **data: The payload.

        Returns:
            The event when it could be scheduled, else ``None``.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._history.append(Event(name=name, data=dict(data), source=source))
            return None
        task = loop.create_task(self.publish(name, source=source, **data))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return Event(name=name, data=dict(data), source=source)

    # ---------------------------------------------------------------- waiting
    async def wait_for(self, name: str, timeout: Optional[float] = None) -> Optional[Event]:
        """Block until an event with this name is published.

        Args:
            name: Event name to wait for.
            timeout: Seconds before giving up (``None`` waits forever).

        Returns:
            The event, or ``None`` on timeout.
        """
        loop = asyncio.get_running_loop()
        future: "asyncio.Future[Event]" = loop.create_future()

        def catch(event: Event) -> None:
            """Complete the future with the first matching event."""
            if not future.done():
                future.set_result(event)

        cancel = self.subscribe(name, catch)
        try:
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            cancel()

    # ---------------------------------------------------------------- history
    def recent(self, name: str = "", limit: int = 20) -> List[Event]:
        """Return the most recent events, newest last.

        Args:
            name: Optional exact name filter.
            limit: Maximum number to return.

        Returns:
            A list of events.
        """
        events = [e for e in self._history if not name or e.name == name]
        return events[-limit:]

    def clear(self) -> None:
        """Forget the history (handlers stay subscribed)."""
        self._history.clear()

    async def close(self) -> None:
        """Wait for any fire-and-forget deliveries still in flight."""
        pending = list(self._tasks)
        for task in pending:
            with contextlib.suppress(Exception):
                await task
        self._handlers.clear()


#: Event names the core publishes, so subscribers have something to autocomplete.
TURN_STARTED = "turn.started"
INTENT_CLASSIFIED = "turn.intent"
TOOL_CALLED = "tool.called"
TURN_FINISHED = "turn.finished"
ERROR_RAISED = "error.raised"
REMINDER_FIRED = "reminder.fired"
MODULE_RELOADED = "module.reloaded"

__all__ = [
    "ERROR_RAISED",
    "INTENT_CLASSIFIED",
    "MODULE_RELOADED",
    "REMINDER_FIRED",
    "TOOL_CALLED",
    "TURN_FINISHED",
    "TURN_STARTED",
    "WILDCARD",
    "Event",
    "EventBus",
]

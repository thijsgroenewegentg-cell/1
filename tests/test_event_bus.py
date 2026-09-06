# /tests/test_event_bus.py
"""Unit tests for core/event_bus.py.

The bus is what lets the voice interface, the web UI and the scheduler watch
a turn unfold without the brain knowing they exist, so the guarantees that
matter are: subscribers get their events, a broken subscriber cannot break
the publisher, and unsubscribing really stops delivery.
"""

from __future__ import annotations

import asyncio

import pytest

from core.event_bus import (
    ERROR_RAISED,
    TURN_FINISHED,
    TURN_STARTED,
    WILDCARD,
    Event,
    EventBus,
)
from tests.conftest import run


def test_a_subscriber_receives_the_event_it_asked_for():
    bus = EventBus()
    seen = []
    bus.subscribe(TURN_STARTED, lambda event: seen.append(event))
    run(bus.publish(TURN_STARTED, text="hello"))
    assert len(seen) == 1
    assert seen[0].data["text"] == "hello"


def test_a_subscriber_is_not_bothered_by_other_events():
    bus = EventBus()
    seen = []
    bus.subscribe(TURN_STARTED, lambda event: seen.append(event))
    run(bus.publish(TURN_FINISHED))
    assert seen == []


def test_a_wildcard_subscriber_receives_everything():
    bus = EventBus()
    seen = []
    bus.subscribe(WILDCARD, lambda event: seen.append(event.name))
    run(bus.publish(TURN_STARTED))
    run(bus.publish(ERROR_RAISED))
    assert seen == [TURN_STARTED, ERROR_RAISED]


def test_async_handlers_are_awaited():
    bus = EventBus()
    seen = []

    async def handler(event: Event) -> None:
        await asyncio.sleep(0)
        seen.append(event.name)

    bus.subscribe(TURN_STARTED, handler)
    run(bus.publish(TURN_STARTED))
    assert seen == [TURN_STARTED]


def test_a_handler_that_raises_cannot_break_the_publisher():
    bus = EventBus()
    survivors = []

    def explode(event: Event) -> None:
        raise RuntimeError("this handler is broken")

    bus.subscribe(TURN_STARTED, explode)
    bus.subscribe(TURN_STARTED, lambda event: survivors.append(event.name))
    run(bus.publish(TURN_STARTED))  # must not raise
    assert survivors == [TURN_STARTED]


def test_unsubscribing_stops_delivery():
    bus = EventBus()
    seen = []
    handler = seen.append
    bus.subscribe(TURN_STARTED, handler)
    assert bus.unsubscribe(TURN_STARTED, handler)
    run(bus.publish(TURN_STARTED))
    assert seen == []


def test_unsubscribing_something_that_was_never_subscribed_is_false():
    assert not EventBus().unsubscribe(TURN_STARTED, print)


def test_subscriber_counts_are_reported():
    bus = EventBus()
    bus.subscribe(TURN_STARTED, print)
    bus.subscribe(TURN_STARTED, repr)
    assert bus.subscriber_count(TURN_STARTED) == 2
    assert bus.subscriber_count() >= 2


def test_recent_history_is_kept_for_replay():
    bus = EventBus()
    run(bus.publish(TURN_STARTED, text="one"))
    run(bus.publish(TURN_FINISHED, text="two"))
    history = bus.recent()
    assert [event.name for event in history] == [TURN_STARTED, TURN_FINISHED]
    assert [event.name for event in bus.recent(name=TURN_STARTED)] == [TURN_STARTED]


def test_history_can_be_cleared():
    bus = EventBus()
    run(bus.publish(TURN_STARTED))
    bus.clear()
    assert bus.recent() == []


def test_emit_delivers_without_being_awaited():
    async def scenario() -> list:
        bus = EventBus()
        seen = []
        bus.subscribe(TURN_STARTED, lambda event: seen.append(event.name))
        bus.emit(TURN_STARTED)
        await asyncio.sleep(0.05)
        return seen

    assert run(scenario()) == [TURN_STARTED]


def test_wait_for_returns_the_matching_event():
    async def scenario() -> Event:
        bus = EventBus()
        asyncio.get_running_loop().call_later(
            0.01, lambda: bus.emit(TURN_FINISHED, response="done")
        )
        return await bus.wait_for(TURN_FINISHED, timeout=2.0)

    event = run(scenario())
    assert event is not None
    assert event.data["response"] == "done"


def test_wait_for_gives_up_at_the_timeout():
    async def scenario() -> object:
        return await EventBus().wait_for(TURN_FINISHED, timeout=0.05)

    assert run(scenario()) is None


def test_closing_the_bus_drops_every_subscriber():
    async def scenario() -> int:
        bus = EventBus()
        bus.subscribe(TURN_STARTED, print)
        await bus.close()
        return bus.subscriber_count()

    assert run(scenario()) == 0


def test_events_carry_a_source_and_a_timestamp():
    bus = EventBus()
    run(bus.publish(TURN_STARTED, source="brain", text="hi"))
    event = bus.recent()[0]
    assert event.source == "brain"
    assert event.at > 0


@pytest.mark.parametrize("name", [TURN_STARTED, TURN_FINISHED, ERROR_RAISED])
def test_the_standard_event_names_are_namespaced(name):
    assert "." in name

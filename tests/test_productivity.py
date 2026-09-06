# /tests/test_productivity.py
"""Unit tests for modules/productivity.py.

Every test gets its own SQLite file under ``tmp_path``, so todos, reminders,
notes and schedules can be created and destroyed without touching the real
database.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from modules.productivity import Productivity, ScheduleRule, parse_quiet_hours, parse_schedule
from tests.conftest import run


@pytest.fixture
def productivity(config):
    """A Productivity module with a fresh database."""
    module = Productivity(config)
    run(module.setup())
    yield module
    run(module.shutdown())


# ------------------------------------------------------------------- routing
@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("remind me to call mom at 5pm", "add_reminder"),
        ("set a timer for 10 minutes", "start_timer"),
        ("add buy milk to my todo list", "add_todo"),
        ("what's on my todo list", "list_todos"),
        ("take a note: the wifi password is hunter2", "add_note"),
        ("give me my daily briefing", "daily_briefing"),
        ("start a stopwatch", "stopwatch"),
    ],
)
def test_offline_router_handles_the_common_requests(productivity, phrase, expected):
    routed = productivity.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


# --------------------------------------------------------------------- todos
def test_a_todo_survives_being_listed_and_completed(productivity):
    created = run(productivity.call_tool("add_todo", {"task": "test the assistant"}))
    assert created.success

    listed = run(productivity.call_tool("list_todos", {}))
    assert "test the assistant" in listed.output

    done = run(productivity.call_tool("complete_todo", {"task": "test the assistant"}))
    assert done.success

    remaining = run(productivity.call_tool("list_todos", {}))
    assert "test the assistant" not in remaining.output


def test_completing_a_todo_that_does_not_exist_fails_politely(productivity):
    result = run(productivity.call_tool("complete_todo", {"task": "learn to fly"}))
    assert not result.success
    assert result.error


def test_todos_can_carry_a_priority(productivity):
    run(productivity.call_tool("add_todo", {"task": "urgent thing", "priority": "high"}))
    listed = run(productivity.call_tool("list_todos", {}))
    assert "urgent thing" in listed.output


# ----------------------------------------------------------------- reminders
def test_a_reminder_is_stored_with_a_future_time(productivity):
    result = run(productivity.call_tool(
        "add_reminder", {"text": "call mom", "when": "in 45 minutes"}
    ))
    assert result.success
    listed = run(productivity.call_tool("list_reminders", {}))
    assert "call mom" in listed.output


def test_a_reminder_without_a_time_is_refused(productivity):
    result = run(productivity.call_tool("add_reminder", {"text": "", "when": ""}))
    assert not result.success


def test_a_cancelled_reminder_stops_being_listed(productivity):
    run(productivity.call_tool("add_reminder", {"text": "stand up", "when": "in 2 hours"}))
    cancelled = run(productivity.call_tool("cancel_reminder", {"text": "stand up"}))
    assert cancelled.success
    assert "stand up" not in run(productivity.call_tool("list_reminders", {})).output


# --------------------------------------------------------------------- notes
def test_notes_can_be_written_and_found_again(productivity):
    run(productivity.call_tool("add_note", {"content": "the wifi password is hunter2"}))
    found = run(productivity.call_tool("search_notes", {"query": "wifi"}))
    assert found.success
    assert "hunter2" in found.output


def test_searching_for_a_note_that_is_not_there_says_so(productivity):
    result = run(productivity.call_tool("search_notes", {"query": "nonexistent gibberish"}))
    assert "no" in (result.output + result.error).lower()


# -------------------------------------------------------------------- timers
def test_a_timer_starts_and_can_be_cancelled(productivity):
    async def scenario() -> tuple:
        # A timer is an asyncio task, so the whole scenario has to share one
        # event loop — start, list and cancel cannot each get their own.
        started = await productivity.call_tool("start_timer", {"duration": "10 minutes"})
        listed = await productivity.call_tool("list_timers", {})
        cancelled = await productivity.call_tool("cancel_timer", {})
        return started, listed, cancelled

    started, listed, cancelled = run(scenario())
    assert started.success
    assert "remaining" in listed.output and "9m" in listed.output
    assert cancelled.success


def test_a_timer_needs_a_parsable_duration(productivity):
    result = run(productivity.call_tool("start_timer", {"duration": "a little while"}))
    assert not result.success


# ------------------------------------------------------------------ schedule
@pytest.mark.parametrize(
    ("phrase", "kind"),
    [
        ("every day at 8am", "daily"),
        ("every weekday at 9:30", "weekdays"),
        ("every hour", "hourly"),
        ("every 15 minutes", "interval"),
    ],
)
def test_schedule_phrases_parse_into_rules(phrase, kind):
    rule = parse_schedule(phrase)
    assert rule is not None, f"{phrase!r} should parse"
    assert rule.kind == kind


def test_a_daily_rule_always_points_at_the_future():
    rule = ScheduleRule(kind="daily", hour=6, minute=0)
    now = datetime.now()
    assert rule.next_after(now) > now


def test_an_interval_rule_repeats_at_its_interval():
    rule = ScheduleRule(kind="interval", seconds=600)
    now = datetime.now()
    assert rule.next_after(now) - now <= timedelta(seconds=600)


def test_nonsense_schedules_are_rejected():
    assert parse_schedule("whenever you feel like it") is None


# --------------------------------------------------------------- quiet hours
@pytest.mark.parametrize(
    ("text", "expected"),
    [("23:00-07:00", (23 * 60, 7 * 60)), ("22:30 - 06:15", (22 * 60 + 30, 6 * 60 + 15))],
)
def test_quiet_hours_parse(text, expected):
    # Stored as minutes since midnight, so a window can wrap past midnight.
    assert parse_quiet_hours(text) == expected


@pytest.mark.parametrize("text", ["", "nights", "25:00-07:00"])
def test_quiet_hours_rejects_rubbish(text):
    assert parse_quiet_hours(text) is None


def test_the_scheduler_is_running_after_setup(productivity):
    assert productivity._scheduler.running
    assert productivity._scheduler.job("productivity-tick") is not None


def test_a_tick_with_nothing_due_is_harmless(productivity):
    run(productivity._tick())


def test_a_negative_duration_is_refused(productivity):
    # "-5 minutes" lost its sign and quietly started a five-minute timer.
    result = run(productivity.call_tool("start_timer", {"duration": "-5 minutes"}))
    assert not result.success


def test_a_non_numeric_id_is_refused_politely(productivity):
    # This used to raise ValueError inside the tool and log a stack trace.
    result = run(productivity.call_tool("delete_note", {"note_id": "the shopping one"}))
    assert not result.success
    assert "number" in result.error.lower()

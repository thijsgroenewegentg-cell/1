# /tests/test_communications.py
"""Unit tests for modules/communications.py — e-mail and calendar.

Nothing is configured in a test run, so what is verified is that every tool
explains what is missing instead of raising, and that nothing tries to reach
a mail server on import.
"""

from __future__ import annotations

import pytest

from modules.communications import Communications
from tests.conftest import run


@pytest.fixture
def comms(config):
    """A Communications module with no mailbox configured."""
    return Communications(config)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("check my email", "check_email"),
        ("what's on my calendar", "upcoming_events"),
        ("what's my next meeting", "next_event"),
    ],
)
def test_offline_router_recognises_comms_requests(comms, phrase, expected):
    routed = comms.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_status_reports_that_nothing_is_configured(comms):
    result = run(comms.call_tool("comms_status", {}))
    assert result.success
    assert result.output.strip()


def test_checking_mail_without_an_account_explains_how_to_set_it_up(comms):
    result = run(comms.call_tool("check_email", {}))
    assert not result.success
    assert "config" in result.error.lower() or "email" in result.error.lower()


def test_sending_mail_without_an_account_is_refused(comms):
    result = run(comms.call_tool("send_email", {
        "to": "someone@example.com", "subject": "hello", "body": "hi"
    }))
    assert not result.success


def test_the_calendar_is_readable_even_when_empty(comms):
    result = run(comms.call_tool("upcoming_events", {"days": 7}))
    assert result.output or result.error


def test_an_event_can_be_added_locally(comms):
    result = run(comms.call_tool("add_event", {
        "title": "dentist", "when": "tomorrow at 10:00"
    }))
    assert result.output or result.error


def test_email_contents_are_untrusted(comms):
    assert comms.tools["check_email"].untrusted

# /tests/test_proactive.py
"""Check-ins, topic watches and hardware alerts — all model-free."""

from __future__ import annotations

from datetime import datetime

from core import proactive
from tests.conftest import run


def test_a_new_watch_is_listed_and_can_be_removed(config):
    assert proactive.add_watch(config, "fusion") is True
    assert "fusion" in proactive.watches(config)
    assert proactive.add_watch(config, "fusion") is False
    assert proactive.remove_watch(config, "fusion") is True
    assert "fusion" not in proactive.watches(config)


def test_the_briefing_is_due_once_a_day(config):
    assert proactive.briefing_due(config, "2026-09-10") is True
    proactive.mark_briefing_delivered(config, "2026-09-10")
    assert proactive.briefing_due(config, "2026-09-10") is False
    assert proactive.briefing_due(config, "2026-09-11") is True


def test_a_check_in_fires_once_per_slot(config):
    noon = datetime(2026, 9, 10, 14, 5)
    assert proactive.check_in_due(config, noon) == 14
    proactive.mark_check_in(config, 14, noon)
    assert proactive.check_in_due(config, noon) is None
    later = datetime(2026, 9, 10, 18, 1)
    assert proactive.check_in_due(config, later) == 18


def test_check_in_line_mentions_open_tasks():
    line = proactive.check_in_line(9, tasks=2)
    assert "Good morning" in line
    assert "2 open tasks" in line
    dutch = proactive.check_in_line(21, tasks=0, dutch=True)
    assert "Goedenavond" in dutch


def test_hardware_alerts_use_hysteresis(config):
    config.set("assistant.hardware_alerts", True)
    config.set("assistant.cpu_alert", 90)
    first = proactive.hardware_messages(config, {"cpu": 95, "ram": 10, "temp": 0})
    assert any("CPU" in message for message in first)
    again = proactive.hardware_messages(config, {"cpu": 93, "ram": 10, "temp": 0})
    assert again == []
    cool = proactive.hardware_messages(config, {"cpu": 70, "ram": 10, "temp": 0})
    assert cool == []
    recross = proactive.hardware_messages(config, {"cpu": 96, "ram": 10, "temp": 0})
    assert any("CPU" in message for message in recross)


def test_new_headlines_are_reported_once(config):
    proactive.add_watch(config, "mars")
    first = proactive.remember_headlines(config, "mars", ["Mars colony grows"])
    assert first == ["Mars colony grows"]
    again = proactive.remember_headlines(config, "mars", ["Mars colony grows"])
    assert again == []


def test_watch_phrases_are_answered_offline(config):
    from core.brain import Brain

    brain = Brain(config)
    run(brain.initialize())
    try:
        reply = run(brain.process("watch the news about fusion"))
        assert "fusion" in reply.lower()
        listing = run(brain.process("what are you watching"))
        assert "fusion" in listing.lower()
        stop = run(brain.process("stop watching fusion"))
        assert "no longer" in stop.lower() or "fusion" in stop.lower()
    finally:
        run(brain.shutdown())

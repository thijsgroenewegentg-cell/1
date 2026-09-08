# /tests/test_journal.py
"""The session journal (H): append-only JSON-lines file, rotation, recap.

Covers the journal core (note/rotate/recap/brief) plus the two places the
journal meets the assistant: the "what were we doing yesterday?" offline
answer, and the one-line recap folded into the morning briefing. Everything
writes to ``tmp_path`` and runs with no model.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import core.journal as journal
from modules.productivity import Productivity
from tests.conftest import run


def _seed_day(config, day: str, texts, tools=()) -> None:
    """Write journal entries for an arbitrary past day, oldest-first."""
    path = config.resolve(config.get("assistant.journal_file", "data/journal.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for index, text in enumerate(texts):
            entry = {
                "ts": f"{day}T09:{index:02d}:00",
                "day": day,
                "text": text,
                "response": "Acknowledged, sir.",
                "module": "productivity",
                "tools": list(tools),
                "ok": True,
            }
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _yesterday() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


# ------------------------------------------------------------------- core
def test_note_turn_appends_one_json_line_per_turn(config):
    journal.note_turn(config, text="render the donut", response="Done.",
                      module="blender", tools=["blender.render"])
    journal.note_turn(config, text="add milk to the list", response="Added.",
                      module="productivity", tools=["productivity.add_todo"])

    path = config.resolve(config.get("assistant.journal_file", "data/journal.json"))
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["module"] == "blender"
    assert first["tools"] == ["blender.render"]
    assert first["day"] == datetime.now().strftime("%Y-%m-%d")


def test_note_turn_truncates_long_text_and_tools(config):
    journal.note_turn(
        config,
        text="x" * 400,
        response="y" * 400,
        module="conversation",
        tools=[f"tool.{index}" for index in range(20)],
    )
    path = config.resolve(config.get("assistant.journal_file", "data/journal.json"))
    entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert len(entry["text"]) == 120
    assert len(entry["response"]) == 120
    assert len(entry["tools"]) == 8


def test_the_journal_rotates_to_a_dot_old_sidecar(config, monkeypatch):
    journal.note_turn(config, text="first", response="ok", module="a")
    monkeypatch.setattr(journal, "_ROTATE_BYTES", 60)  # smaller than any line
    journal.note_turn(config, text="second", response="ok", module="b")
    journal.note_turn(config, text="third", response="ok", module="c")

    # Once the live file outgrows the cap it is moved to ``.old`` and a fresh
    # file starts; the sidecar keeps the most recent rotated chunk readable.
    path = config.resolve(config.get("assistant.journal_file", "data/journal.json"))
    old = path.with_suffix(path.suffix + ".old")
    assert old.exists()
    merged = journal._load(config)
    assert [entry["text"] for entry in merged] == ["second", "third"]


def test_events_on_filters_by_day_and_recap_is_speakable(config):
    _seed_day(config, _yesterday(), ["finished the donut", "asked the weather"])
    yesterday_entries = journal.events_on(config, _yesterday())
    assert len(yesterday_entries) == 2

    recap = journal.recap(config, _yesterday())
    assert "exchange" in recap
    assert "finished the donut" in recap

    # A day nobody recorded anything still gets a polite spoken answer.
    empty_day = (datetime.now() - timedelta(days=9)).strftime("%Y-%m-%d")
    quiet = journal.recap(config, empty_day)
    assert "quiet in the journal" in quiet


def test_brief_line_is_blank_for_empty_days_and_compact_otherwise(config):
    assert journal.brief_line(config, _yesterday()) == ""
    _seed_day(config, _yesterday(), ["rendered the donut", "paid the bills"],
              tools=["blender.render", "blender.render",
                     "productivity.complete_todo"])
    line = journal.brief_line(config, _yesterday())
    assert line.startswith("Yesterday:")
    assert "2 request(s)" in line
    assert "blender.render" in line


def test_day_before_crosses_month_boundaries():
    assert journal.day_before("2026-03-01") == "2026-02-28"
    assert journal.day_before("2026-01-01", delta=7) == "2025-12-25"


# ------------------------------------------------------------- in the brain
def _brain(config) -> Any:
    from core.brain import Brain

    brain = Brain(config)
    run(brain.initialize())
    return brain


def test_brain_answers_what_were_we_doing_yesterday(config):
    _seed_day(config, _yesterday(), ["tweaked the lighting rig",
                                     "wrote the weekly summary"])
    brain = _brain(config)
    try:
        reply = run(brain.process("what were we doing yesterday"))
        assert "tweaked the lighting rig" in reply
        assert "exchange" in reply
    finally:
        run(brain.shutdown())


def test_brain_answers_about_the_last_session(config):
    _seed_day(config, _yesterday(), ["re-rigged the donut scene"])
    brain = _brain(config)
    try:
        reply = run(brain.process("what did we do last session"))
        assert "re-rigged the donut scene" in reply
    finally:
        run(brain.shutdown())


def test_ordinary_small_talk_is_not_treated_as_a_recap_question(config):
    brain = _brain(config)
    try:
        reply = run(brain.process("what were you doing when the render crashed"))
        # "what were you doing…" is about the assistant's own action, not a
        # journal request — it must not be intercepted by the recap router,
        # which only claims "what were WE doing" / "what did we do".
        assert "exchange" not in reply
    finally:
        run(brain.shutdown())


def test_every_turn_is_written_to_the_journal(config):
    brain = _brain(config)
    try:
        run(brain.process("what time is it"))
    finally:
        run(brain.shutdown())
    today = datetime.now().strftime("%Y-%m-%d")
    assert len(journal.events_on(config, today)) >= 1


def test_the_morning_brief_folds_in_yesterdays_one_liner(config):
    config.set("modules.communications", False)
    config.set("modules.web_search", False)
    _seed_day(config, _yesterday(), ["re-rigged the donut", "booked the flight"],
              tools=["blender.render", "productivity.add_todo"])
    module = Productivity(config)
    run(module.setup())
    try:
        brief = run(module.daily_briefing())
        assert brief.success
        assert "Yesterday:" in brief.output
        assert "booked the flight" not in brief.output  # the line is compact
    finally:
        run(module.shutdown())

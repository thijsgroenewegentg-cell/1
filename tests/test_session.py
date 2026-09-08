# /tests/test_session.py
"""Boot routine (D) and proactive macro suggestions (F) on the Brain.

Both features are offline: a routine is stored SQLite steps run through the
existing productivity machinery, and macro offers are pure state plus the
existing JSON macro store. No model, no network.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import run


def _brain(config) -> Any:
    """An offline Brain with every module loaded."""
    from core.brain import Brain

    instance = Brain(config)
    run(instance.initialize())
    return instance


@pytest.fixture
def brain(config):
    """An offline Brain with every module loaded."""
    instance = _brain(config)
    yield instance
    run(instance.shutdown())


def _arm_routine(brain, name: str, step: str) -> None:
    module = brain.modules["productivity"]
    result = run(module.call_tool("create_routine", {"name": name, "steps": step}))
    assert result.success


# ------------------------------------------------------------- D: boot routine
def test_boot_routine_runs_the_configured_routine_once(brain, config):
    _arm_routine(brain, "startup", "say:Good morning sir")
    config.set("assistant.boot_routine", "startup")

    text = run(brain.boot_routine())
    assert "Good morning sir" in text

    # Running it again would repeat it — main.py guards that, and the brain
    # call itself simply re-executes the configured steps, so the *routing*
    # must live at the caller. What the brain guarantees is: returns the
    # routine's spoken output and nothing else when unset.
    config.set("assistant.boot_routine", "")
    assert run(brain.boot_routine()) == ""


def test_boot_routine_stays_silent_inside_quiet_hours(config):
    config.set("productivity.quiet_hours", "00:00-23:59")  # always quiet
    brain = _brain(config)  # quiet hours are read at module start-up
    try:
        _arm_routine(brain, "startup", "say:Good morning sir")
        config.set("assistant.boot_routine", "startup")
        assert run(brain.boot_routine()) == ""
    finally:
        run(brain.shutdown())


def test_boot_routine_question_is_answered_offline(brain, config):
    _arm_routine(brain, "startup", "open the mail app; give the briefing")
    config.set("assistant.boot_routine", "startup")

    reply = run(brain.process("what's your boot routine?"))
    assert "startup" in reply
    assert "mail app" in reply

    config.set("assistant.boot_routine", "")
    unset = run(brain.process("what is your boot routine"))
    assert "don't run a boot routine" in unset


def test_creating_a_boot_routine_is_not_treated_as_a_question(brain):
    # "create a boot routine that opens the mail app" belongs to the
    # productivity tools, not the offline answer router.
    reply = run(brain.process("create a boot routine called morning that says hello"))
    assert "don't run a boot routine" not in reply


# ------------------------------------------------------ F: macro suggestions
def _repeat_todo(brain, text: str = "add buy milk to my todo list") -> str:
    return run(brain.process(text))


def test_three_identical_turns_offer_a_macro(brain):
    first = _repeat_todo(brain)
    assert "macro" not in first.lower()
    second = _repeat_todo(brain)
    assert "macro" not in second.lower()
    third = _repeat_todo(brain)
    assert "macro" in third.lower()
    assert brain._macro_offer is not None


def test_the_offer_can_arm_the_macro_with_a_phrase(brain):
    for _ in range(3):
        _repeat_todo(brain, "add water plants to my todo list")
    reply = run(brain.process("yes — when I say plant day"))
    assert "Armed" in reply

    armed = brain.macros.find("plant day")
    assert armed is not None
    steps = armed["steps"]
    assert steps[0]["tool"] == "productivity.add_todo"
    assert steps[0]["params"]["task"] == "water plants"  # exact same call

    # Now that the exact macro exists, repeating the action stops suggesting.
    for _ in range(3):
        _repeat_todo(brain, "add water plants to my todo list")
    assert brain._macro_offer is None


def test_no_thanks_suppresses_the_suggestion_for_the_session(brain):
    for _ in range(3):
        _repeat_todo(brain)
    reply = run(brain.process("no thanks"))
    assert "stop offering" in reply.lower()
    assert brain._macro_offer is None

    fourth = _repeat_todo(brain)  # identical again: must stay silent now
    assert "macro" not in fourth.lower()


def test_macro_suggestions_can_be_turned_off(brain, config):
    config.set("assistant.macro_suggestions", False)
    for _ in range(4):
        reply = _repeat_todo(brain)
    assert "macro" not in reply.lower()
    assert brain._macro_offer is None


def test_a_chat_turn_between_repeats_resets_the_counter(brain):
    _repeat_todo(brain)
    run(brain.process("thanks"))
    _repeat_todo(brain)
    run(brain.process("thanks"))
    reply = _repeat_todo(brain)
    assert "macro" not in reply.lower()
    assert brain._macro_offer is None


def test_the_threshold_is_configurable(brain, config):
    config.set("assistant.macro_repeat_threshold", 2)
    _repeat_todo(brain, "add tea to my todo list")
    second = _repeat_todo(brain, "add tea to my todo list")
    assert "macro" in second.lower()

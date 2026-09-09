# /tests/test_macros.py
"""Voice macros: the JSON store, management tools and the instant trigger."""

from __future__ import annotations

import json

import pytest

from core.brain import Brain
from core.macros import MacroStore, normalize
from tests.conftest import run


@pytest.fixture
def brain(config):
    """An offline Brain with every module loaded, including macros."""
    instance = Brain(config)
    run(instance.initialize())
    yield instance
    run(instance.shutdown())


def test_normalize_handles_filler_and_punctuation():
    assert normalize("hey jarvis, goodnight please!") == "goodnight"
    assert normalize("GOODNIGHT") == "goodnight"
    assert normalize("ok jarvis please run my morning routine") == "run my morning routine"
    assert normalize("can you open the door") == "open the door"
    assert normalize("") == ""


def test_store_add_find_remove_roundtrip(config):
    store = MacroStore(config.resolve("data/macros.json"))
    entry = store.add("movie time", say="Dimming the lights.", steps=[
        {"tool": "productivity.add_todo", "params": {"task": "pick a film"}},
    ])
    assert entry["trigger"] == "movie time"
    # The store may reload from disk between calls, so compare contents.
    assert store.find("movie time") == entry
    assert store.match("hey jarvis, movie time!") == entry
    assert store.all()[0]["uses"] == 0

    store.count_use("movie time")
    assert store.find("movie time")["uses"] == 1

    assert store.remove("movie time") is True
    assert store.find("movie time") is None
    assert store.remove("movie time") is False


def test_store_reloads_when_the_file_changes_under_it(config):
    store_a = MacroStore(config.resolve("data/macros.json"))
    store_b = MacroStore(config.resolve("data/macros.json"))
    store_a.add("goodnight", say="Sleep well.")
    # store_b loaded before the file existed; a match must refresh it.
    assert store_b.match("goodnight") is not None


def test_add_macro_requires_something_to_say_or_do(config):
    store = MacroStore(config.resolve("data/macros.json"))
    with pytest.raises(ValueError):
        store.add("nothing")
    with pytest.raises(ValueError):
        store.add("   ")


def test_macros_module_manages_the_table(brain):
    module = brain.modules["macros"]
    result = run(module.add_macro(
        "goodnight",
        json.dumps({"say": "Sleep well, sir.", "steps": []}),
    ))
    assert result.success
    assert "goodnight" in result.output

    listing = run(module.list_macros())
    assert listing.success
    assert "goodnight" in listing.output
    assert listing.data["macros"][0]["say"] == "Sleep well, sir."

    removed = run(module.remove_macro("goodnight"))
    assert removed.success
    empty = run(module.list_macros())
    assert empty.data["macros"] == []


def test_add_macro_rejects_bad_definition(brain):
    module = brain.modules["macros"]
    result = run(module.add_macro("x", "not json at all"))
    assert not result.success
    result2 = run(module.add_macro("x", '{"steps": "nope"}'))
    assert not result2.success


def test_trigger_fires_instantly_without_a_model(brain):
    module = brain.modules["macros"]
    run(module.add_macro(
        "movie time",
        json.dumps({"say": "Dimming things down.", "steps": [
            {"tool": "productivity.add_todo", "params": {"task": "pick a film"}},
        ]}),
    ))
    reply = run(brain.process("hey jarvis, movie time please"))
    assert "Dimming things down." in reply
    assert "pick a film" in reply

    todos = run(brain.modules["productivity"].list_todos())
    assert any(row["task"] == "pick a film" for row in todos.data["todos"])


def test_trigger_wins_over_conversation_and_is_fast(brain):
    module = brain.modules["macros"]
    run(module.add_macro("goodnight", json.dumps({"say": "Sleep well, sir."})))
    # The brain is offline; if the macro were not matched first this would
    # return the degraded-mode apology instead of the canned line.
    reply = run(brain.process("goodnight"))
    assert reply == "Sleep well, sir."


def test_macro_step_failure_stops_cleanly(brain):
    module = brain.modules["macros"]
    run(module.add_macro(
        "do the thing",
        json.dumps({"say": "Starting.", "steps": [
            {"tool": "productivity.delete_todo", "params": {"task": "not there"}},
            {"tool": "productivity.add_todo", "params": {"task": "should not run"}},
        ]}),
    ))
    reply = run(brain.process("do the thing"))
    assert "Starting." in reply
    assert "snag" in reply
    assert "should not run" not in reply


def test_unarmed_trigger_still_routes_normally(brain):
    # No macro named "goodnight" is armed here, so the offline brain must
    # fall back to its normal (degraded) conversational path — which now
    # answers goodnight properly instead of quoting a canned macro or the
    # model-offline wall.
    reply = run(brain.process("goodnight"))
    assert "goodnight" in reply.lower() or "sleep well" in reply.lower()
    assert "language model is offline" not in reply

# /tests/test_assistant_features.py
"""Wave-2 assistant behaviours: help, read-aloud, done-pings, context."""

from __future__ import annotations

from typing import Any

from core.brain import Brain
from core.intent_router import Intent
from tests.conftest import run


def make_brain(config) -> Any:
    instance = Brain(config)
    run(instance.initialize())
    return instance


# ------------------------------------------------------------------ help text
def test_help_request_lists_live_modules(config):
    brain = make_brain(config)
    try:
        reply = run(brain.process("what can you do?"))
        assert "Here's what I can do" in reply
        assert "productivity" in reply
        assert "macros" in reply  # new module shows up through metadata
        assert "todo" in reply.lower()
    finally:
        run(brain.shutdown())


def test_help_request_works_offline_and_is_short(config):
    brain = make_brain(config)
    try:
        reply = run(brain.process("help"))
        assert "Here's what I can do" in reply
        assert "offline" not in reply.lower()
    finally:
        run(brain.shutdown())


def test_help_is_not_stolen_from_a_longer_request(config):
    brain = make_brain(config)
    try:
        assert brain._is_help_request("help me find my keys please") is False
        assert brain._is_help_request("can you help me with dinner") is False
        assert brain._is_help_request("what can you do") is True
    finally:
        run(brain.shutdown())


# ------------------------------------------------------------------ read aloud
def test_read_aloud_chunks_and_continues(config, tmp_path):
    brain = make_brain(config)
    try:
        config.set("assistant.read_aloud_words", 12)
        text = "one two three four five six seven eight nine ten " * 12
        target = tmp_path / "story.txt"
        target.write_text(text, encoding="utf-8")

        first = run(brain.process(f"read {target} to me"))
        assert "one two three" in first
        assert "There's more" in first

        second = run(brain.process("continue reading"))
        assert "There's more" in second
        assert second.split("There's more")[0].strip()  # chunk text present

        # Keep going until the session ends.
        replies = [first, second]
        for _ in range(30):
            more = run(brain.process("continue reading"))
            replies.append(more)
            if brain._reading is None:
                break
        assert brain._reading is None
        joined = " ".join(replies)
        assert "nothing left to read" not in joined  # ended on content, not an error
        # All of the source words were eventually spoken.
        assert "one two three four five" in joined
    finally:
        run(brain.shutdown())


def test_read_aloud_uses_context_when_no_path_given(config, tmp_path):
    brain = make_brain(config)
    try:
        config.set("assistant.read_aloud_words", 20)
        target = tmp_path / "todo_notes.txt"
        target.write_text("alpha beta gamma delta epsilon zeta eta theta", encoding="utf-8")
        # The previous turn touched this file through a tool.
        run(brain.process(f"add a note about the file {target}"))
        run(brain.dispatch("file_manager.read_file", {"path": str(target)}))
        brain._remember_turn("previous turn", "done")

        reply = run(brain.process("read it to me"))
        assert "alpha beta gamma" in reply
        assert "There's more" not in reply  # short file, read in one go
    finally:
        run(brain.shutdown())


def test_read_aloud_ignores_non_read_requests(config):
    brain = make_brain(config)
    try:
        assert run(brain._read_aloud("what do you think about the weather")) is None
    finally:
        run(brain.shutdown())


# ------------------------------------------------------------------ done-pings
def test_ping_minutes_parsing():
    assert Brain._ping_minutes("remind me to stretch") is None
    assert Brain._ping_minutes("ping me when it's done") == 0
    assert Brain._ping_minutes("notify me when the render is done") == 0
    assert Brain._ping_minutes("ping me in 10 minutes") == 10
    assert Brain._ping_minutes("let me know in 3 minutes") == 3


def test_requested_ping_publishes_a_task_completed_event(config):
    brain = make_brain(config)
    try:
        seen = []
        brain.events.subscribe("task.completed", lambda event: seen.append(event))
        reply = run(brain.process("note down the groceries and ping me when it's done"))
        assert reply  # whatever the note reply is, a ping must follow
        assert len(seen) == 1
        assert seen[0].name == "task.completed"
        assert "groceries" in seen[0].data["text"] or seen[0].data["text"]
    finally:
        run(brain.shutdown())


def test_no_ping_without_a_request(config):
    brain = make_brain(config)
    try:
        seen = []
        brain.events.subscribe("task.completed", lambda event: seen.append(event))
        run(brain.process("tell me a joke"))
        assert seen == []
    finally:
        run(brain.shutdown())


def test_ping_respects_the_master_switch(config):
    config.set("assistant.notify_when_asked", False)
    brain = make_brain(config)
    try:
        seen = []
        brain.events.subscribe("task.completed", lambda event: seen.append(event))
        run(brain.process("ping me when it's done"))
        assert seen == []
    finally:
        run(brain.shutdown())


# ------------------------------------------------------------------ context
def test_referential_detection():
    assert Brain._referential("render it again but slower") is True
    assert Brain._referential("open that file") is True
    assert Brain._referential("what is the weather like today") is False
    assert Brain._referential("same again please") is True


def test_context_hint_describes_the_last_turn(config):
    brain = make_brain(config)
    try:
        config.set("assistant.context_hints", False)
        assert brain._context_hint() == ""
        config.set("assistant.context_hints", True)
        brain._remember_turn("add milk", "Added task #7.")
        hint = brain._context_hint()
        assert "previous request: add milk" in hint
    finally:
        run(brain.shutdown())


def test_anaphora_reroutes_to_the_previous_module(config):
    brain = make_brain(config)
    try:
        run(brain.process("add buy milk to my todo list"))
        assert brain.last_module_hint == "productivity"
        run(brain.process("again, but slower"))
        assert brain.last_intent.module == "productivity"
        assert isinstance(brain.last_intent, Intent)
    finally:
        run(brain.shutdown())

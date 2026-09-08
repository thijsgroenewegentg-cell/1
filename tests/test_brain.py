# /tests/test_brain.py
"""Unit tests for core/brain.py and the pieces it delegates to.

The brain is built with no reachable LLM, so what is under test is the
keyword router, the module registry, the dispatcher, the personality layer
and the event bus — everything that has to keep working when Ollama is not
running.
"""

from __future__ import annotations

import pytest

from core.brain import Brain
from core.intent_router import (
    DECISIVE_CONFIDENCE,
    DECISIVE_PHRASES,
    INTENT_KEYWORDS,
    Intent,
    IntentRouter,
)
from core.personality import Personality
from core.planner import MAX_REACT_STEPS, Planner
from tests.conftest import run


@pytest.fixture
def brain(config):
    """An initialised Brain with every module loaded and no LLM."""
    instance = Brain(config)
    run(instance.initialize())
    yield instance
    run(instance.shutdown())


# ------------------------------------------------------------------ assembly
def test_the_brain_owns_its_collaborators(brain):
    assert isinstance(brain.router, IntentRouter)
    assert isinstance(brain.planner, Planner)
    assert isinstance(brain.persona, Personality)
    assert brain.events is not None


def test_the_expected_modules_are_loaded(brain):
    for name in ("system_control", "web_search", "productivity",
                 "code_assistant", "file_manager", "smart_assistant"):
        assert name in brain.modules, f"{name} should be loaded"


def test_a_disabled_module_is_not_loaded(config):
    config.set("modules.web_search", False)
    instance = Brain(config)
    run(instance.initialize())
    try:
        assert "web_search" not in instance.modules
    finally:
        run(instance.shutdown())


# ------------------------------------------------------------------- routing
@pytest.mark.parametrize(
    ("utterance", "module"),
    [
        ("open chrome", "system_control"),
        ("search for quantum computing", "web_search"),
        ("remind me to call mom at 5pm", "productivity"),
        ("write a python script", "code_assistant"),
        ("find all PDFs on my desktop", "file_manager"),
        ("what is the meaning of life", "smart_assistant"),
        ("what time is it", "system_control"),
        ("set a timer for 10 minutes", "productivity"),
        ("summarize this document", "file_manager"),
        ("how's the weather", "web_search"),
    ],
)
def test_the_ten_reference_utterances_route_correctly(brain, utterance, module):
    # These are the examples the specification calls out by name.
    intent = run(brain.classify(utterance))
    assert intent.module == module, f"{utterance!r} went to {intent.module}"


@pytest.mark.parametrize(
    ("utterance", "module"),
    [
        ("set a timer for 10 minutes then tell me a joke about it", "productivity"),
        ("remind me to water the plants when you get a moment", "productivity"),
        ("what time is it, by the way", "system_control"),
        ("could you search for the best pizza in rome", "web_search"),
    ],
)
def test_decisive_phrases_beat_the_router_model(brain, utterance, module):
    # A 3B router model reads "set a timer" as a question about the time. A
    # phrase this unambiguous must not depend on the model at all.
    intent = run(brain.classify(utterance))
    assert intent.module == module
    assert intent.method == "keyword"
    assert intent.confidence >= DECISIVE_CONFIDENCE


def test_classification_reports_how_it_decided(brain):
    intent = run(brain.classify("open chrome"))
    assert intent.method in {"keyword", "llm", "fallback"}
    assert 0.0 <= intent.confidence <= 1.0


def test_every_keyword_table_names_a_real_module(brain):
    for module in INTENT_KEYWORDS:
        assert module in brain.modules or module in {"memory", "conversation"}


def test_every_decisive_phrase_names_a_real_module(brain):
    for module in DECISIVE_PHRASES:
        assert module in brain.modules


def test_no_decisive_phrase_is_claimed_by_two_modules():
    seen: dict = {}
    for module, phrases in DECISIVE_PHRASES.items():
        for phrase in phrases:
            assert phrase not in seen, f"{phrase!r} claimed by {seen.get(phrase)} and {module}"
            seen[phrase] = module


def test_offline_turns_skip_the_memory_recall_round_trip(brain, monkeypatch):
    """With the model offline nothing can use long-term context anyway, so a
    turn must not wait on an embedding search before answering."""

    def should_not_be_called(*args, **kwargs):
        raise AssertionError("memory recall ran for an offline turn")

    monkeypatch.setattr(brain.memory, "build_context", should_not_be_called)
    reply = run(brain.process("hello"))
    assert reply


def test_an_empty_utterance_is_answered_not_routed(brain):
    assert run(brain.process("")).strip()


# ---------------------------------------------------------------- dispatching
def test_dispatch_runs_a_tool_by_qualified_name(brain):
    result = run(brain.dispatch("system_control.current_time", {}))
    assert result.success


def test_dispatch_finds_a_bare_tool_name(brain):
    result = run(brain.dispatch("current_time", {}))
    assert result.success


def test_dispatch_of_an_unknown_tool_fails_without_raising(brain):
    result = run(brain.dispatch("nonsense.nothing", {}))
    assert not result.success
    assert "no such tool" in result.error.lower() or result.error


def test_dispatch_with_no_tool_named_is_refused(brain):
    assert not run(brain.dispatch("", {})).success


# ---------------------------------------------------------------- personality
def test_the_system_prompt_carries_the_persona(brain):
    prompt = brain.system_prompt()
    assert "JARVIS" in prompt
    assert "sir" in prompt.lower()


def test_the_system_prompt_includes_memory_context(brain):
    prompt = brain.system_prompt("The user's cat is called Widget.")
    assert "Widget" in prompt


def test_error_reports_stay_in_character(brain):
    reply = brain._humorous_failure("connection refused")
    assert reply.strip()
    assert "connection refused" in reply


def test_the_offline_reply_explains_what_is_missing(brain):
    reply = brain._offline_reply("what is the meaning of life")
    assert "ollama" in reply.lower() or "model" in reply.lower()


def test_finalize_strips_model_scaffolding():
    assert "Final Answer:" not in Brain._finalize("Final Answer: All done, sir.")


# ---------------------------------------------------------------------- turns
def test_a_turn_produces_a_reply_and_is_counted(brain):
    before = brain.turn_count
    reply = run(brain.process("what time is it"))
    assert reply.strip()
    assert brain.turn_count == before + 1


def test_a_turn_publishes_its_lifecycle_events(brain):
    seen = []
    brain.events.subscribe("*", lambda event: seen.append(event.name))
    run(brain.process("what time is it"))
    assert "turn.started" in seen
    assert "turn.finished" in seen


def test_the_exchange_is_remembered(brain):
    run(brain.process("what time is it"))
    assert brain.memory.short_term.messages()


def test_the_planner_has_a_step_budget():
    assert 1 <= MAX_REACT_STEPS <= 10


def test_an_intent_is_a_plain_data_object():
    intent = Intent(module="web_search", confidence=0.9, method="keyword")
    assert intent.module == "web_search"
    assert 0 <= intent.confidence <= 1


def test_a_number_shaped_parameter_rejects_prose(brain):
    # The tool used to raise ValueError two frames later and log a traceback.
    result = run(brain.dispatch("productivity.delete_todo", {"task_id": "the milk one"}))
    assert not result.success


def test_an_interrupted_answer_says_stopped_not_offline(brain):
    """Stopping mid-answer used to report that Ollama was unreachable.

    Being told to restart a server that is running perfectly sends the user
    off to debug a non-problem.
    """
    brain.llm.available = True  # the model is up; only the interruption matters
    brain._cancel.set()
    try:
        reply = run(brain._converse("tell me a very long story", ""))
        assert reply == "Stopped."
    finally:
        brain._cancel.clear()
        brain.llm.available = False


def test_a_genuinely_offline_model_still_explains_itself(brain):
    reply = run(brain._converse("tell me a story", ""))
    assert "ollama" in reply.lower()


def test_a_stale_stop_does_not_kill_the_next_turn(brain):
    brain.cancel()
    assert run(brain.process("what time is it")).strip() != "Stopped."


def test_a_blank_optional_number_falls_back_to_its_default(brain):
    # An LLM passing "" for an optional numeric argument should not make the
    # whole call fail — that is what the default is for.
    result = run(brain.dispatch("productivity.list_todos", {"limit": ""}))
    assert result.success


# ------------------------------------------- results, not just prose
def test_a_tool_result_is_published(brain):
    """Interfaces should be able to draw the data, not parse the sentence."""
    seen = []
    brain.events.subscribe("tool.result", lambda event: seen.append(event.data))
    run(brain.dispatch("productivity.add_todo", {"task": "sourdough"}))
    run(brain.dispatch("productivity.list_todos", {}))

    assert len(seen) == 2
    listing = seen[-1]
    assert listing["tool"] == "productivity.list_todos"
    assert listing["ok"] is True
    assert any("sourdough" in str(todo) for todo in listing["data"]["todos"])


def test_published_data_is_kept_small(brain):
    """A file search can return thousands of rows; a socket should not."""
    from core.brain import _compact

    shrunk = _compact({
        "files": [f"/tmp/file{number}.txt" for number in range(500)],
        "text": "x" * 5000,
        "nested": {"deep": {"deeper": {"deepest": {"further": "unreachable"}}}},
        "count": 500,
    })
    assert len(shrunk["files"]) == 9          # eight, plus the "and more" note
    assert "more" in shrunk["files"][-1]
    assert len(shrunk["text"]) <= 240
    assert shrunk["count"] == 500
    assert shrunk["nested"]["deep"]["deeper"]["deepest"] == "…"


def test_the_result_event_survives_a_failing_tool(brain):
    seen = []
    brain.events.subscribe("tool.result", lambda event: seen.append(event.data))
    run(brain.dispatch("productivity.complete_todo", {"task": "nothing like this"}))
    assert seen and seen[-1]["ok"] is False

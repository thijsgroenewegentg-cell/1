"""Offline routing: the keyword layer that works when Ollama is not running.

The router has two keyword layers that were maintained independently:
``INTENT_KEYWORDS`` picks a *module*, and each ``@tool`` declares keywords that
pick a *tool once the module is already chosen*. Nothing kept them in step, so
a phrase declared on a tool — "what did i copy" on ``system_control.clipboard``
— scored zero at the module level, fell through to ``conversation`` and failed
outright with the LLM offline. These tests pin the repair, and the guard that
stops it over-correcting into ordinary chit-chat.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from core.brain import Brain
from core.config import Config
from core.intent_router import GENERIC_TOOL_KEYWORDS, _keyword_matches
from tests.conftest import run


@pytest.fixture(scope="module")
def brain(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """A fully loaded brain, reused across the routing assertions."""
    root = tmp_path_factory.mktemp("router")
    config = Config.load("config.yaml")
    config.set("security.confirm_dangerous", False)
    config.set("memory.directory", str(root / "memory"))
    built = Brain(config)
    asyncio.run(built.initialize())
    yield built
    asyncio.run(built.shutdown())


def route(brain: Any, text: str) -> str:
    """The module the offline keyword router picks for ``text``."""
    return brain.router._keyword_intent(text).module


# --------------------------------------------------------------- the repair
@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("what did i copy", "system_control"),      # clipboard
        ("what's running", "system_control"),       # list_processes
        ("free space", "system_control"),           # disk_free
        ("the time", "system_control"),             # current_time
        ("silence the sound", "system_control"),    # mute
        ("move the mouse", "system_control"),       # mouse
        ("test this code", "code_assistant"),
        ("what's on today", "productivity"),        # daily_briefing
    ],
)
def test_tool_keywords_reach_their_own_module(brain: Any, utterance: str, expected: str) -> None:
    assert route(brain, utterance) == expected


def test_these_phrases_are_answerable_without_the_llm(brain: Any) -> None:
    """The whole point: no LLM, so falling back to conversation is a failure."""
    for utterance in ("what did i copy", "free space", "what's running"):
        assert route(brain, utterance) != "conversation"


# ------------------------------------------------- no regression on routing
@pytest.mark.parametrize(
    ("utterance", "expected"),
    [
        ("take a screenshot", "system_control"),
        ("what's the weather", "web_search"),
        ("set a timer for 10 minutes", "productivity"),
        ("remind me to call mum", "productivity"),
        ("organize my downloads", "file_manager"),
        ("translate hello to french", "smart_assistant"),
        ("latest news", "web_search"),
        ("list your plugins", "self_improve"),
        ("check my inbox", "communications"),
        ("index my documents", "knowledge"),
    ],
)
def test_established_routes_still_hold(brain: Any, utterance: str, expected: str) -> None:
    assert route(brain, utterance) == expected


# ------------------------------------------------------- chit-chat is spared
@pytest.mark.parametrize(
    "utterance",
    [
        "hello",
        "hi there",
        "how are you today",
        "thanks, that's great",
        "goodbye",
        "what do you think about jazz music",
        "tell me a joke",
        "who are you",
        "i'm feeling tired today",
        "that was funny",
        "do you like cats",          # 'cat' is a keyword on analyze_csv
        "what's your favourite colour",
        "good morning",
        "i had a long day",
    ],
)
def test_small_talk_is_not_hijacked_by_a_tool_keyword(brain: Any, utterance: str) -> None:
    assert route(brain, utterance) == "conversation"


# ------------------------------------------------- latency: skip the router LLM
def test_plain_chat_skips_the_classifier_model(brain: Any, monkeypatch: Any) -> None:
    """With the model online, keyword-silent small talk must not spend a full
    classifier round-trip before the reply — one model call is enough."""

    def should_not_be_called(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the classifier model was consulted for small talk")

    monkeypatch.setattr(brain.llm, "available", True)
    monkeypatch.setattr(brain.llm, "complete", should_not_be_called)
    intent = run(brain.router.classify("hello, how are you?"))
    assert intent.module == "conversation"
    assert intent.method == "keyword"


def test_instant_chat_can_be_turned_back_off(brain: Any, monkeypatch: Any) -> None:
    """``llm.instant_chat: false`` restores always asking the router model."""
    previous = brain.config.get("llm.instant_chat", True)
    brain.config.set("llm.instant_chat", False)

    def consulted(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("consulted (expected)")

    try:
        monkeypatch.setattr(brain.llm, "available", True)
        monkeypatch.setattr(brain.llm, "complete", consulted)
        with pytest.raises(AssertionError, match="consulted"):
            run(brain.router.classify("good morning"))
    finally:
        brain.config.set("llm.instant_chat", previous)


# ----------------------------------------------------- the matching rule itself
def test_short_keywords_need_a_word_boundary() -> None:
    # The bug: 'cat' matching inside 'cats' sent small talk to file_manager.
    # 'cat' is now generic as well, so use another short keyword to show the
    # boundary rule itself rather than the generic-word veto.
    assert not _keyword_matches("ram", " the program crashed ")
    assert not _keyword_matches("ram", " a rambling story ")
    assert _keyword_matches("ram", " how much ram is free ")
    assert _keyword_matches("ram", " check the ram. ")


def test_generic_short_keywords_are_vetoed_outright(brain: Any) -> None:
    # 'cat' is a keyword on file_manager.analyze_csv; it must never route.
    assert not _keyword_matches("cat", " do you like cats ")
    assert not _keyword_matches("cat", " show me the cat ")
    assert route(brain, "do you like cats") == "conversation"


def test_long_keywords_may_match_as_substrings() -> None:
    assert _keyword_matches("screenshot", " take a screenshot now ")
    assert _keyword_matches("clipboard", " check the clipboard ")


def test_generic_keywords_never_route_on_their_own() -> None:
    for keyword in ("open", "start", "tell me", "what's"):
        assert keyword in GENERIC_TOOL_KEYWORDS
        assert not _keyword_matches(keyword, f" {keyword} something ")


def test_blank_keywords_are_ignored() -> None:
    assert not _keyword_matches("", " anything ")
    assert not _keyword_matches("   ", " anything ")


# ----------------------------------------------------------------- the cache
def test_tool_keywords_are_grouped_by_owning_module(brain: Any) -> None:
    collected = brain.router._tool_keywords()
    assert "system_control" in collected
    assert "clipboard" in " ".join(collected["system_control"])
    # Every key must be a loaded module, or scoring would credit a phantom.
    assert set(collected).issubset(set(brain.modules))


def test_the_keyword_cache_is_reused(brain: Any) -> None:
    first = brain.router._tool_keywords()
    assert brain.router._tool_keywords() is first

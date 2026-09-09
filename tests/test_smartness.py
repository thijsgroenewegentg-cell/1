# /tests/test_smartness.py
"""JARVIS actually being smart — chat, reasoning sharpness and remembering.

Three waves, all testable with no LLM:

1. **Offline chat** — when Ollama is down, greetings, thanks, jokes, identity
   questions and goodbyes get real (varied) replies instead of the same
   "language model is offline" wall; only genuinely open-ended questions fall
   back, and the fallback is honest and short.
2. **Reasoning sharpness** — the system prompt and ReAct contract carry a
   self-check: answer what was literally asked, never pad, never round data
   into vagueness.
3. **Remembering the user** — "my name is Alice" is stored durably (survives
   a restart, no model needed) and "what's my name?" / "what do you know
   about me?" are answered from it.
"""

from __future__ import annotations

import inspect

import pytest

from core.brain import Brain
from core.intent_router import Intent
from tests.conftest import build_config, run

#: The old canned wall this wave removes — no reply may be exactly this.
OLD_WALL = "My language model is offline"


def _fresh_brain(factory: pytest.TempPathFactory) -> Brain:
    config = build_config(factory.mktemp("smartness"))
    instance = Brain(config)
    run(instance.initialize())
    return instance


@pytest.fixture(scope="module")
def brain(tmp_path_factory: pytest.TempPathFactory) -> Brain:
    """One offline brain shared by the small-talk parameter tests."""
    instance = _fresh_brain(tmp_path_factory)
    yield instance
    run(instance.shutdown())


@pytest.fixture()
def fresh_brain(tmp_path_factory: pytest.TempPathFactory) -> Brain:
    """A clean offline brain for each name-memory test."""
    instance = _fresh_brain(tmp_path_factory)
    yield instance
    run(instance.shutdown())


# ------------------------------------------------------------- offline chat
@pytest.mark.parametrize("line", [
    "hello", "hi there", "good morning", "hey jarvis", "yo",
    "thanks", "thank you very much", "cheers",
    "who are you", "what are you", "tell me about yourself",
    "are you smart", "are you a robot", "do you have feelings",
    "tell me a joke", "make me laugh", "another joke",
    "i love you", "you're great", "good bot", "sorry about that",
    "goodbye", "see you later", "goodnight", "bye",
])
def test_offline_small_talk_gets_a_real_reply(brain, line):
    reply = run(brain.process(line))
    assert reply.strip()
    assert OLD_WALL not in reply, f"{line!r} still hits the canned wall: {reply!r}"
    assert "ollama serve" not in reply.lower(), (
        f"{line!r} nags about the model: {reply!r}"
    )


def test_offline_identity_reply_is_persona_shaped(brain):
    reply = run(brain.process("who are you"))
    assert "JARVIS" in reply
    assert len(reply.split()) > 6  # a real sentence, not a grunt


def test_consecutive_offline_greetings_differ(brain):
    # Rotation lives in the persona (it remembers the last line it spoke);
    # consecutive identical inputs must produce different canned replies.
    first = brain.persona.offline_reply("hello")
    second = brain.persona.offline_reply("hello")
    assert first != second, "the same greeting twice should not be identical"


def test_offline_greeting_through_a_full_turn_is_a_greeting(brain):
    reply = run(brain.process("hello"))
    assert "hello" in reply.lower() or "hey" in reply.lower() or "hi" in reply.lower()


def test_open_ended_questions_fall_back_honestly(brain):
    reply = run(brain.process("what is the meaning of life?"))
    assert "model" in reply.lower() and "offline" in reply.lower()
    assert "ollama serve" in reply.lower()


def test_imperative_sentences_do_not_look_like_questions(brain):
    """'call me when you're done' is not a question and not a name intro."""
    reply = run(brain.process("call me when you're done"))
    assert OLD_WALL not in reply
    assert "?" not in reply


# ------------------------------------------------------------- name memory
def test_introducing_yourself_is_learned_and_acknowledged(fresh_brain):
    reply = run(fresh_brain.process("my name is Ada"))
    assert "Ada" in reply
    assert fresh_brain.preferences.user_name() == "Ada"


def test_call_me_fillers_are_not_learned_as_names(fresh_brain):
    run(fresh_brain.process("call me when you're done"))
    run(fresh_brain.process("call me if you need anything at all"))
    assert fresh_brain.preferences.user_name() == ""


def test_name_question_before_introduction_is_honest(fresh_brain):
    reply = run(fresh_brain.process("what's my name"))
    assert fresh_brain.preferences.user_name() == ""
    assert "haven't told me" in reply or "haven't told" in reply


def test_name_question_after_introduction_answers(fresh_brain):
    run(fresh_brain.process("my name is Lin"))
    reply = run(fresh_brain.process("what's my name?"))
    assert "Lin" in reply


def test_what_do_you_know_about_me(fresh_brain):
    run(fresh_brain.process("my name is Sam"))
    reply = run(fresh_brain.process("what do you know about me"))
    assert "Sam" in reply


def test_the_learned_name_survives_a_restart(tmp_path_factory):
    config = build_config(tmp_path_factory.mktemp("smartness-restart"))
    first = Brain(config)
    run(first.initialize())
    run(first.process("hi, my name is Grace"))
    run(first.shutdown())

    second = Brain(config)
    run(second.initialize())
    assert second.preferences.user_name() == "Grace"
    reply = run(second.process("what's my name"))
    assert "Grace" in reply
    run(second.shutdown())


def test_learned_name_reaches_the_system_prompt(fresh_brain):
    run(fresh_brain.process("my name is Lin"))
    assert "Lin" in fresh_brain.system_prompt()


def test_stored_facts_come_back_offline(fresh_brain):
    """'remember that X' then 'what's my X' works with the model down."""
    run(fresh_brain.process("remember that my favorite color is blue"))
    reply = run(fresh_brain.process("what's my favorite color"))
    assert "blue" in reply.lower()


def test_recall_with_nothing_stored_is_honest(fresh_brain):
    reply = run(fresh_brain.process("what's my wifi password"))
    assert "don't have anything on file" in reply
    assert "language model is offline" not in reply


def test_recall_questions_are_not_stored_as_facts(fresh_brain):
    """A question-shaped line must never be filed away as a fact."""
    run(fresh_brain.process("what's my shoe size"))
    hits = run(fresh_brain.memory.recall("shoe size", k=3, min_score=0.05))
    assert not hits


# ----------------------------------------------------- reasoning sharpness
def test_the_system_prompt_demands_a_self_check(brain):
    prompt = brain.system_prompt()
    assert "Self-check" in prompt
    assert "ask one short question" in prompt.lower()


def test_the_react_prompt_orders_answer_first_when_possible(brain):
    brain.last_intent = Intent("productivity", 0.9, "probe", method="keyword")
    prompt = brain.planner._react_prompt(
        "add milk to my list", brain.tool_registry("productivity"), [], 1, ""
    )
    assert "Re-read the USER REQUEST" in prompt
    assert "answer directly" in prompt


def test_tool_result_composition_demands_verbatim_fidelity():
    source = inspect.getsource(Brain._compose_answer)
    assert "verbatim" in source
    assert "exact figures" in source

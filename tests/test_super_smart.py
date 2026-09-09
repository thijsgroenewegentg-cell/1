# /tests/test_super_smart.py
"""The four 'super smart' capabilities, all verifiable with no LLM.

1. **Autopilot** — one-shot compound requests ("set a timer AND convert 5
   miles to kilometers") run across modules in a single pass instead of the
   second half being silently dropped by single-module routing.
2. **Learning from corrections** — "use miles instead of kilometers" becomes a
   durable standing rule in the profile, listed on demand and injected into
   the system prompt. Social noise ("don't worry about it") is never stored.
3. **Ask about your past** — "what did I say about X?" is answered from the
   session journal with dated, quoted receipts; empty topics are answered
   honestly.
4. **Failure autopsies** — "what went wrong?" reads the durable failure log
   and answers honestly, or reports a clean bill of health.
"""

from __future__ import annotations

import pytest

from core.brain import Brain
from tests.conftest import build_config, run


def _fresh(factory: pytest.TempPathFactory) -> Brain:
    config = build_config(factory.mktemp("super-smart"))
    instance = Brain(config)
    run(instance.initialize())
    return instance


@pytest.fixture()
def brain(tmp_path_factory: pytest.TempPathFactory) -> Brain:
    """A clean offline brain per test."""
    instance = _fresh(tmp_path_factory)
    yield instance
    run(instance.shutdown())


# ---------------------------------------------------------------- autopilot
def test_compound_request_runs_both_modules_offline(brain):
    reply = run(brain.process(
        "set a timer for 3 minutes and convert 5 miles to kilometers"
    ))
    assert "step(s)" in reply
    assert "Timer" in reply          # productivity ran
    assert "miles" in reply.lower() and "kilometer" in reply.lower()  # smart_assistant


def test_autopilot_skips_same_module_compounds(brain):
    """Two steps on one module stay single-module (existing path owns them)."""
    reply = run(brain.process(
        "remind me to call mom and set a timer for 5 minutes"
    ))
    assert "step(s)" not in reply.lower()


def test_autopilot_skips_chatty_compounds(brain):
    reply = run(brain.process("hello and thanks"))
    assert "step(s)" not in reply.lower()
    assert reply.strip()


def test_autopilot_plan_splitter_is_deterministic(brain):
    from core.autopilot import build

    plan = build(brain, "search the web for news and add a todo")
    assert plan is not None
    modules = [module for module, _ in plan]
    assert len(set(modules)) >= 2
    assert build(brain, "how are you and what's up") is None


# ------------------------------------------------------------- corrections
def test_a_correction_is_stored_and_listed(brain):
    reply = run(brain.process("never use the word dude"))
    assert "Understood" in reply
    assert "dude" in reply.lower()
    listed = run(brain.process("what did i correct you about"))
    assert "dude" in listed.lower()
    assert any("dude" in rule.lower() for rule in brain.preferences.corrections())


def test_social_noise_is_never_stored(brain):
    run(brain.process("don't worry about it"))
    assert brain.preferences.corrections() == []
    listed = run(brain.process("what rules have i taught you"))
    assert "haven't corrected" in listed


def test_duplicate_correction_is_reported(brain):
    run(brain.process("use miles instead of kilometers"))
    reply = run(brain.process("use miles instead of kilometers"))
    assert "Already on it" in reply


def test_corrections_reach_the_system_prompt(brain):
    run(brain.process("i prefer the metric system"))
    prompt = brain.system_prompt()
    assert "metric system" in prompt.lower()


# ------------------------------------------------------------------- autopsy
def test_a_logged_failure_is_answerable(brain):
    from core.failures import note_failure

    note_failure(
        brain.config, text="render the donut",
        error="Blender crashed: boom", module="blender",
    )
    reply = run(brain.process("what went wrong"))
    assert "boom" in reply
    assert "blender" in reply.lower() or "render" in reply.lower()


def test_clean_bill_of_health_when_nothing_failed(brain):
    reply = run(brain.process("have you been making mistakes"))
    assert "Clean bill" in reply


# ------------------------------------------------------------- past recall
def test_journal_receipts_answer_past_questions(brain):
    run(brain.process("remember that the budget meeting is on friday"))
    reply = run(brain.process("what did i say about the budget"))
    assert "budget" in reply.lower()
    assert "friday" in reply.lower()
    assert "you said" in reply


def test_past_recall_with_nothing_on_file_is_honest(brain):
    reply = run(brain.process("what did i say about the iphone"))
    assert "Nothing on record" in reply


def test_time_anchored_questions_do_not_hijack(brain):
    reply = run(brain.process("what did we talk about yesterday"))
    # Must not produce the fake "nothing on record about yesterday" autopsy
    # of the journal — it should fall through to the normal conversational
    # path (journal recap or small talk).
    assert "Nothing on record about \"yesterday\"" not in reply

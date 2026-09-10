# /tests/test_brain.py
"""Unit tests for core/brain.py and the pieces it delegates to.

The brain is built with no reachable LLM, so what is under test is the
keyword router, the module registry, the dispatcher, the personality layer
and the event bus — everything that has to keep working when Ollama is not
running.
"""

from __future__ import annotations

import json

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
from modules.base import ModuleResult
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
    """An offline turn must not wait on an embedding search to answer."""

    def should_not_be_called(*args: object, **kwargs: object) -> None:
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


@pytest.mark.parametrize(
    ("requested", "path", "is_order"),
    [
        ("edit your own code to be quicker", "", True),
        ("edit your code in core/brain.py to trim prefill", "core/brain.py", True),
        ("change your code in modules/base.py, please", "modules/base.py", True),
        ("edit it", "", True),
        ("don't edit your code today", "", False),
        ("explain your code to me", "", False),
        ("what files do you have", "", False),
    ],
)
def test_the_planner_recognises_explicit_self_edit_orders(
    requested, path, is_order
):
    """Self-edit orders skip the ReAct model's chance to answer in prose."""
    params = Planner._self_edit_request(requested)
    if not is_order:
        assert params is None
        return
    assert params is not None
    assert params["path"] == path
    assert params["instruction"] == requested


def test_a_no_file_self_edit_asks_which_file(brain, monkeypatch):
    """A no-file self-edit asks rather than editing the project root dir."""
    brain.config.set("memory.enabled", False)
    monkeypatch.setattr(brain.llm, "available", True)
    reply = run(brain.process("edit your code to make replies snappier"))
    assert "Point me at the file" in reply


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
    # The old wall named Ollama; the smarter offline fallback still explains
    # plainly that the language model is down and what still works.
    assert "model" in reply.lower() and "offline" in reply.lower()


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


# --------------------------------------------------- learned preferences
def test_learned_habits_reach_the_system_prompt(brain):
    brain.preferences.observe("blender.render",
                              {"animation": True, "samples": 128})
    brain.preferences.observe("blender.render",
                              {"animation": True, "samples": 128})
    prompt = brain.system_prompt()
    assert "has noticed about how" in prompt
    assert "the full animation" in prompt
    assert "128" in prompt


def test_dispatch_feeds_the_preferences_store(brain):
    run(brain.dispatch("productivity.add_todo", {"task": "water the basil"}))
    assert brain.preferences.tool_counts().get("productivity.add_todo") == 1


def test_failed_calls_are_not_learned_from(brain):
    result = run(brain.dispatch(
        "productivity.delete_todo", {"task_id": "999999"}
    ))
    assert not result.success
    assert "productivity.delete_todo" not in brain.preferences.tool_counts()


# --------------------------------------------------------------- plan confirm
def test_a_first_tool_that_names_an_unnamed_file_is_checked(brain, monkeypatch):
    """The model picked 'city.blend' though the user never said it — ask."""
    calls = []
    denied = {"answer": False}

    async def fake_confirm(question: str) -> bool:
        calls.append(question)
        return denied["answer"]

    brain.config.set("assistant.confirm_plan", True)
    monkeypatch.setattr(brain.security, "confirm_dangerous", True)
    monkeypatch.setattr(brain.llm, "available", True)
    monkeypatch.setattr(brain.security, "confirm", fake_confirm)

    dispatches = []

    async def fake_complete(prompt, system=None, temperature=None,
                            max_tokens=None, model=None, json_mode=False) -> str:
        return json.dumps({
            "thought": "open the file the user means",
            "action": "file_manager.read_file",
            "params": {"path": "~/Downloads/city.blend"},
            "answer": None,
        })

    async def fake_dispatch(reference, params) -> ModuleResult:
        dispatches.append((reference, params))
        return ModuleResult.ok("read")

    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    monkeypatch.setattr(brain, "dispatch", fake_dispatch)

    intent = Intent(module="file_manager", confidence=0.9, method="keyword")
    reply = run(brain._react("show me the scene from last week", intent, "", None))
    assert "Hold on" in reply
    assert "city.blend" in reply
    assert len(calls) == 1
    assert dispatches == []


def test_an_approved_plan_runs_the_tool(brain, monkeypatch):
    brain.config.set("assistant.confirm_plan", True)
    monkeypatch.setattr(brain.security, "confirm_dangerous", True)
    monkeypatch.setattr(brain.llm, "available", True)
    asked = []

    async def fake_confirm(question: str) -> bool:
        asked.append(question)
        return True

    monkeypatch.setattr(brain.security, "confirm", fake_confirm)
    dispatched = []

    async def fake_complete(prompt, system=None, temperature=None,
                            max_tokens=None, model=None, json_mode=False) -> str:
        if not dispatched:
            return json.dumps({
                "thought": "user approved the target",
                "action": "file_manager.read_file",
                "params": {"path": "~/Downloads/city.blend"},
                "answer": None,
            })
        return json.dumps({"thought": "done", "action": None, "params": {},
                           "answer": "Read it, sir."})

    async def fake_dispatch(reference, params) -> ModuleResult:
        dispatched.append((reference, params))
        return ModuleResult.ok("read it")

    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    monkeypatch.setattr(brain, "dispatch", fake_dispatch)

    intent = Intent(module="file_manager", confidence=0.9, method="keyword")
    reply = run(brain._react("show me the scene from last week", intent, "", None))
    assert reply == "Read it, sir."
    assert asked, "the plan should have been confirmed"
    assert dispatched == [("file_manager.read_file", {"path": "~/Downloads/city.blend"})]
def test_a_named_target_skips_the_plan_check(brain, monkeypatch):
    """The user said 'city.blend' themselves — no guess, no question."""
    brain.config.set("assistant.confirm_plan", True)
    monkeypatch.setattr(brain.security, "confirm_dangerous", True)
    monkeypatch.setattr(brain.llm, "available", True)
    asked = []

    async def fake_confirm(question: str) -> bool:
        asked.append(question)
        return True

    monkeypatch.setattr(brain.security, "confirm", fake_confirm)
    dispatched = []

    async def fake_complete(prompt, system=None, temperature=None,
                            max_tokens=None, model=None, json_mode=False) -> str:
        if not dispatched:
            return json.dumps({
                "thought": "exactly what the user named",
                "action": "file_manager.read_file",
                "params": {"path": "~/Downloads/city.blend"},
                "answer": None,
            })
        return json.dumps({"thought": "done", "action": None, "params": {},
                           "answer": "Read it, sir."})

    async def fake_dispatch(reference, params) -> ModuleResult:
        dispatched.append((reference, params))
        return ModuleResult.ok("read it")

    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    monkeypatch.setattr(brain, "dispatch", fake_dispatch)

    intent = Intent(module="file_manager", confidence=0.9, method="keyword")
    reply = run(brain._react("read ~/Downloads/city.blend for me", intent, "", None))
    assert reply == "Read it, sir."
    assert not asked, "the user named the target — nothing to ask"
    assert dispatched == [("file_manager.read_file", {"path": "~/Downloads/city.blend"})]
def test_confirmations_off_means_no_plan_check(brain, monkeypatch):
    """confirm_dangerous: false trusts the plan; the gate stays silent."""
    brain.config.set("assistant.confirm_plan", True)
    monkeypatch.setattr(brain.security, "confirm_dangerous", False)
    monkeypatch.setattr(brain.llm, "available", True)
    asked = []

    async def fake_confirm(question: str) -> bool:
        asked.append(question)
        return True

    monkeypatch.setattr(brain.security, "confirm", fake_confirm)
    dispatched = []

    async def fake_complete(prompt, system=None, temperature=None,
                            max_tokens=None, model=None, json_mode=False) -> str:
        return json.dumps({
            "thought": "just run it",
            "action": "file_manager.read_file",
            "params": {"path": "~/Downloads/city.blend"},
            "answer": None,
        })

    async def fake_dispatch(reference, params) -> ModuleResult:
        dispatched.append((reference, params))
        return ModuleResult.ok("read it")

    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    monkeypatch.setattr(brain, "dispatch", fake_dispatch)
    async def fake_compose(text, obs, mem, on_token=None) -> str:
        return "Read it, sir."

    monkeypatch.setattr(brain, "_compose_answer", fake_compose)

    intent = Intent(module="file_manager", confidence=0.9, method="keyword")
    run(brain._react("show me the scene from last week", intent, "", None))
    assert not asked
    assert dispatched


# --------------------------------------------------------- fast/deep models
def test_routine_chat_uses_the_fast_model(brain, monkeypatch):
    brain.llm.fast_model = "tiny-chat"
    seen = {}

    async def fake_chat(messages, temperature=None, max_tokens=None,
                        model=None, json_mode=False) -> str:
        seen["model"] = model
        return "Hello yourself, sir."

    monkeypatch.setattr(brain.llm, "available", True)
    monkeypatch.setattr(brain.llm, "chat", fake_chat)
    reply = run(brain._converse("hello", ""))
    assert reply == "Hello yourself, sir."
    assert seen["model"] == "tiny-chat"


def test_an_unparseable_decision_gets_one_deep_model_retry(brain, monkeypatch):
    brain.llm.deep_model = "big-brain"
    models = []

    async def fake_complete(prompt, system=None, temperature=None,
                            max_tokens=None, model=None, json_mode=False) -> str:
        models.append(model)
        if len(models) == 1:
            return "this is not json at all"
        return json.dumps({"thought": "second try", "action": None,
                           "params": {}, "answer": "Sorted, sir."})

    monkeypatch.setattr(brain.llm, "available", True)
    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    intent = Intent(module="productivity", confidence=0.9, method="keyword")
    reply = run(brain._react("sort my day out", intent, "", None))
    assert reply == "Sorted, sir."
    assert models == [None, "big-brain"], "one retry on the deep model expected"


def test_a_failed_tool_moves_the_next_step_to_the_deep_model(brain, monkeypatch):
    brain.llm.deep_model = "big-brain"
    models = []

    async def fake_complete(prompt, system=None, temperature=None,
                            max_tokens=None, model=None, json_mode=False) -> str:
        models.append(model)
        if len(models) == 1:
            return json.dumps({
                "thought": "delete it",
                "action": "productivity.delete_todo",
                "params": {"task_id": "999999"}, "answer": None,
            })
        return json.dumps({"thought": "that failed, list instead",
                           "action": "productivity.list_todos", "params": {},
                           "answer": None})

    monkeypatch.setattr(brain.llm, "available", True)
    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    async def fake_compose(text, obs, mem, on_token=None) -> str:
        return "Recovered, sir."

    monkeypatch.setattr(brain, "_compose_answer", fake_compose)
    intent = Intent(module="productivity", confidence=0.9, method="keyword")
    reply = run(brain._react("fix my todos", intent, "", None))
    assert reply == "Recovered, sir."
    assert models[0] is None
    assert "big-brain" in models[1:]


def test_deep_retry_stays_off_when_no_deep_model_is_configured(brain, monkeypatch):
    """Garbage on the main model falls back — it is not 'escalated' to nobody."""
    react_models = []

    async def fake_complete(prompt, system=None, temperature=None,
                            max_tokens=None, model=None, json_mode=False) -> str:
        if "reasoning core" in prompt:
            react_models.append(model)
        return "still not json"

    monkeypatch.setattr(brain.llm, "available", True)
    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    intent = Intent(module="productivity", confidence=0.9, method="keyword")
    run(brain._react("sort my day out", intent, "", None))
    assert react_models == [None], "no deep model configured — no retry"
def test_boot_status_is_a_local_sentence(brain):
    status = brain.boot_status()
    assert "All systems online" in status
    assert "modules" in status


def test_boot_status_never_waits_on_the_model(brain, monkeypatch):
    """The boot line is instant and local — a silent audio pipe must show at once."""

    def should_not_be_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("boot_status must not call the LLM")

    monkeypatch.setattr(brain.llm, "complete", should_not_be_called)
    assert "All systems online" in brain.boot_status()


def test_morning_brief_always_returns_speechable_text(brain):
    brief = run(brain.morning_brief(timeout=5.0))
    assert isinstance(brief, str) and brief.strip()


def test_instant_actions_get_no_acknowledgment(brain):
    assert brain._ack_line("productivity") == ""
    assert brain._ack_line("system_control") == ""


def test_slower_tasks_get_a_short_acknowledgment(brain):
    line = brain._ack_line("web_search")
    assert line
    assert "…" in line or "..." in line


def test_the_acknowledgment_follows_dutch(brain):
    brain.config.set("assistant.language", "nl")
    assert "zoek" in brain._ack_line("web_search").lower()


def test_a_search_turn_emits_an_ack_event(brain):
    seen = []
    brain.events.subscribe("turn.ack", lambda event: seen.append(event.data))
    run(brain.process("search the web for rust iterators"))
    assert seen
    assert seen[0].get("text")


def test_the_model_is_not_overruled_by_a_keyword_guess(brain, monkeypatch):
    """When Ollama is up, a hesitant model still picks the module."""
    brain.llm.available = True
    monkeypatch.setattr(
        brain.router,
        "_keyword_intent",
        lambda text: Intent("system_control", 0.9, "keyword guess", method="keyword"),
    )

    async def fake_complete(prompt, **kwargs):
        assert "Keyword hint" in prompt
        return json.dumps({"module": "web_search", "confidence": 0.55, "reason": "needs live data"})

    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    intent = run(brain.router.classify("what is going on with memory prices"))
    assert intent.module == "web_search"
    assert intent.method == "llm"


def test_the_planner_thinks_again_after_a_tool(brain, monkeypatch):
    """A successful system_control call used to end the loop without a think."""
    brain.llm.available = True
    calls: list[str] = []

    async def fake_complete(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps({
                "thought": "need the clock",
                "action": "system_control.current_time",
                "params": {},
                "answer": None,
            })
        return json.dumps({
            "thought": "observation is enough",
            "action": None,
            "params": {},
            "answer": "It is tea time.",
        })

    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    intent = Intent("system_control", 0.9, "clock", method="llm")
    reply = run(brain.planner.run("what time is it", intent, "", None))
    assert len(calls) >= 2
    assert "Observation:" in calls[1]
    assert "tea time" in reply.lower()


def test_the_planner_does_not_repeat_an_identical_call(brain, monkeypatch):
    brain.llm.available = True
    prompts: list[str] = []

    async def fake_complete(prompt, **kwargs):
        prompts.append(prompt)
        if len(prompts) <= 2:
            return json.dumps({
                "thought": "try the clock",
                "action": "system_control.current_time",
                "params": {},
                "answer": None,
            })
        return json.dumps({
            "thought": "done",
            "action": None,
            "params": {},
            "answer": "Enough.",
        })

    monkeypatch.setattr(brain.llm, "complete", fake_complete)
    intent = Intent("system_control", 0.9, "clock", method="llm")
    reply = run(brain.planner.run("what time is it", intent, "", None))
    assert "Enough" in reply
    assert any("already made" in prompt for prompt in prompts[1:])


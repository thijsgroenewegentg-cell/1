# /tests/test_function_calling.py
"""The tool-usage curriculum (core/toolcraft) stays true to the real routers.

Every corpus row teaches the model a ``phrase -> module.tool`` mapping. This
suite replays the corpus through the *deterministic* layers — intent keyword
routing, module offline routers, keyword tool picking — and enforces exactly
the promises the curriculum file makes:

* every row names a module and tool that really exist;
* ``offline: "module"`` rows reach their module with no model;
* ``offline: "tool"`` rows reach module AND tool with no model.

Fixing a routing bug is one side of training the assistant to use his tools;
this suite is the other — it stops the routers drifting away from what the
model is being taught. ``scripts/eval_function_calling.py`` prints the same
scoreboard for a human.
"""

from __future__ import annotations

import pytest

from core.brain import Brain
from core.toolcraft import EXAMPLES
from tests.conftest import build_config, run


@pytest.fixture(scope="module")
def brain(tmp_path_factory: pytest.TempPathFactory) -> Brain:
    """One offline brain, shared across the whole corpus replay."""
    config = build_config(tmp_path_factory.mktemp("function-calling"))
    instance = Brain(config)
    run(instance.initialize())
    yield instance
    run(instance.shutdown())


def _offline_tool(brain: Brain, module: str, phrase: str) -> str:
    """Mirror the planner's no-model chain: router first, keywords second."""
    target = brain.modules[module]
    routed = target.offline_router(phrase)
    if routed:
        return str(routed[0])
    picked = target._keyword_pick(phrase)
    return str(picked[0]) if picked else ""


def test_every_corpus_row_names_a_real_module_and_tool(brain):
    missing = []
    for row in EXAMPLES:
        module = str(row["module"])
        tool = str(row["tool"])
        if module not in brain.modules or tool not in brain.modules[module].tools:
            missing.append(f"{module}.{tool} <- {row['phrase']!r}")
    assert not missing, f"corpus names tools that do not exist: {missing}"


@pytest.mark.parametrize(
    "row",
    [row for row in EXAMPLES if row.get("offline") in ("module", "tool")],
    ids=lambda row: f"{row['module']}.{row['tool']}",
)
def test_offline_module_promises_hold(brain, row):
    intent = brain._keyword_intent(str(row["phrase"]))
    assert intent.module == str(row["module"]), (
        f"{row['phrase']!r} promised module {row['module']} but routed to "
        f"{intent.module} without a model"
    )


@pytest.mark.parametrize(
    "row",
    [row for row in EXAMPLES if row.get("offline") == "tool"],
    ids=lambda row: f"{row['module']}.{row['tool']}",
)
def test_offline_tool_promises_hold(brain, row):
    chosen = _offline_tool(brain, str(row["module"]), str(row["phrase"]))
    assert chosen == str(row["tool"]), (
        f"{row['phrase']!r} promised {row['module']}.{row['tool']} but the "
        f"no-model chain picked {chosen or '(nothing)'}"
    )


def test_worked_examples_skip_the_users_own_phrase():
    from core.toolcraft import worked_examples

    shown = worked_examples("productivity", exclude_text="add buy milk to my todo list")
    assert shown
    assert all("add buy milk to my todo list" not in phrase for phrase, _ in shown)
    for _phrase, call in shown:
        assert "action" in call and "params" in call


def test_worked_examples_exist_for_the_main_modules(brain):
    from core.toolcraft import worked_examples

    for module in ("productivity", "file_manager", "system_control",
                   "web_search", "smart_assistant"):
        assert worked_examples(module), f"no teaching examples for {module}"


def test_the_golden_rules_render():
    from core.toolcraft import golden_block

    text = golden_block()
    assert "parameters verbatim" in text
    assert "never repeat" in text.lower() or "repeat" in text.lower()


def test_module_guidance_names_only_real_tools(brain):
    """Cross-module tool references in the guidance must exist.

    Prose like "open_url, not open_app" stays bare (no dot) and is not
    checked; qualified names like ``file_manager.summarize_document`` must
    point at a real tool or the model learns a call that can never work.
    """
    import re

    from core.toolcraft import MODULE_GUIDANCE

    known = set(brain.modules)
    # memory is a pseudo-module: the brain routes its tools directly.
    memory_tools = {"remember", "store", "save", "recall", "search", "query",
                    "forget", "delete"}
    for module, guidance in MODULE_GUIDANCE.items():
        assert module in brain.modules or module == "memory", (
            f"guidance for unknown module {module}"
        )
        for mention in re.findall(r"[a-z_]+\.[a-z_]+", guidance):
            owner, _, leaf = mention.partition(".")
            if owner not in known and owner != "memory":
                continue  # report.pdf is a filename, not a tool reference
            real = (memory_tools if owner == "memory"
                    else set(brain.modules[owner].tools))
            assert leaf in real, (
                f"{module} guidance mentions {mention}, which is not a real "
                f"tool on {owner}"
            )

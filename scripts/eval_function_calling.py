# /scripts/eval_function_calling.py
"""Score how well the offline router chain maps speech onto the right function.

Run it after touching any tool, keyword, offline router or the curriculum::

    python scripts/eval_function_calling.py

It replays the corpus from :mod:`core.toolcraft` — the same phrases the model
is shown as worked examples — through the deterministic layers (intent
keywords, module offline routers, keyword tool picking) and prints a table of
what routes where, plus the accuracy each module promises. Rows marked
``offline: "tool"`` in the corpus must reach module AND tool with no model;
``offline: "module"`` only promises the module. The hard promises are locked
in by ``tests/test_function_calling.py``; this script is the human-readable
scoreboard.

Online (LLM) accuracy is not measured here — no Ollama in tests — but every
``offline: "tool"`` row that passes is one less thing a small model can get
wrong, and the worked examples teach it the rest.
"""

from __future__ import annotations

import asyncio
import copy
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.brain import Brain  # noqa: E402
from core.config import DEFAULT_CONFIG, Config  # noqa: E402
from core.toolcraft import corpus_rows  # noqa: E402

#: A port nothing listens on, so every LLM call fails fast (offline eval).
DEAD_LLM_HOST = "http://127.0.0.1:59999"


def _offline_tool(brain: Brain, module_name: str, phrase: str) -> Optional[str]:
    """What tool the no-model chain picks for a phrase inside one module."""
    module = brain.modules.get(module_name)
    if module is None:
        return None
    try:
        router = getattr(module, "offline_router", None)
        if callable(router):
            picked = router(phrase)
            if picked:
                return str(picked[0])
        keyword = getattr(module, "_keyword_pick", None)
        if callable(keyword):
            chosen = keyword(phrase)
            if chosen:
                return str(chosen[0])
    except Exception:
        return None
    return None


def _build_offline_brain() -> Brain:
    """Boot an assistant rooted in a throwaway directory, no model."""
    data = copy.deepcopy(DEFAULT_CONFIG)
    data["llm"]["host"] = DEAD_LLM_HOST
    root = Path(tempfile.mkdtemp(prefix="jarvis-eval-"))
    data["paths"] = {"data": str(root / "data"), "logs": str(root / "data" / "logs"),
                     "backups": str(root / "data" / "backups"),
                     "screenshots": str(root / "data" / "screenshots"),
                     "knowledge": str(root / "data" / "knowledge")}
    data["database"] = {"path": str(root / "data" / "jarvis.db")}
    data["memory"]["path"] = str(root / "data" / "chroma")
    data["voice"]["enabled"] = False
    data["security"]["confirm_dangerous"] = False
    config = Config(data=data, path=root / "config.yaml")
    config.ensure_directories()
    return Brain(config)


def evaluate(brain: Brain) -> Dict[str, Any]:
    """Replay the corpus against the offline chain.

    Args:
        brain: An offline, initialised brain.

    Returns:
        Per-row results plus overall tallies.
    """
    rows: List[Dict[str, Any]] = []
    modules: Dict[str, Dict[str, int]] = {}
    tool_promises = 0
    module_promises = 0

    for row in corpus_rows():
        phrase = str(row["phrase"])
        expected_module = str(row["module"])
        expected_tool = str(row["tool"])
        promise = str(row.get("offline", "") or "")
        intent = brain._keyword_intent(phrase)
        module_hit = intent.module == expected_module
        tool_hit = None
        if promise == "tool" and module_hit:
            tool_hit = _offline_tool(brain, expected_module, phrase) == expected_tool
            if tool_hit:
                tool_promises += 1
        if promise == "module":
            module_promises += 1
        bucket = modules.setdefault(expected_module, {"module": 0, "tool": 0})
        if module_hit:
            bucket["module"] += 1
        if tool_hit:
            bucket["tool"] += 1
        rows.append({
            "phrase": phrase, "module": expected_module, "tool": expected_tool,
            "promise": promise, "module_hit": module_hit,
            "tool_hit": tool_hit, "routed_to": intent.module,
        })
    return {"rows": rows, "modules": modules,
            "tool_promises": tool_promises, "module_promises": module_promises}


def render(results: Dict[str, Any]) -> str:
    """Format the scoreboard for the terminal.

    Args:
        results: The dict returned by :func:`evaluate`.

    Returns:
        A readable report.
    """
    rows = results["rows"]
    promised = [row for row in rows if row["promise"] == "tool"]
    module_rows = [row for row in rows if row["promise"] in ("tool", "module")]
    module_ok = sum(1 for row in module_rows if row["module_hit"])
    tool_ok = sum(1 for row in promised if row["tool_hit"])
    lines: List[str] = [
        "function-calling corpus — offline routing scoreboard",
        "",
        f"module route:    {module_ok}/{len(module_rows)} "
        f"({100.0 * module_ok / len(module_rows):.0f}%)  [rows promising "
        f"offline module or tool routing]",
        f"tool route:      {tool_ok}/{len(promised)} "
        f"({100.0 * tool_ok / len(promised):.0f}%)  [rows promising "
        "offline module+tool routing]",
        "",
        "by module (module promises hit / tool promises hit):",
    ]
    for name in sorted(results["modules"]):
        counts = results["modules"][name]
        lines.append(f"  {name:<18} module {counts['module']:>3}   tool {counts['tool']:>3}")
    lines.append("")
    problems = [row for row in module_rows if not row["module_hit"]]
    problems += [row for row in promised if row["tool_hit"] is False]
    if not problems:
        lines.append("all promised routes pass offline.")
    else:
        lines.append("promised routes that FAIL offline:")
        for row in problems:
            lines.append(
                f"  {row['phrase']!r}"
                f"\n    wanted {row['module']}.{row['tool']} (promise "
                f"{row['promise']}) -> module {row['routed_to']}"
            )
    return "\n".join(lines)


def main() -> int:
    """Run the evaluation against a throwaway offline assistant.

    Returns:
        Process exit code (always 0; the table shows what passes).
    """
    brain = _build_offline_brain()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(brain.initialize())
        results = evaluate(brain)
    finally:
        try:
            loop.run_until_complete(brain.shutdown())
        finally:
            loop.close()
    print(render(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

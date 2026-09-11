"""Run MARK's dependency-free local capability benchmark.

The benchmark intentionally does not call Ollama, open a browser, start MCP,
or execute a tool. It checks routing contracts, safety boundaries, recovery
semantics, memory influence, Blender planning and hallucination regressions.
Use ``python -m evaluation.benchmark`` from the repository root.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.approval_policy import assess_tool
from core.blender_workflows import build_plan, render_plan
from core.evaluation import EvaluationCase, evaluate_trace
from core.tool_contracts import normalize_result
from memory.memory_manager import format_memory_for_prompt
from plugins.blender_control import _blocked_tool
from core.blender_bridge import configuration_error, connection_status
from core.agent_orchestrator import analyze_request, build_preview
from core.i18n import detect_language, edge_voice


@dataclass
class BenchmarkResult:
    area: str
    name: str
    passed: bool
    detail: str


def _check(area: str, name: str, fn: Callable[[], str | bool]) -> BenchmarkResult:
    try:
        value = fn()
        return BenchmarkResult(area, name, bool(value), "ok" if value is True else str(value))
    except Exception as exc:
        return BenchmarkResult(area, name, False, f"exception: {exc}")


def run_benchmark() -> list[BenchmarkResult]:
    rows: list[BenchmarkResult] = []
    rows.append(_check("tool_accuracy", "read-only policy classification", lambda: assess_tool("system_status", {}).risk == "read_only"))
    rows.append(_check("tool_accuracy", "Blender mutation is not read-only", lambda: assess_tool("blender_control", {"action": "set_transform"}).risk != "read_only"))
    rows.append(_check("safety", "arbitrary Blender Python remains blocked", lambda: _blocked_tool("execute_python") and _blocked_tool("run_code")))
    rows.append(_check("safety", "Blender bridge rejects non-loopback host", lambda: configuration_error({"host": "192.168.1.4", "port": 9876, "launcher": "uvx"}) is not None))
    rows.append(_check("recovery", "failed mutation is never reported as changed", lambda: (not normalize_result("Blender MCP tool failed: timeout", "blender_control", {"action": "set_transform"}).ok) and not normalize_result("Blender MCP tool failed: timeout", "blender_control", {"action": "set_transform"}).changed))
    rows.append(_check("recovery", "confirmation remains pending", lambda: normalize_result("[CONFIRMATION_PENDING] confirm on HUD", "file_controller", {"action": "write"}).status == "waiting_confirmation"))
    memory_fixture = {"identity": {"name": {"value": "Ada", "source": "conversation", "scope": "personal"}}, "preferences": {"tone": {"value": "concise", "source": "explicit_user", "scope": "global", "confidence": "high"}}, "temporary": {"old": {"value": "stale", "expires": "2000-01-01"}}}
    rows.append(_check("memory", "explicit preferences show provenance", lambda: "explicit user preferences" in format_memory_for_prompt(memory_fixture).lower() and "explicit_user" in format_memory_for_prompt(memory_fixture)))
    rows.append(_check("memory", "expired temporary memory is not prompt influence", lambda: "stale" not in format_memory_for_prompt(memory_fixture)))
    plan = build_plan("make a cinematic preview")
    rows.append(_check("blender", "high-level plan has confirmation and verification", lambda: bool(plan.confirmation_points and plan.verification and "confirmation" in render_plan(plan).lower())))
    rows.append(_check("hallucination", "failed tool cannot look successful", lambda: not normalize_result({"ok": False, "summary": "No changes were made"}, "tool").ok))
    rows.append(_check("hallucination", "evaluation harness catches forbidden calls", lambda: not evaluate_trace(EvaluationCase("safe", "safe", expected_tools=("inspect",), forbidden_tools=("shell",)), [{"tool": "shell"}]).passed))
    rows.append(_check("orchestration", "Dutch multi-step preflight is bounded", lambda: analyze_request("Open Blender en maak daarna een productfoto", "auto").requires_plan))
    rows.append(_check("orchestration", "dry-run preview is non-mutating", lambda: "no change was made" in build_preview("blender_control", {"action": "render"}, analyze_request("render", "en")).lower()))
    rows.append(_check("language", "Dutch speech voice is native", lambda: detect_language("Verbind met Blender alsjeblieft") == "nl" and edge_voice("nl", "Fenna") == "nl-NL-FennaNeural"))
    rows.append(_check("blender", "connection state remains loopback", lambda: connection_status().get("port") == 9876 and connection_status().get("host") in {"127.0.0.1", "localhost", "::1"}))
    return rows


def render(results: list[BenchmarkResult]) -> str:
    passed = sum(item.passed for item in results)
    lines = [f"MARK local benchmark: {passed}/{len(results)} passed"]
    for item in results:
        lines.append(f"- [{ 'PASS' if item.passed else 'FAIL' }] {item.area}/{item.name}: {item.detail}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    results = run_benchmark()
    print(render(results))
    output = next((arg.split("=", 1)[1] for arg in argv if arg.startswith("--json=")), "")
    if output:
        path = Path(output).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([item.__dict__ for item in results], indent=2), encoding="utf-8")
    return 0 if all(item.passed for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

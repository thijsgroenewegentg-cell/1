# /tests/test_smoke.py
"""End-to-end smoke tests for JARVIS.

Runs the whole stack twice — once with no LLM at all (degraded mode) and once
against a scripted mock Ollama server — so every routing path is exercised
without downloading a model.

Run with::

    python tests/test_smoke.py
    # or, if pytest is installed:
    pytest tests/test_smoke.py
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.brain import Brain  # noqa: E402
from core.config import Config  # noqa: E402
from modules.smart_assistant import safe_eval  # noqa: E402
from tests.mock_ollama import serve  # noqa: E402
from utils.helpers import extract_json, parse_duration, parse_when  # noqa: E402
from utils.security import RiskLevel, SecurityGuard  # noqa: E402

PASSED: List[str] = []
FAILED: List[Tuple[str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    """Record a single assertion result."""
    if condition:
        PASSED.append(name)
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAILED.append((name, detail))
        print(f"  \033[31m✗\033[0m {name} — {detail}")


def free_port() -> int:
    """Find an unused TCP port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_config(root: Path, llm_host: str) -> Config:
    """Build an isolated configuration rooted in a temp directory."""
    config = Config(
        {
            "llm": {"host": llm_host, "model": "llama3.2", "timeout": 20},
            "memory": {"path": "chroma", "auto_extract_facts": False},
            "database": {"path": "jarvis.db"},
            "voice": {"enabled": False},
            "logging": {"level": "WARNING", "file": ""},
            "security": {"confirm_dangerous": False},
            "paths": {
                "data": "data", "logs": "logs", "notes": "notes", "code": "code",
                "screenshots": "shots", "downloads": "dl", "tts_cache": "tts",
            },
        },
        path=root / "config.yaml",
    )
    config.root = root
    config.ensure_directories()
    return config


# ---------------------------------------------------------------------------
# Unit-level checks
# ---------------------------------------------------------------------------


def test_helpers() -> None:
    """Pure helper functions."""
    print("\n[helpers]")
    check("parse_duration('10 minutes')", parse_duration("10 minutes") == 600)
    check("parse_duration('1h30m')", parse_duration("1h30m") == 5400)
    check("parse_when('in 5 minutes')", parse_when("in 5 minutes") is not None)
    check("parse_when('at 5pm')", parse_when("at 5pm") is not None)
    check(
        "extract_json from fenced text",
        extract_json('noise ```json\n{"a": 1}\n``` more') == {"a": 1},
    )
    check("safe_eval arithmetic", safe_eval("(3+4)*2") == 14)
    check("safe_eval maths fn", abs(safe_eval("sqrt(144)") - 12) < 1e-9)
    try:
        safe_eval("__import__('os').system('echo hi')")
        check("safe_eval blocks imports", False, "no exception raised")
    except Exception:
        check("safe_eval blocks imports", True)


def test_security() -> None:
    """Risk classification."""
    print("\n[security]")
    guard = SecurityGuard(confirm_dangerous=True)
    check("rm -rf / is blocked", guard.assess("rm -rf /").level is RiskLevel.BLOCKED)
    check("fork bomb blocked", guard.assess(":(){ :|:& };:").level is RiskLevel.BLOCKED)
    check("sudo is dangerous", guard.assess("sudo apt update").level is RiskLevel.DANGEROUS)
    check("curl is caution", guard.assess("curl https://example.com").level is RiskLevel.CAUTION)
    check("ls is safe", guard.assess("ls -la").level is RiskLevel.SAFE)
    check(
        "protected path refused",
        guard.is_path_allowed("/etc", write=True).level
        in (RiskLevel.BLOCKED, RiskLevel.DANGEROUS),
    )


# ---------------------------------------------------------------------------
# Integration checks
# ---------------------------------------------------------------------------


async def test_degraded(root: Path) -> None:
    """Everything must still work with no LLM reachable."""
    print("\n[degraded mode — no LLM]")
    config = make_config(root / "degraded", "http://127.0.0.1:1")  # nothing listening
    brain = Brain(config)
    await brain.initialize()

    check("modules loaded", len(brain.modules) == 6, f"got {len(brain.modules)}")
    check("llm reports offline", brain.llm.available is False)

    cases = [
        ("what time is it", "system_control", ("20", "19", ":")),
        ("add buy milk to my todo list", "productivity", ("Added task",)),
        ("what are my tasks", "productivity", ("buy milk",)),
        ("set a timer for 3 minutes", "productivity", ("Timer",)),
        ("calculate 15% of 240", "smart_assistant", ("36",)),
        ("convert 10 miles to km", "smart_assistant", ("16.09",)),
        ("system stats", "system_control", ("CPU",)),
        ("take a note: the wifi password is hunter2", "productivity", ("Note",)),
    ]
    for text, expected_module, needles in cases:
        reply = await brain.process(text)
        routed = brain.last_intent.module if brain.last_intent else "?"
        check(
            f"route {text!r} -> {expected_module}",
            routed == expected_module,
            f"routed to {routed}",
        )
        check(
            f"answer {text!r}",
            any(needle in reply for needle in needles),
            f"reply={reply[:120]!r}",
        )

    remembered = await brain.memory.remember("The user drinks oat milk", category="preference")
    check("memory write", remembered)
    hits = await brain.memory.recall("what milk does the user drink", min_score=0.0)
    check("memory recall", bool(hits), "no hits returned")

    await brain.shutdown()


async def test_with_mock_llm(root: Path, host: str) -> None:
    """The full LLM pipeline against a scripted Ollama."""
    print("\n[with mock LLM]")
    config = make_config(root / "mock", host)
    brain = Brain(config)
    await brain.initialize()

    check("llm online", brain.llm.available, "client says offline")
    check("model resolved", brain.llm.model.startswith("llama3.2"), brain.llm.model)

    intent = await brain.classify("what time is it")
    check("llm classification", intent.module == "system_control" and intent.method == "llm",
          f"{intent.module}/{intent.method}")

    reply = await brain.process("what time is it")
    check("react loop produced a reply", len(reply) > 5, reply[:80])

    reply = await brain.process("tell me a joke about compilers")
    check("conversation path", "mock response" in reply.lower(), reply[:80])

    result = await brain.dispatch("system_control.current_time", {})
    check("direct dispatch", result.success and bool(result.output))

    result = await brain.dispatch("memory.remember", {"text": "user likes dark mode"})
    check("memory tool dispatch", result.success)

    result = await brain.dispatch("nonexistent.tool", {})
    check("unknown tool fails gracefully", not result.success and "No such tool" in result.output)

    status = await brain.status_report()
    check("status report", status["llm"]["online"] and status["modules"])

    await brain.shutdown()


async def test_modules(root: Path) -> None:
    """Direct tool calls on individual modules."""
    print("\n[modules]")
    config = make_config(root / "modules", "http://127.0.0.1:1")

    from modules.code_assistant import CodeAssistant
    from modules.file_manager import FileManager
    from modules.productivity import Productivity
    from modules.smart_assistant import SmartAssistant
    from modules.system_control import SystemControl

    system = SystemControl(config)
    result = await system.call_tool("current_time", {})
    check("system_control.current_time", result.success)
    result = await system.call_tool("system_stats", {})
    check("system_control.system_stats", result.success and "CPU" in result.output)
    result = await system.call_tool("run_shell", {"command": "echo hello"})
    check("system_control.run_shell", result.success and "hello" in result.output)

    code = CodeAssistant(config)
    result = await code.call_tool(
        "run_python", {"code": "print(sum(range(10)))", "timeout": 15}
    )
    check("code_assistant.run_python", result.success and "45" in result.output, result.output[:80])
    result = await code.call_tool(
        "save_code", {"filename": "demo.py", "code": "print('hi')", "language": "python"}
    )
    check("code_assistant.save_code", result.success and Path(result.data["path"]).exists())

    files = FileManager(config)
    sample = Path(result.data["path"]).parent
    result = await files.call_tool("find_files", {"pattern": "*.py", "path": str(sample)})
    check("file_manager.find_files", result.success and "demo.py" in result.output)
    result = await files.call_tool("folder_stats", {"path": str(sample)})
    check("file_manager.folder_stats", result.success)

    smart = SmartAssistant(config)
    result = await smart.call_tool("calculate", {"expression": "2**10 + 24"})
    check("smart_assistant.calculate", result.success and "1,048" in result.output,
          result.output[:60])
    result = await smart.call_tool(
        "convert", {"value": 100, "from_unit": "celsius", "to_unit": "fahrenheit"}
    )
    check("smart_assistant.convert temp", result.success and "212" in result.output,
          result.output[:60])

    productivity = Productivity(config)
    result = await productivity.call_tool("add_todo", {"task": "test task", "priority": "high"})
    check("productivity.add_todo", result.success)
    result = await productivity.call_tool("list_todos", {})
    check("productivity.list_todos", result.success and "test task" in result.output)
    result = await productivity.call_tool("complete_todo", {"task": "test task"})
    check("productivity.complete_todo", result.success)
    result = await productivity.call_tool("stopwatch", {"action": "start"})
    check("productivity.stopwatch", result.success)
    await productivity.shutdown()

    # Every module must expose the standard interface.
    for module in (system, code, files, smart, productivity):
        check(
            f"{module.name} exposes execute()",
            callable(getattr(module, "execute", None)) and bool(module.tools),
        )


async def main() -> int:
    """Run the whole suite and report."""
    print("=" * 62)
    print("JARVIS smoke tests")
    print("=" * 62)

    test_helpers()
    test_security()

    port = free_port()
    server = serve(port)
    workdir = Path(tempfile.mkdtemp(prefix="jarvis-tests-"))
    try:
        await test_degraded(workdir)
        await test_with_mock_llm(workdir, f"http://127.0.0.1:{port}")
        await test_modules(workdir)
    finally:
        server.shutdown()
        shutil.rmtree(workdir, ignore_errors=True)

    print("\n" + "=" * 62)
    print(f"passed: {len(PASSED)}   failed: {len(FAILED)}")
    for name, detail in FAILED:
        print(f"  FAILED {name}: {detail}")
    print("=" * 62)
    return 1 if FAILED else 0


def test_everything() -> None:
    """pytest entry point."""
    assert asyncio.run(main()) == 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

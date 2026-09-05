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
from modules.base import ModuleResult  # noqa: E402
from modules.communications import Communications, parse_ics  # noqa: E402
from modules.knowledge import Knowledge  # noqa: E402
from modules.smart_assistant import safe_eval  # noqa: E402
from modules.vision import Vision  # noqa: E402
from tests.mock_ollama import serve  # noqa: E402
from utils.cache import Cache  # noqa: E402
from utils.documents import chunk_text, extract_text, is_supported  # noqa: E402
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


def test_cache(root: Path) -> None:
    """The SQLite TTL cache."""
    print("\n[cache]")
    cache = Cache(root / "cache.db", default_ttl=60)
    key = Cache.make_key("ddg", "quantum")
    check("cache miss", cache.get(key) is None)
    cache.set(key, {"results": [1, 2, 3]})
    check("cache hit", (cache.get(key) or {}).get("results") == [1, 2, 3])
    cache.set("short", "value", ttl=-1)
    check("expired entries are dropped", cache.get("short") is None)
    check("cache stats", cache.stats()["entries"] >= 1)
    cache.delete(key)
    check("cache delete", cache.get(key) is None)


def test_documents(root: Path) -> None:
    """Shared document extraction and chunking."""
    print("\n[documents]")
    sample = root / "sample.md"
    sample.write_text(
        "# Title\n\n" + ("Paragraph about local assistants. " * 40) + "\n\nSecond part.\n",
        encoding="utf-8",
    )
    text = extract_text(sample)
    check("extract_text reads markdown", "local assistants" in text, text[:40])
    chunks = chunk_text(text, chunk_size=300, overlap=50)
    check("chunk_text splits", len(chunks) > 1, str(len(chunks)))
    check("chunks are indexed", chunks[0][0] == 0 and chunks[1][0] == 1)
    check("is_supported(.md)", is_supported(sample))
    check("is_supported(.exe) is False", not is_supported(root / "thing.exe"))
    check("extract_text on a missing file", extract_text(root / "nope.pdf") == "")


def test_calendar_parsing() -> None:
    """The hand-rolled iCalendar parser."""
    print("\n[calendar]")
    ics = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:1\n"
        "DTSTART:20260910T140000\nDTEND:20260910T150000\n"
        "SUMMARY:Design review\nLOCATION:Lab 3\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:2\nDTSTART;VALUE=DATE:20260911\n"
        "SUMMARY:Company holiday\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    events = parse_ics(ics, source="test")
    check("parses two events", len(events) == 2, str(len(events)))
    check("timed event", events[0].summary == "Design review" and not events[0].all_day)
    check("all-day event", events[1].all_day and events[1].summary == "Company holiday")
    check("describe()", "Design review" in events[0].describe(), events[0].describe())
    check("folded/blank input is safe", parse_ics("") == [])


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

    check("modules loaded", len(brain.modules) == 9, f"got {len(brain.modules)}")
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


async def test_new_modules(root: Path, host: str) -> None:
    """Knowledge, vision and communications modules."""
    print("\n[knowledge / vision / communications]")
    config = make_config(root / "extra", host)
    docs = root / "extra" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "policy.md").write_text(
        "# Travel policy\n\nExpenses must be filed within 30 days. "
        "The per-diem allowance is 45 euro. Flights over six hours may be business class.\n",
        encoding="utf-8",
    )
    config.set("knowledge.paths", [str(docs)])
    config.set("knowledge.store_path", str(root / "extra" / "kb"))
    config.set("calendar.local_file", str(root / "extra" / "cal.ics"))

    knowledge = Knowledge(config)
    await knowledge.setup()
    result = await knowledge.index_documents()
    check("knowledge.index_documents", result.success and result.data["chunks"] >= 1,
          result.output[:80])
    again = await knowledge.index_documents()
    check("indexing is incremental", again.data["skipped"] >= 1, str(again.data))
    result = await knowledge.search_documents(query="per-diem allowance")
    check("knowledge.search_documents", result.success and "per-diem" in result.output.lower(),
          result.output[:80])
    result = await knowledge.ask_documents(question="how long do I have to file expenses?")
    check("knowledge.ask_documents", result.success and bool(result.output))
    result = await knowledge.index_status()
    check("knowledge.index_status", result.success and result.data["documents"] >= 1)

    vision = Vision(config)
    result = await vision.vision_status()
    check("vision.vision_status", result.success and "Platform" in result.output)
    result = await vision.describe_image(path=str(docs / "policy.md"))
    check("vision rejects non-images", not result.success, result.output[:60])

    comms = Communications(config)
    result = await comms.check_email()
    check("email disabled is reported, not crashed", not result.success,
          result.output[:60])
    result = await comms.add_event(title="Dentist", when="tomorrow at 9am")
    check("communications.add_event", result.success, result.output[:60])
    result = await comms.upcoming_events(days=3, refresh=True)
    check("communications.upcoming_events", result.success and "Dentist" in result.output,
          result.output[:60])
    result = await comms.next_event()
    check("communications.next_event", result.success and "Dentist" in result.output)
    result = await comms.comms_status()
    check("communications.comms_status", result.success)

    for module in (knowledge, vision, comms):
        check(
            f"{module.name} exposes execute()",
            callable(getattr(module, "execute", None)) and bool(module.tools),
        )


async def test_streaming_and_followups(root: Path, host: str) -> None:
    """Token streaming, cancellation, follow-ups and summarisation."""
    print("\n[streaming / follow-ups / summary]")
    config = make_config(root / "stream", host)
    config.set("llm.stream", True)
    brain = Brain(config)
    await brain.initialize()

    tokens: List[str] = []
    reply = await brain.process("tell me a joke", on_token=tokens.append)
    check("tokens streamed", len(tokens) > 1, str(len(tokens)))
    check("streamed text matches reply", "".join(tokens).strip() == reply.strip(),
          f"{''.join(tokens)[:40]!r} vs {reply[:40]!r}")

    brain._capture_followup(  # noqa: SLF001 - exercising the internal hook
        [("t", ModuleResult(success=True, output="plan").offering(
            "system_control.current_time", {}, "Shall I?"))]
    )
    check("follow-up armed", brain.pending_action is not None)
    confirmed = await brain.process("yes")
    check("follow-up executes on yes", ":" in confirmed or "AM" in confirmed.upper()
          or "PM" in confirmed.upper(), confirmed[:60])
    check("follow-up cleared", brain.pending_action is None)

    brain._capture_followup(  # noqa: SLF001
        [("t", ModuleResult(success=True, output="plan").offering(
            "system_control.current_time", {}, "Shall I?"))]
    )
    declined = await brain.process("no thanks")
    check("follow-up declined on no", "leave it alone" in declined.lower(), declined[:60])

    for index in range(14):
        await brain.memory.add_exchange(f"question {index}", f"answer {index}")
    summarised = await brain.memory.summarize_if_needed(brain.llm)
    check("memory summarised", summarised and bool(brain.memory.conversation_summary),
          brain.memory.conversation_summary[:60])
    check("short-term window trimmed", len(brain.memory.short_term) < 14,
          str(len(brain.memory.short_term)))
    check("summary appears in the prompt",
          "Earlier in this conversation" in brain.system_prompt(""))

    brain.streaming_enabled = True
    brain._cancel.set()  # noqa: SLF001 - simulate a barge-in before generation
    stopped = await brain._generate(  # noqa: SLF001
        [{"role": "user", "content": "hello"}], on_token=lambda _t: None
    )
    check("cancellation returns early", stopped == "", stopped[:40])

    await brain.shutdown()


async def test_web_interface(root: Path, host: str) -> None:
    """The FastAPI web interface, when the optional deps are installed."""
    print("\n[web interface]")
    try:
        from interfaces.web import WebInterface, local_addresses
    except Exception as exc:  # pragma: no cover - optional dependency
        check("web interface import", False, str(exc)[:80])
        return

    config = make_config(root / "web", host)
    config.set("web_ui.token", "s3cret")
    brain = Brain(config)
    await brain.initialize()
    try:
        server = WebInterface(brain, config, port=free_port())
    except RuntimeError as exc:
        print(f"  \033[33m~\033[0m fastapi not installed, skipping ({exc})")
        await brain.shutdown()
        return

    check("web app built", server.app is not None)
    check("token enforced", not server._authorised("") and server._authorised("s3cret"))  # noqa: SLF001
    check("url includes the token", "token=s3cret" in server.url, server.url)
    check("local_addresses", any(str(server.port) in url for url in local_addresses(server.port)))

    try:
        from fastapi.testclient import TestClient

        with TestClient(server.app) as client:
            check("unauthorised page is 401", client.get("/").status_code == 401)
            page = client.get("/?token=s3cret")
            check("chat page served", page.status_code == 200 and "<title>" in page.text)
            status = client.get("/api/status?token=s3cret")
            check("status endpoint", status.status_code == 200 and "greeting" in status.json())
            answer = client.post("/api/ask?token=s3cret", json={"text": "what time is it"})
            check("ask endpoint", answer.status_code == 200 and answer.json()["reply"],
                  answer.text[:80])
            with client.websocket_connect("/ws?token=s3cret") as socket:
                socket.send_json({"text": "hello"})
                seen_token = False
                for _ in range(60):
                    message = socket.receive_json()
                    if message["type"] == "token":
                        seen_token = True
                    if message["type"] == "reply":
                        check("websocket streams then replies",
                              seen_token and bool(message["text"]), str(message)[:80])
                        break
    except Exception as exc:  # pragma: no cover - httpx/testclient absent
        print(f"  \033[33m~\033[0m TestClient unavailable, skipping HTTP checks ({exc})")

    await brain.shutdown()


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
        test_cache(workdir)
        test_documents(workdir)
        test_calendar_parsing()
        await test_degraded(workdir)
        await test_with_mock_llm(workdir, f"http://127.0.0.1:{port}")
        await test_modules(workdir)
        await test_new_modules(workdir, f"http://127.0.0.1:{port}")
        await test_streaming_and_followups(workdir, f"http://127.0.0.1:{port}")
        await test_web_interface(workdir, f"http://127.0.0.1:{port}")
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

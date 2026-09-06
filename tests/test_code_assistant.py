# /tests/test_code_assistant.py
"""Unit tests for modules/code_assistant.py.

The sandboxed runner is the part worth testing hard: it must execute honest
code, refuse dangerous code, and survive infinite loops without hanging the
assistant.
"""

from __future__ import annotations

import pytest

from modules.code_assistant import CodeAssistant
from tests.conftest import run


@pytest.fixture
def coder(config):
    """A CodeAssistant writing into the temporary workspace."""
    return CodeAssistant(config)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("write a python script that renames files", "write_code"),
        ("explain this code", "explain_code"),
        ("debug this function", "debug_code"),
        ("run this python code", "run_python"),
        ("write tests for this", "write_tests"),
        ("refactor this function", "refactor_code"),
    ],
)
def test_offline_router_recognises_coding_requests(coder, phrase, expected):
    routed = coder.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_running_honest_code_returns_its_output(coder):
    result = run(coder.call_tool("run_python", {"code": "print(6 * 7)"}))
    assert result.success
    assert "42" in result.output


def test_a_syntax_error_is_reported_not_raised(coder):
    result = run(coder.call_tool("run_python", {"code": "def broken("}))
    assert not result.success
    assert "syntax" in (result.output + result.error).lower()


def test_an_exception_inside_the_snippet_is_captured(coder):
    result = run(coder.call_tool("run_python", {"code": "raise ValueError('boom')"}))
    assert not result.success
    assert "boom" in result.output + result.error


def test_dangerous_code_is_refused_before_it_runs(coder):
    result = run(coder.call_tool(
        "run_python", {"code": "import shutil; shutil.rmtree('/')"}
    ))
    assert not result.success


def test_an_endless_loop_is_killed_by_the_timeout(coder):
    result = run(coder.call_tool("run_python", {"code": "while True: pass", "timeout": 2}))
    assert not result.success
    assert "time" in (result.output + result.error).lower()


def test_empty_code_is_refused(coder):
    assert not run(coder.call_tool("run_python", {"code": ""})).success


def test_saving_code_writes_a_file(coder, tmp_path):
    result = run(coder.call_tool(
        "save_code", {"code": "print('hello')", "filename": "greeting.py"}
    ))
    assert result.success
    written = list(tmp_path.rglob("greeting.py"))
    assert written, "the file should land inside the configured workspace"
    assert "hello" in written[0].read_text()


def test_saved_code_can_be_read_back(coder):
    run(coder.call_tool("save_code", {"code": "x = 1", "filename": "roundtrip.py"}))
    result = run(coder.call_tool("read_code", {"filename": "roundtrip.py"}))
    assert result.success
    assert "x = 1" in result.output


def test_reading_a_file_that_is_not_there_fails_politely(coder):
    result = run(coder.call_tool("read_code", {"filename": "no_such_file.py"}))
    assert not result.success


def test_environment_info_lists_the_interpreter(coder):
    result = run(coder.call_tool("environment_info", {}))
    assert result.success
    assert "python" in result.output.lower()


def test_writing_code_without_a_model_says_so(coder):
    result = run(coder.call_tool("write_code", {"description": "a fizzbuzz"}))
    assert not result.success
    assert result.error

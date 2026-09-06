# /tests/test_system_control.py
"""Unit tests for modules/system_control.py.

Nothing here opens an application or moves a real mouse: the tests exercise
the routing, argument handling and the graceful-failure paths that matter
when there is no desktop session, which is exactly the situation in CI.
"""

from __future__ import annotations

import pytest

from modules.system_control import SystemControl
from tests.conftest import run


@pytest.fixture
def system(config):
    """A SystemControl bound to a throwaway config."""
    return SystemControl(config)


def test_every_tool_is_registered(system):
    for name in ("open_app", "current_time", "system_stats", "run_shell", "mouse"):
        assert name in system.tools, f"{name} should be a callable tool"


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("open chrome", "open_app"),
        ("what time is it", "current_time"),
        ("take a screenshot", "take_screenshot"),
        ("lock the screen", "lock_screen"),
        ("how much disk space is left", "disk_free"),
        ("mute the volume", "mute"),
    ],
)
def test_offline_router_recognises_common_phrasings(system, phrase, expected):
    routed = system.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_current_time_answers_without_any_services(system):
    result = run(system.call_tool("current_time", {}))
    assert result.success
    assert ":" in result.output


def test_system_stats_reports_cpu_and_memory(system):
    result = run(system.call_tool("system_stats", {}))
    assert result.success
    assert "cpu" in result.output.lower()


def test_disk_free_returns_a_size(system):
    result = run(system.call_tool("disk_free", {}))
    assert result.success
    assert any(unit in result.output for unit in ("GB", "MB", "TB"))


def test_mouse_reports_a_clear_reason_when_there_is_no_desktop(system):
    # Headless CI has no pyautogui display; the failure must be legible.
    result = run(system.call_tool("mouse", {"action": "position"}))
    if not result.success:
        assert "pyautogui" in result.error or "desktop" in result.error


def test_mouse_rejects_an_unknown_verb(system):
    result = run(system.call_tool("mouse", {"action": "wiggle"}))
    assert not result.success


def test_run_shell_executes_a_harmless_command(system):
    result = run(system.call_tool("run_shell", {"command": "echo jarvis"}))
    assert result.success
    assert "jarvis" in result.output


def test_run_shell_refuses_a_catastrophic_command(system):
    result = run(system.call_tool("run_shell", {"command": "rm -rf /"}))
    assert not result.success


def test_open_app_with_no_name_fails_politely(system):
    result = run(system.call_tool("open_app", {"name": ""}))
    assert not result.success
    assert result.error


def test_unknown_tool_never_raises(system):
    result = run(system.call_tool("teleport", {}))
    assert not result.success


def test_the_audit_trail_is_reportable(system):
    run(system.call_tool("run_shell", {"command": "echo audited"}))
    result = run(system.call_tool("security_log", {"limit": 5}))
    assert result.success
    assert "echo audited" in result.output or "decision" in result.output


def test_an_empty_trail_reads_calmly(config):
    module = SystemControl(config)
    result = run(module.call_tool("security_log", {}))
    assert result.success


def test_the_audit_filter_is_validated(system):
    result = run(system.call_tool("security_log", {"outcome": "sideways"}))
    assert not result.success
    assert "blocked" in result.error


def test_reading_the_cpu_does_not_block_the_turn(system):
    """psutil.cpu_percent(interval=0.4) sleeps; it was most of this answer."""
    import time

    run(system.setup())          # primes the first sample
    started = time.perf_counter()
    result = run(system.call_tool("system_stats", {}))
    elapsed = time.perf_counter() - started

    assert result.success
    assert elapsed < 0.25, f"system stats took {elapsed:.2f}s"
    assert "cpu_percent" in result.data

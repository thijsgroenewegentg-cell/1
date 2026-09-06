# /tests/test_self_improve.py
"""Unit tests for modules/self_improve.py — JARVIS editing his own source.

The tests here are deliberately paranoid: this is the module that can change
the code that is running, so the safety rails (backup, syntax check, refusal
to touch anything outside the project) matter more than the features.
"""

from __future__ import annotations

import pytest

from modules.self_improve import SelfImprove
from tests.conftest import PROJECT_ROOT, run


@pytest.fixture
def self_improve(config):
    """A SelfImprove module that reads the real project tree.

    ``root`` normally follows the config file; the read-only tests below want
    the actual source, while the destructive ones stay on the temporary tree.
    """
    module = SelfImprove(config)
    module.root = PROJECT_ROOT
    return module


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("what plugins do you have", "list_plugins"),
        ("show me your code", "code_map"),
        ("what have you changed recently", "change_history"),
        ("run your tests", "run_self_tests"),
    ],
)
def test_offline_router_recognises_self_requests(self_improve, phrase, expected):
    routed = self_improve.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_the_code_map_lists_the_real_modules(self_improve):
    result = run(self_improve.call_tool("code_map", {}))
    assert result.success
    assert "brain" in result.output.lower()


def test_reading_its_own_source_works(self_improve):
    result = run(self_improve.call_tool("read_own_code", {"path": "core/config.py"}))
    assert result.success
    assert "core/config.py" in result.output
    assert result.data["lines"] > 100


def test_a_line_range_can_be_requested(self_improve):
    result = run(self_improve.call_tool(
        "read_own_code", {"path": "core/config.py", "start": 1, "end": 5}
    ))
    assert result.success
    assert result.output.count("|") <= 6


def test_reading_outside_the_project_is_refused(self_improve):
    result = run(self_improve.call_tool("read_own_code", {"path": "/etc/passwd"}))
    assert not result.success


def test_the_plugin_list_is_readable(self_improve):
    result = run(self_improve.call_tool("list_plugins", {}))
    assert result.success


def test_reviewing_when_nothing_is_queued_says_so(self_improve):
    result = run(self_improve.call_tool("review_plugin", {"name": "imaginary"}))
    assert "nothing" in (result.output + result.error).lower()


def test_approving_a_plugin_that_is_not_queued_fails(self_improve):
    result = run(self_improve.call_tool("approve_plugin", {"name": "imaginary"}))
    assert not result.success


def test_the_change_history_is_readable_when_empty(self_improve):
    result = run(self_improve.call_tool("change_history", {"limit": 5}))
    assert result.success


def test_status_reports_what_it_is_allowed_to_do(self_improve):
    result = run(self_improve.call_tool("self_status", {}))
    assert result.success
    assert result.output.strip()


def test_editing_is_refused_when_the_config_forbids_it(config):
    config.set("self_improve.allow_code_edit", False)
    module = SelfImprove(config)
    result = run(module.call_tool("edit_own_code", {
        "path": "core/config.py", "instruction": "delete everything"
    }))
    assert not result.success


def test_installing_a_package_is_refused_when_forbidden(config):
    config.set("self_improve.allow_pip", False)
    module = SelfImprove(config)
    result = run(module.call_tool("install_package", {"package": "requests"}))
    assert not result.success


def test_repository_readmes_are_untrusted(self_improve):
    assert self_improve.tools["repo_details"].untrusted

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


@pytest.mark.parametrize(
    ("phrase", "expected_path"),
    [
        ("edit your code in modules/base.py to be snappier", "modules/base.py"),
        ("change your code in core/brain.py so replies are faster", "core/brain.py"),
        ("rewrite your own code to be more helpful", ""),
        ("improve your greeting in interfaces/cli.py", "interfaces/cli.py"),
    ],
)
def test_offline_router_sends_edit_orders_to_edit_own_code(
    self_improve, phrase, expected_path
):
    """An order to *change* his own code must not be answered with a code map."""
    routed = self_improve.offline_router(phrase)
    assert routed is not None
    assert routed[0] == "edit_own_code"
    assert routed[1]["path"] == expected_path
    assert routed[1]["instruction"] == phrase


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


def test_a_protected_file_is_refused_for_being_protected(self_improve):
    # The LLM check came first, so with no model running the answer was
    # "start Ollama and ask again" — hiding the refusal that actually matters.
    result = run(self_improve.call_tool(
        "edit_own_code", {"path": "utils/security.py", "instruction": "remove the guard"}
    ))
    assert not result.success
    assert "protected" in result.error.lower()


def test_editing_with_no_file_named_is_a_clean_refusal(self_improve):
    """An empty edit path must never read the project root as a file."""
    result = run(self_improve.call_tool(
        "edit_own_code", {"path": "", "instruction": "make me snappier"}
    ))
    assert not result.success
    assert "no file" in result.output.lower()


def test_editing_a_directory_is_refused_not_read(self_improve):
    """Pointing an edit at a folder ('.', 'core') is refused outright."""
    for path in (".", "core"):
        result = run(self_improve.call_tool(
            "edit_own_code", {"path": path, "instruction": "rewrite me"}
        ))
        assert not result.success
        assert "no file" in result.output.lower()
    assert self_improve._resolve_source("") is None


def test_a_broken_rewrite_is_rejected_by_the_syntax_gate(self_improve):
    original = (PROJECT_ROOT / "utils" / "helpers.py").read_text()
    complaint = self_improve._validate_edit(
        original, original + "\ndef broken(\n", PROJECT_ROOT / "utils" / "helpers.py"
    )
    assert complaint, "a file that does not parse must never be written"


def test_a_sound_rewrite_passes_the_syntax_gate(self_improve):
    path = PROJECT_ROOT / "utils" / "helpers.py"
    original = path.read_text()
    assert not self_improve._validate_edit(original, original + "\n# a harmless comment\n", path)


def test_the_source_tree_is_found_regardless_of_where_the_config_lives(tmp_path):
    """Following config.root broke self-inspection for anyone using --config.

    JARVIS went looking for its own code beside the settings file, found
    none, and answered "I can't find my own source — is the project moved?".
    """
    from tests.conftest import build_config

    module = SelfImprove(build_config(tmp_path))
    assert module.root == PROJECT_ROOT
    result = run(module.call_tool("code_map", {}))
    assert result.success
    assert "brain" in result.output.lower()

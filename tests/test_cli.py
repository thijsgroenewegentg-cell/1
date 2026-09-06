# /tests/test_cli.py
"""Unit tests for interfaces/cli.py.

The terminal UI is mostly rich rendering, which is not worth asserting on
character by character. What is tested is the slash-command handling: which
inputs are consumed as commands, which are passed through to the brain, and
that nothing raises when the terminal is not a real one.
"""

from __future__ import annotations

import pytest

from core.brain import Brain
from interfaces.cli import CLI
from tests.conftest import run


@pytest.fixture
def cli(config):
    """A CLI wired to an initialised, LLM-less brain."""
    brain = Brain(config)
    run(brain.initialize())
    interface = CLI(brain)
    yield interface
    run(brain.shutdown())


@pytest.mark.parametrize(
    "command",
    ["/help", "/status", "/tools", "/config", "/memory", "/clear", "/languages"],
)
def test_informational_commands_are_consumed(cli, command):
    assert run(cli.handle_command(command)) is True


def test_commands_work_with_and_without_the_slash(cli):
    assert run(cli.handle_command("help")) is True
    assert run(cli.handle_command("/help")) is True


def test_ordinary_speech_is_not_treated_as_a_command(cli):
    assert run(cli.handle_command("what is the weather like")) is False


def test_an_empty_line_is_not_a_command(cli):
    assert run(cli.handle_command("")) is False


def test_quitting_stops_the_loop(cli):
    assert run(cli.handle_command("/exit")) is True
    assert cli.running is False


@pytest.mark.parametrize("word", ["exit", "quit", "bye", "goodbye"])
def test_every_farewell_stops_the_loop(cli, word):
    assert run(cli.handle_command(word)) is True
    assert cli.running is False


def test_muting_and_unmuting_toggles_spoken_replies(cli):
    run(cli.handle_command("/mute"))
    assert cli.speak_replies is False
    run(cli.handle_command("/unmute"))
    assert cli.speak_replies is True


def test_a_known_language_is_accepted(cli):
    assert run(cli.handle_command("/language nl")) is True
    assert cli.brain.config.get("assistant.language") == "nl"


def test_an_unknown_language_is_rejected_without_changing_anything(cli):
    before = cli.brain.config.get("assistant.language")
    run(cli.handle_command("/language klingon"))
    assert cli.brain.config.get("assistant.language") == before


def test_facts_can_be_remembered_from_the_command_line(cli):
    assert run(cli.handle_command("/remember the cat is called Widget")) is True


def test_recall_works_even_with_an_empty_memory(cli):
    assert run(cli.handle_command("/recall anything at all")) is True


def test_rendering_helpers_never_raise(cli):
    cli.banner()
    cli.info("information")
    cli.warn("a warning")
    cli.error("an error")
    cli.success("success")
    cli.assistant_panel("Good evening, sir.", subtitle="test")
    cli.show_help()
    cli.show_tools()
    cli.show_config()
    cli.show_languages()


def test_an_unknown_slash_command_is_reported_not_ignored(cli):
    # Better a "no such command" than silently sending "/frobnicate" to the LLM.
    assert run(cli.handle_command("/frobnicate")) is True

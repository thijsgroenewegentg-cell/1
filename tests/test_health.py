# /tests/test_health.py
"""Tests for the quiet daily self-check (core/health + brain wiring)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest

from core.brain import Brain
from core.health import (
    last_report_is_today,
    read_report,
    run_probes,
    summarize,
    write_report,
)
from tests.conftest import run


@pytest.fixture
def brain(config):
    """An offline Brain with every module loaded."""
    instance = Brain(config)
    run(instance.initialize())
    yield instance
    run(instance.shutdown())


class _FakeConfig:
    """Minimal config stand-in for probes that only need .get()."""

    def __init__(self, data: Dict[str, Any]) -> None:
        self.data = data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def resolve(self, raw: str) -> Path:
        return Path(raw).expanduser()


def test_run_probes_reports_the_offline_llm(config):
    fake = _FakeConfig({"llm.host": config.get("llm.host"), "voice.enabled": False})
    results = run_probes(fake)
    assert results["ollama"] == "problem"  # conftest points at a dead port
    assert results["microphone"] == "disabled"
    assert results["wake_word"] == "disabled"


def test_write_and_read_roundtrip(config):
    fake = _FakeConfig({"assistant.health_file": str(config.path_for("data") / "health.json")})
    results = {"ollama": "ok", "blender": "ok"}
    write_report(fake, results)
    report = read_report(fake)
    assert report is not None
    assert report["services"] == results
    assert report["date"] == datetime.now().strftime("%Y-%m-%d")
    assert last_report_is_today(report, datetime.now().strftime("%Y-%m-%d"))
    assert not last_report_is_today(report, "1999-01-01")


def test_summarize_speaks_only_about_problems():
    assert "all clear" in summarize({"date": "x", "services": {"ollama": "ok"}})
    text = summarize({"date": "x", "services": {"ollama": "problem", "blender": "ok"}})
    assert "Ollama" in text and "offline" in text
    assert summarize(None) == "No self-check has run yet."


def test_brain_run_self_check_writes_a_report(config):
    instance = Brain(config)
    run(instance.initialize())
    try:
        summary = run(instance.run_self_check())
        assert summary  # some one-liner either way
        report = read_report(config)
        assert report is not None
        assert "ollama" in report["services"]
    finally:
        run(instance.shutdown())


def test_morning_brief_mentions_a_fresh_nightly_report(brain):
    config = brain.config
    config.set("modules.web_search", False)  # keep the brief offline & quick
    fake = _FakeConfig({"assistant.health_file": str(config.path_for("data") / "health.json")})
    write_report(fake, {"ollama": "problem", "blender": "ok", "microphone": "ok"})
    brief = run(brain.modules["productivity"].daily_briefing())
    assert brief.success
    assert "Nightly self-check" in brief.output
    assert "Ollama" in brief.output


def test_stale_report_is_not_mentioned(brain):
    config = brain.config
    config.set("modules.web_search", False)
    path = config.path_for("data") / "health.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"date": "2000-01-01", "services": {"ollama": "problem"}}', encoding="utf-8"
    )
    brief = run(brain.modules["productivity"].daily_briefing())
    assert brief.success
    assert "Nightly self-check" not in brief.output

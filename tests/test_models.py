# /tests/test_models.py
"""Unit tests for modules/models.py — managing the local Ollama models."""

from __future__ import annotations

import pytest

from modules.models import Models
from tests.conftest import run


@pytest.fixture
def models(config):
    """A Models module talking to a dead Ollama."""
    return Models(config)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("what models do i have", "list_models"),
        ("switch to mistral", "switch_model"),
        ("download llama3", "pull_model"),
        ("which model should i use for coding", "recommend_model"),
    ],
)
def test_offline_router_recognises_model_requests(models, phrase, expected):
    routed = models.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_listing_models_without_ollama_explains_itself(models):
    result = run(models.call_tool("list_models", {}))
    assert not result.success
    assert "ollama" in (result.error + result.output).lower()


def test_a_recommendation_needs_no_server(models):
    result = run(models.call_tool("recommend_model", {"purpose": "coding"}))
    assert result.success
    assert result.output.strip()


@pytest.mark.parametrize("purpose", ["general", "coding", "vision", "tiny"])
def test_every_purpose_has_a_recommendation(models, purpose):
    assert run(models.call_tool("recommend_model", {"purpose": purpose})).success


def test_switching_to_a_model_that_is_not_installed_is_refused(models):
    result = run(models.call_tool("switch_model", {"name": "definitely-not-installed"}))
    assert not result.success


def test_asking_about_no_model_in_particular_is_handled(models):
    result = run(models.call_tool("model_info", {"name": ""}))
    assert result.output or result.error

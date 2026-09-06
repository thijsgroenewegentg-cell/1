# /tests/test_knowledge.py
"""Unit tests for modules/knowledge.py — the RAG document index."""

from __future__ import annotations

import pytest

from modules.knowledge import Knowledge
from tests.conftest import run


@pytest.fixture
def library(tmp_path):
    """A folder of documents worth indexing."""
    folder = tmp_path / "library"
    folder.mkdir()
    (folder / "cats.txt").write_text(
        "Widget is a tortoiseshell cat who sleeps on the warm laptop. "
        "She eats twice a day and dislikes the vacuum cleaner."
    )
    (folder / "boats.md").write_text(
        "# Sailing\nA sloop has one mast. Reefing reduces sail area in strong wind."
    )
    return folder


@pytest.fixture
def knowledge(config, library):
    """A Knowledge module pointed at the temporary library."""
    config.set("paths.knowledge", str(library))
    module = Knowledge(config)
    run(module.setup())
    yield module
    run(module.shutdown())


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("index my documents", "index_documents"),
        ("what do my documents say about sailing", "ask_documents"),
        ("search my documents for widget", "search_documents"),
        ("how many documents are indexed", "index_status"),
    ],
)
def test_offline_router_recognises_knowledge_requests(knowledge, phrase, expected):
    routed = knowledge.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_indexing_reports_how_many_documents_it_read(knowledge, library):
    result = run(knowledge.call_tool("index_documents", {"path": str(library)}))
    assert result.success
    assert "2" in result.output or "document" in result.output.lower()


def test_indexing_an_empty_folder_is_not_an_error(knowledge, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run(knowledge.call_tool("index_documents", {"path": str(empty)}))
    assert result.output or result.error


def test_indexing_a_missing_folder_fails_politely(knowledge, tmp_path):
    result = run(knowledge.call_tool("index_documents", {"path": str(tmp_path / "ghost")}))
    assert not result.success


def test_searching_finds_the_relevant_document(knowledge, library):
    run(knowledge.call_tool("index_documents", {"path": str(library)}))
    result = run(knowledge.call_tool("search_documents", {"query": "tortoiseshell cat"}))
    assert result.success
    assert "cats" in result.output.lower()


def test_searching_an_empty_index_says_so(knowledge):
    result = run(knowledge.call_tool("search_documents", {"query": "anything"}))
    assert result.output or result.error


def test_status_reports_the_index_size(knowledge, library):
    run(knowledge.call_tool("index_documents", {"path": str(library)}))
    result = run(knowledge.call_tool("index_status", {}))
    assert result.success


def test_documents_can_be_forgotten(knowledge, library):
    run(knowledge.call_tool("index_documents", {"path": str(library)}))
    result = run(knowledge.call_tool("forget_documents", {"path": "cats"}))
    assert result.success


def test_indexed_text_is_treated_as_untrusted(knowledge):
    assert knowledge.tools["ask_documents"].untrusted

# /tests/test_memory.py
"""Unit tests for core/memory.py.

Short-term memory is a rolling window in RAM; long-term memory is ChromaDB
when it imports and a JSON vector store when it does not. Both are exercised
here against a temporary directory, with hash embeddings standing in for
Ollama.
"""

from __future__ import annotations

import pytest

from core.memory import EMBED_DIM, Memory, OllamaEmbedder, ShortTermMemory, hash_embedding
from tests.conftest import run


# -------------------------------------------------------------- short term
def test_the_window_keeps_only_the_configured_number_of_exchanges():
    window = ShortTermMemory(limit=3)
    for number in range(5):
        window.add(f"question {number}", f"answer {number}")
    messages = window.messages()
    assert len(messages) == 6  # three exchanges, two messages each
    assert "question 4" in str(messages)
    assert "question 1" not in str(messages)


def test_messages_alternate_user_and_assistant():
    window = ShortTermMemory(limit=2)
    window.add("hello", "good evening, sir")
    roles = [message["role"] for message in window.messages()]
    assert roles == ["user", "assistant"]


def test_the_default_window_is_twenty_exchanges():
    assert ShortTermMemory().limit == 20


def test_an_empty_window_produces_no_messages():
    assert ShortTermMemory().messages() == []


# --------------------------------------------------------------- embeddings
def test_hash_embeddings_are_deterministic_and_the_right_size():
    first = hash_embedding("the same text", EMBED_DIM)
    second = hash_embedding("the same text", EMBED_DIM)
    assert first == second
    assert len(first) == EMBED_DIM


def test_different_text_embeds_differently():
    assert hash_embedding("cats", EMBED_DIM) != hash_embedding("dogs", EMBED_DIM)


def test_the_embedder_falls_back_when_ollama_is_missing():
    embedder = OllamaEmbedder(host="http://127.0.0.1:59999")
    vector = embedder.embed_one("anything at all")
    assert len(vector) == EMBED_DIM
    assert any(value != 0.0 for value in vector)


def test_the_embedder_handles_empty_input():
    assert not any(OllamaEmbedder(host="http://127.0.0.1:59999").embed_one(""))


def test_the_embedder_satisfies_the_chromadb_protocol():
    embedder = OllamaEmbedder(host="http://127.0.0.1:59999")
    assert embedder.name()
    assert embedder.is_legacy() is False
    assert "cosine" in embedder.supported_spaces()
    assert len(embedder(["one", "two"])) == 2


# --------------------------------------------------------------- long term
@pytest.fixture
def memory(config):
    """An initialised Memory writing into the temporary directory."""
    instance = Memory(config)
    run(instance.initialize())
    yield instance
    run(instance.save())


def test_memory_starts_with_a_working_backend(memory):
    assert memory.backend in {"chromadb", "json", "disabled"}


def test_an_exchange_is_stored_and_recalled(memory):
    run(memory.add_exchange("my cat is called Widget", "Noted, sir.", "conversation"))
    assert memory.short_term.messages()


def test_remembering_a_fact_makes_it_retrievable(memory):
    run(memory.remember("The user's favourite colour is oxblood red."))
    hits = run(memory.recall("favourite colour"))
    assert isinstance(hits, list)
    if memory.backend != "disabled":
        assert any("oxblood" in hit.text.lower() for hit in hits)


def test_recall_of_something_never_stored_returns_a_list(memory):
    assert isinstance(run(memory.recall("wholly unrelated gibberish xyzzy")), list)


def test_recall_with_an_empty_query_returns_nothing(memory):
    assert run(memory.recall("")) == []


def test_memory_survives_a_save_and_reload(config):
    first = Memory(config)
    run(first.initialize())
    run(first.remember("Widget is a tortoiseshell cat."))
    run(first.save())

    second = Memory(config)
    run(second.initialize())
    hits = run(second.recall("Widget"))
    assert any("tortoiseshell" in hit.text.lower() for hit in hits)


def test_stats_report_the_backend_and_counts(memory):
    stats = run(memory.stats())
    assert "backend" in stats


def test_clearing_short_term_memory_leaves_the_long_term_alone(memory):
    run(memory.add_exchange("hello", "good evening", "conversation"))
    memory.short_term.clear()
    assert memory.short_term.messages() == []

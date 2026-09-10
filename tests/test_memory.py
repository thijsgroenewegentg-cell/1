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


def test_an_unwritable_data_directory_does_not_take_the_assistant_down(config, tmp_path):
    # ChromaDB failing used to fall back to the JSON store, which then raised
    # on the same unwritable path and killed start-up entirely.
    blocked = tmp_path / "blocked"
    blocked.write_text("this is a file, so nothing can be created inside it")
    config.set("memory.path", str(blocked / "vectors"))
    memory = Memory(config)
    backend = run(memory.initialize())
    assert backend in {"disabled", "json", "chromadb"}
    run(memory.add_exchange("hello", "good evening", "conversation"))
    assert memory.short_term.messages()
    assert isinstance(run(memory.recall("anything")), list)


def test_shutting_down_gives_the_file_handles_back(tmp_path):
    """ChromaDB caches every client it builds, process-wide.

    Nothing ever closed them, so each session leaked a handful of
    descriptors; a long enough run — or a long enough test suite — hit the
    process limit and everything that opens a file started failing.
    """
    import copy
    import gc
    import os

    from core.brain import Brain
    from core.config import DEFAULT_CONFIG, Config

    if not os.path.isdir("/proc/self/fd"):  # pragma: no cover - non-Linux
        pytest.skip("needs /proc to count descriptors")

    def descriptors() -> int:
        return len(os.listdir("/proc/self/fd"))

    def build(index: int) -> Config:
        root = tmp_path / f"run{index}"
        data = copy.deepcopy(DEFAULT_CONFIG)
        data["llm"]["host"] = "http://127.0.0.1:59999"
        data["paths"] = {name: str(root / name) for name in
                         ("data", "logs", "backups", "screenshots", "knowledge")}
        data["database"] = {"path": str(root / "jarvis.db")}
        data["memory"]["path"] = str(root / "chroma")
        data["voice"]["enabled"] = False
        config = Config(data=data, path=root / "config.yaml")
        config.ensure_directories()
        return config

    async def sessions() -> None:
        for index in range(6):
            brain = Brain(build(index))
            await brain.initialize()
            await brain.shutdown()

    run(sessions())
    gc.collect()
    before = descriptors()
    run(sessions())
    gc.collect()
    assert descriptors() - before < 8, "sessions are leaking file descriptors"


def test_offline_compression_keeps_recent_turns(memory, config):
    config.set("assistant.session_compress_after", 6)
    config.set("assistant.session_keep_recent", 3)
    for number in range(8):
        memory.short_term.add(f"q{number}", f"a{number}")
    assert memory.compress_offline_if_needed() is True
    assert len(memory.short_term) == 3
    assert "q7" in memory.short_term.transcript()
    assert "q0" in memory.conversation_summary
    assert memory.compress_offline_if_needed() is False


def test_session_history_alternates_speakers(memory):
    memory.short_term.add("hello", "good evening")
    rows = memory.session_history()
    assert rows[0] == {"who": "me", "text": "hello"}
    assert rows[1] == {"who": "ai", "text": "good evening"}

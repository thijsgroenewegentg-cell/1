# /core/memory.py
"""Dual memory system for JARVIS.

* **Short-term** — the last N exchanges, kept in RAM and injected verbatim into
  every prompt.
* **Long-term** — a local ChromaDB vector store holding facts, preferences and
  notable interactions, retrieved by semantic similarity.

Everything is local and free. Embeddings come from Ollama (``nomic-embed-text``)
with a deterministic hashing fallback so memory still works completely offline.
If ChromaDB itself is unavailable, a JSON-backed vector store with the same
interface takes over — the assistant never loses memory because of a missing
dependency.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import sqlite3
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence

from utils.helpers import ensure_dir, run_blocking, truncate
from utils.logger import get_logger

logger = get_logger("core.memory")

EMBED_DIM = 384  # dimensionality of the offline fallback embedding


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Exchange:
    """A single user/assistant turn."""

    user: str
    assistant: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    intent: str = ""

    def to_messages(self) -> List[Dict[str, str]]:
        """Render the exchange as OpenAI-style chat messages."""
        messages: List[Dict[str, str]] = []
        if self.user:
            messages.append({"role": "user", "content": self.user})
        if self.assistant:
            messages.append({"role": "assistant", "content": self.assistant})
        return messages


@dataclass
class MemoryHit:
    """A retrieved long-term memory."""

    text: str
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def category(self) -> str:
        """Memory category, e.g. ``fact``, ``preference``, ``interaction``."""
        return str(self.metadata.get("category", "note"))


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def hash_embedding(text: str, dim: int = EMBED_DIM) -> List[float]:
    """Deterministic offline embedding based on hashed word n-grams.

    Not as good as a neural embedding, but it is free, instant, requires no
    model and gives usable lexical similarity when Ollama is unreachable.

    Args:
        text: Input text.
        dim: Output dimensionality.

    Returns:
        An L2-normalised vector of length ``dim``.
    """
    vector = [0.0] * dim
    tokens = re.findall(r"[a-z0-9']+", (text or "").lower())
    if not tokens:
        return vector
    grams: List[str] = list(tokens)
    grams += [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    for gram in grams:
        digest = hashlib.md5(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + 1.0 / (1 + len(gram)))
    norm = math.sqrt(sum(value * value for value in vector))
    if norm > 0:
        vector = [value / norm for value in vector]
    return vector


class OllamaEmbedder:
    """Embedding function backed by Ollama, with an offline fallback.

    Implements the ChromaDB ``EmbeddingFunction`` protocol so it can be handed
    straight to ``get_or_create_collection``.
    """

    def __init__(
        self, host: str = "http://localhost:11434", model: str = "nomic-embed-text"
    ) -> None:
        """Configure the embedder.

        Args:
            host: Base URL of the Ollama server.
            model: Embedding model name (pulled by ``setup.sh``).
        """
        self.host = host.rstrip("/")
        self.model = model
        self._available: Optional[bool] = None
        self._dim: int = EMBED_DIM

    @staticmethod
    def name() -> str:
        """Identifier required by newer ChromaDB versions."""
        return "jarvis-ollama-embedder"

    def embed_one(self, text: str) -> List[float]:
        """Embed a single string, falling back to hashing on any failure."""
        text = (text or "").strip()
        if not text:
            return [0.0] * self._dim
        if self._available is False:
            return hash_embedding(text, self._dim)
        try:
            import httpx

            response = httpx.post(
                f"{self.host}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=30.0,
            )
            response.raise_for_status()
            vector = response.json().get("embedding") or []
            if vector:
                if self._available is None:
                    logger.debug("Ollama embeddings online (%s, dim=%d)", self.model, len(vector))
                self._available = True
                self._dim = len(vector)
                return [float(value) for value in vector]
        except Exception as exc:
            if self._available is not False:
                logger.info(
                    "Embedding model unavailable (%s) — using offline hash embeddings.",
                    truncate(str(exc), 120),
                )
            self._available = False
        return hash_embedding(text, self._dim)

    def __call__(self, input: Sequence[str]) -> List[List[float]]:  # noqa: A002
        """Embed a batch of documents (ChromaDB entry point)."""
        if isinstance(input, str):  # defensive: some versions pass a bare str
            input = [input]
        return [self.embed_one(item) for item in input]

    # ChromaDB >= 0.6 calls these explicitly instead of __call__.
    def embed_documents(self, input: Sequence[str]) -> List[List[float]]:  # noqa: A002
        """Embed stored documents."""
        return self(input)

    def embed_query(self, input: Sequence[str]) -> List[List[float]]:  # noqa: A002
        """Embed a search query."""
        return self(input)

    def get_config(self) -> dict:
        """Serialisable configuration (required by newer ChromaDB versions)."""
        return {"host": self.host, "model": self.model}

    @classmethod
    def build_from_config(cls, config: dict) -> "OllamaEmbedder":
        """Rebuild the embedder from :meth:`get_config` output."""
        return cls(
            host=config.get("host", "http://localhost:11434"),
            model=config.get("model", "nomic-embed-text"),
        )


# ---------------------------------------------------------------------------
# Vector stores
# ---------------------------------------------------------------------------


class JsonVectorStore:
    """Tiny append-only vector store used when ChromaDB is unavailable."""

    def __init__(self, path: Path, embedder: OllamaEmbedder) -> None:
        """Create/open the JSON store at ``path``."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self.records: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        """Load records from disk, ignoring corrupt files."""
        if self.path.exists():
            try:
                self.records = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.records = []

    def _flush(self) -> None:
        """Persist records to disk."""
        try:
            self.path.write_text(json.dumps(self.records, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            logger.debug("Could not persist JSON memory: %s", exc)

    def add(self, doc_id: str, text: str, metadata: Dict[str, Any]) -> None:
        """Add one document."""
        self.records.append(
            {
                "id": doc_id,
                "text": text,
                "metadata": metadata,
                "embedding": self.embedder.embed_one(text),
            }
        )
        self._flush()

    def query(self, text: str, k: int) -> List[MemoryHit]:
        """Return the ``k`` most similar documents by cosine similarity."""
        if not self.records:
            return []
        query_vec = self.embedder.embed_one(text)
        scored: List[MemoryHit] = []
        for record in self.records:
            vector = record.get("embedding") or []
            score = _cosine(query_vec, vector)
            scored.append(MemoryHit(record["text"], score, record.get("metadata", {})))
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:k]

    def count(self) -> int:
        """Number of stored documents."""
        return len(self.records)

    def wipe(self) -> None:
        """Delete everything."""
        self.records = []
        self._flush()


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two vectors (0.0 when undefined)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class ChromaStore:
    """ChromaDB-backed persistent vector store."""

    def __init__(self, path: Path, collection: str, embedder: OllamaEmbedder) -> None:
        """Open (or create) a persistent Chroma collection.

        Raises:
            RuntimeError: If ChromaDB cannot be initialised.
        """
        try:
            import chromadb
            from chromadb.config import Settings

            ensure_dir(path)
            self.client = chromadb.PersistentClient(
                path=str(path),
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
            self.collection = self.client.get_or_create_collection(
                name=collection,
                embedding_function=embedder,  # type: ignore[arg-type]
                metadata={"hnsw:space": "cosine"},
            )
            self.name = collection
        except Exception as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(f"ChromaDB unavailable: {exc}") from exc

    def add(self, doc_id: str, text: str, metadata: Dict[str, Any]) -> None:
        """Insert one document."""
        self.collection.add(ids=[doc_id], documents=[text], metadatas=[metadata or {}])

    def query(self, text: str, k: int) -> List[MemoryHit]:
        """Return the ``k`` nearest documents as :class:`MemoryHit` objects."""
        count = self.count()
        if count == 0:
            return []
        result = self.collection.query(query_texts=[text], n_results=min(k, count))
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        hits: List[MemoryHit] = []
        for index, document in enumerate(documents):
            distance = distances[index] if index < len(distances) else 1.0
            score = max(0.0, 1.0 - float(distance))  # cosine distance -> similarity
            metadata = metadatas[index] if index < len(metadatas) else {}
            hits.append(MemoryHit(document, score, dict(metadata or {})))
        return hits

    def count(self) -> int:
        """Number of stored documents."""
        try:
            return int(self.collection.count())
        except Exception:
            return 0

    def wipe(self) -> None:
        """Delete and recreate the collection."""
        try:
            self.client.delete_collection(self.name)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Short-term memory
# ---------------------------------------------------------------------------


class ShortTermMemory:
    """Rolling window of recent exchanges held in RAM."""

    def __init__(self, limit: int = 20) -> None:
        """Args:
        limit: Maximum number of exchanges to keep.
        """
        self.limit = max(1, int(limit))
        self._buffer: Deque[Exchange] = deque(maxlen=self.limit)

    def add(self, user: str, assistant: str, intent: str = "") -> Exchange:
        """Append an exchange and return it."""
        exchange = Exchange(user=user, assistant=assistant, intent=intent)
        self._buffer.append(exchange)
        return exchange

    def messages(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """Return recent turns as chat messages for the LLM."""
        items = list(self._buffer)
        if limit:
            items = items[-limit:]
        messages: List[Dict[str, str]] = []
        for exchange in items:
            messages.extend(exchange.to_messages())
        return messages

    def transcript(self, limit: int = 6) -> str:
        """Return a compact plain-text transcript of the last turns."""
        rows = []
        for exchange in list(self._buffer)[-limit:]:
            rows.append(f"User: {truncate(exchange.user, 200)}")
            rows.append(f"JARVIS: {truncate(exchange.assistant, 200)}")
        return "\n".join(rows)

    def last(self) -> Optional[Exchange]:
        """Most recent exchange, if any."""
        return self._buffer[-1] if self._buffer else None

    def clear(self) -> None:
        """Forget the conversation window."""
        self._buffer.clear()

    def drain_oldest(self, count: int) -> List[Exchange]:
        """Remove and return the ``count`` oldest exchanges."""
        removed: List[Exchange] = []
        for _ in range(min(count, len(self._buffer))):
            removed.append(self._buffer.popleft())
        return removed

    def char_length(self) -> int:
        """Rough size of the window in characters (a crude token proxy)."""
        return sum(len(item.user) + len(item.assistant) for item in self._buffer)

    def __len__(self) -> int:
        return len(self._buffer)

    def to_list(self) -> List[Dict[str, Any]]:
        """Serialise the window."""
        return [asdict(exchange) for exchange in self._buffer]

    def load_list(self, rows: Iterable[Dict[str, Any]]) -> None:
        """Restore a serialised window."""
        for row in rows:
            try:
                self._buffer.append(
                    Exchange(
                        user=row.get("user", ""),
                        assistant=row.get("assistant", ""),
                        timestamp=row.get("timestamp", datetime.now().isoformat()),
                        intent=row.get("intent", ""),
                    )
                )
            except Exception:
                continue


# ---------------------------------------------------------------------------
# The combined memory
# ---------------------------------------------------------------------------


class Memory:
    """Short-term + long-term memory with SQLite persistence.

    Example::

        memory = Memory(config)
        await memory.initialize()
        await memory.remember("User prefers metric units", category="preference")
        context = await memory.build_context("what units do I like?")
    """

    def __init__(self, config: Any) -> None:
        """Args:
        config: A :class:`core.config.Config` instance.
        """
        self.config = config
        self.enabled: bool = bool(config.get("memory.enabled", True))
        self.long_term_enabled: bool = bool(config.get("memory.long_term", True))
        self.top_k: int = int(config.get("memory.top_k", 4))
        self.min_relevance: float = float(config.get("memory.min_relevance", 0.2))
        self.short_term = ShortTermMemory(int(config.get("memory.short_term_limit", 20)))
        self.session_id: str = uuid.uuid4().hex[:12]

        self.db_path: Path = config.resolve(config.get("database.path", "data/jarvis.db"))
        self.vector_path: Path = config.resolve(config.get("memory.path", "data/chroma"))
        self.embedder = OllamaEmbedder(
            host=str(config.get("llm.host", "http://localhost:11434")),
            model=str(config.get("memory.embedding_model", "nomic-embed-text")),
        )
        self.store: Optional[Any] = None
        self.backend: str = "disabled"
        self.conversation_summary: str = ""
        self.summarize_enabled: bool = bool(config.get("memory.summarize", True))
        self.summary_trigger: int = int(config.get("memory.summary_trigger", 12))
        self.context_budget: int = int(config.get("memory.context_char_budget", 9000))
        self._lock = asyncio.Lock()
        self._init_sqlite()

    # -- setup --------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        """Open a SQLite connection with sensible defaults."""
        ensure_dir(self.db_path.parent)
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init_sqlite(self) -> None:
        """Create the conversation/fact tables if they do not exist."""
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS conversations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT,
                        timestamp TEXT,
                        role TEXT,
                        content TEXT,
                        intent TEXT
                    );
                    CREATE TABLE IF NOT EXISTS facts (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT,
                        category TEXT,
                        content TEXT,
                        importance REAL DEFAULT 0.5,
                        source TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_conv_session
                        ON conversations(session_id);
                    CREATE INDEX IF NOT EXISTS idx_facts_category
                        ON facts(category);
                    """
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("SQLite memory unavailable: %s", exc)

    async def initialize(self) -> str:
        """Open the vector store and restore the last conversation window.

        Returns:
            The backend name: ``chromadb``, ``json`` or ``disabled``.
        """
        if not self.enabled or not self.long_term_enabled:
            self.backend = "disabled"
            return self.backend

        def _open() -> tuple[Any, str]:
            try:
                store = ChromaStore(
                    self.vector_path,
                    str(self.config.get("memory.collection", "jarvis_memory")),
                    self.embedder,
                )
                return store, "chromadb"
            except Exception as exc:
                logger.info("Falling back to JSON vector memory (%s).", truncate(str(exc), 140))
                store = JsonVectorStore(self.vector_path / "memory.json", self.embedder)
                return store, "json"

        self.store, self.backend = await run_blocking(_open)
        await self.load_recent_window()
        logger.info(
            "Memory ready — backend=%s, long-term entries=%d", self.backend, await self.count()
        )
        return self.backend

    # -- short term ---------------------------------------------------------
    async def add_exchange(self, user: str, assistant: str, intent: str = "") -> None:
        """Record a completed turn in short-term memory and SQLite."""
        self.short_term.add(user, assistant, intent)
        await run_blocking(self._persist_exchange, user, assistant, intent)

    def _persist_exchange(self, user: str, assistant: str, intent: str) -> None:
        """Write a turn into the ``conversations`` table."""
        try:
            stamp = datetime.now().isoformat(timespec="seconds")
            with self._connect() as connection:
                connection.executemany(
                    "INSERT INTO conversations (session_id, timestamp, role, content, intent)"
                    " VALUES (?, ?, ?, ?, ?)",
                    [
                        (self.session_id, stamp, "user", user, intent),
                        (self.session_id, stamp, "assistant", assistant, intent),
                    ],
                )
        except Exception as exc:
            logger.debug("Could not persist exchange: %s", exc)

    async def load_recent_window(self) -> int:
        """Reload the most recent exchanges from SQLite into RAM.

        Returns:
            Number of exchanges restored.
        """

        def _load() -> List[Dict[str, Any]]:
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        "SELECT role, content, timestamp, intent FROM conversations"
                        " ORDER BY id DESC LIMIT ?",
                        (self.short_term.limit * 2,),
                    ).fetchall()
                return [dict(row) for row in reversed(rows)]
            except Exception:
                return []

        rows = await run_blocking(_load)
        pending_user: Optional[Dict[str, Any]] = None
        restored = 0
        for row in rows:
            if row["role"] == "user":
                pending_user = row
            elif row["role"] == "assistant" and pending_user is not None:
                self.short_term.add(
                    pending_user["content"], row["content"], row.get("intent", "") or ""
                )
                pending_user = None
                restored += 1
        return restored

    def context_messages(self, limit: int = 10) -> List[Dict[str, str]]:
        """Recent turns as chat messages, trimmed to the character budget.

        Args:
            limit: Maximum number of exchanges to consider.

        Returns:
            A message list that fits inside ``memory.context_char_budget``.
        """
        messages = self.short_term.messages(limit=limit)
        total = sum(len(message["content"]) for message in messages)
        while messages and total > self.context_budget:
            dropped = messages.pop(0)
            total -= len(dropped["content"])
        return messages

    async def summarize_if_needed(self, llm: Any) -> bool:
        """Compress the oldest half of the window into a running summary.

        Triggered when the window exceeds ``memory.summary_trigger`` exchanges
        or the character budget. The summary is prepended to future system
        prompts and also stored as a long-term memory.

        Args:
            llm: An object exposing ``async complete(prompt, ...) -> str``.

        Returns:
            True when a new summary was produced.
        """
        if not self.summarize_enabled or llm is None:
            return False
        too_many = len(self.short_term) >= self.summary_trigger
        too_long = self.short_term.char_length() > self.context_budget
        if not (too_many or too_long):
            return False

        drained = self.short_term.drain_oldest(max(2, len(self.short_term) // 2))
        if not drained:
            return False

        transcript = "\n".join(
            f"User: {truncate(item.user, 300)}\nJARVIS: {truncate(item.assistant, 300)}"
            for item in drained
        )
        prompt = (
            "Compress this conversation excerpt into a compact briefing for your future "
            "self. Keep decisions, facts about the user, open threads and anything you "
            "promised to do. Drop pleasantries. Maximum 120 words.\n"
            + (f"\nPrevious briefing: {self.conversation_summary}\n" if self.conversation_summary else "")
            + f"\nExcerpt:\n{transcript}"
        )
        try:
            summary = await llm.complete(prompt, temperature=0.2, max_tokens=250)
        except Exception as exc:
            logger.debug("Summarisation failed: %s", exc)
            return False

        summary = (summary or "").strip()
        if not summary:
            return False
        self.conversation_summary = truncate(summary, 1200)
        logger.debug("Conversation summary updated (%d chars).", len(self.conversation_summary))
        await self.remember(
            f"Conversation summary ({datetime.now():%Y-%m-%d %H:%M}): {self.conversation_summary}",
            category="session_summary",
            importance=0.4,
            source="summarizer",
        )
        return True

    # -- long term ----------------------------------------------------------
    async def remember(
        self,
        text: str,
        category: str = "fact",
        importance: float = 0.5,
        source: str = "conversation",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Store a durable memory.

        Args:
            text: The thing worth remembering.
            category: ``fact`` | ``preference`` | ``interaction`` | ``note``.
            importance: 0..1 weighting used when pruning.
            source: Where the memory came from.
            metadata: Extra metadata to attach.

        Returns:
            True when the memory was stored.
        """
        text = (text or "").strip()
        if not text or not self.enabled or self.store is None:
            return False

        payload: Dict[str, Any] = {
            "category": category,
            "importance": float(importance),
            "source": source,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "session": self.session_id,
        }
        payload.update(metadata or {})
        doc_id = hashlib.sha1(f"{category}:{text}".encode("utf-8")).hexdigest()[:24]

        async with self._lock:
            try:
                await run_blocking(self.store.add, doc_id, text, payload)
            except Exception as exc:
                if "existing embedding id" not in str(exc).lower():
                    logger.debug("Vector insert failed: %s", exc)
                    return False
            await run_blocking(self._persist_fact, doc_id, text, category, importance, source)
        logger.debug("Remembered [%s] %s", category, truncate(text, 90))
        return True

    def _persist_fact(
        self, doc_id: str, text: str, category: str, importance: float, source: str
    ) -> None:
        """Mirror a memory into the SQLite ``facts`` table."""
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO facts"
                    " (id, timestamp, category, content, importance, source)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        doc_id,
                        datetime.now().isoformat(timespec="seconds"),
                        category,
                        text,
                        importance,
                        source,
                    ),
                )
        except Exception as exc:
            logger.debug("Could not persist fact: %s", exc)

    async def recall(
        self, query: str, k: Optional[int] = None, min_score: Optional[float] = None
    ) -> List[MemoryHit]:
        """Semantic search over long-term memory.

        Args:
            query: Natural language query.
            k: Number of hits (defaults to ``memory.top_k``).
            min_score: Minimum similarity in ``[0, 1]``.

        Returns:
            Relevant memories, best first.
        """
        if not self.enabled or self.store is None or not (query or "").strip():
            return []
        k = k or self.top_k
        threshold = self.min_relevance if min_score is None else min_score
        try:
            hits: List[MemoryHit] = await run_blocking(self.store.query, query, k)
        except Exception as exc:
            logger.debug("Recall failed: %s", exc)
            return []
        return [hit for hit in hits if hit.score >= threshold]

    async def build_context(self, query: str, k: Optional[int] = None) -> str:
        """Render relevant long-term memories as a prompt-ready block.

        Returns:
            A formatted string, or ``""`` when nothing relevant was found.
        """
        hits = await self.recall(query, k=k)
        if not hits:
            return ""
        lines = [
            f"- ({hit.category}, relevance {hit.score:.2f}) {truncate(hit.text, 240)}"
            for hit in hits
        ]
        return "Relevant things you remember about the user:\n" + "\n".join(lines)

    async def extract_and_store_facts(self, user_text: str, assistant_text: str, llm: Any) -> int:
        """Ask the LLM whether the exchange contains anything worth keeping.

        Args:
            user_text: What the user said.
            assistant_text: What JARVIS replied.
            llm: An object exposing ``async complete(prompt, ...) -> str``.

        Returns:
            Number of facts stored.
        """
        if not self.config.get("memory.auto_extract_facts", True) or llm is None:
            return 0
        if len(user_text.strip()) < 12:
            return 0

        prompt = (
            "Extract durable facts about the USER from this exchange: personal details, "
            "preferences, goals, recurring people/places/projects, or stated constraints.\n"
            "Ignore small talk, one-off questions and anything about the assistant.\n"
            'Reply ONLY with JSON: {"facts": [{"text": "...", "category": '
            '"fact|preference|goal", "importance": 0.0-1.0}]}\n'
            'If nothing is worth remembering, reply {"facts": []}.\n\n'
            f"USER: {truncate(user_text, 600)}\nASSISTANT: {truncate(assistant_text, 600)}"
        )
        try:
            raw = await llm.complete(prompt, temperature=0.1, max_tokens=300)
        except Exception:
            return 0

        from utils.helpers import extract_json  # local import to avoid cycles

        parsed = extract_json(raw) or {}
        facts = parsed.get("facts", []) if isinstance(parsed, dict) else []
        stored = 0
        for entry in facts[:5]:
            if not isinstance(entry, dict):
                continue
            text = str(entry.get("text", "")).strip()
            if len(text) < 8:
                continue
            ok = await self.remember(
                text,
                category=str(entry.get("category", "fact")),
                importance=float(entry.get("importance", 0.5) or 0.5),
                source="auto-extract",
            )
            stored += int(ok)
        return stored

    # -- maintenance --------------------------------------------------------
    async def count(self) -> int:
        """Total number of long-term memories."""
        if self.store is None:
            return 0
        try:
            return int(await run_blocking(self.store.count))
        except Exception:
            return 0

    async def stats(self) -> Dict[str, Any]:
        """Return a summary of memory usage for status displays."""

        def _fact_counts() -> Dict[str, int]:
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        "SELECT category, COUNT(*) AS n FROM facts GROUP BY category"
                    ).fetchall()
                return {row["category"]: row["n"] for row in rows}
            except Exception:
                return {}

        return {
            "backend": self.backend,
            "session": self.session_id,
            "summary": truncate(self.conversation_summary, 160) or "(none)",
            "short_term": len(self.short_term),
            "short_term_limit": self.short_term.limit,
            "long_term": await self.count(),
            "categories": await run_blocking(_fact_counts),
            "database": str(self.db_path),
            "vectors": str(self.vector_path),
        }

    async def search_facts(self, keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Keyword search over the SQLite fact mirror."""

        def _search() -> List[Dict[str, Any]]:
            try:
                with self._connect() as connection:
                    rows = connection.execute(
                        "SELECT content, category, timestamp, importance FROM facts"
                        " WHERE content LIKE ? ORDER BY importance DESC, timestamp DESC LIMIT ?",
                        (f"%{keyword}%", limit),
                    ).fetchall()
                return [dict(row) for row in rows]
            except Exception:
                return []

        return await run_blocking(_search)

    async def forget(self, keyword: str) -> int:
        """Delete facts matching ``keyword`` from SQLite (and JSON store).

        Returns:
            Number of rows removed.
        """

        def _delete() -> int:
            removed = 0
            try:
                with self._connect() as connection:
                    cursor = connection.execute(
                        "DELETE FROM facts WHERE content LIKE ?", (f"%{keyword}%",)
                    )
                    removed = cursor.rowcount or 0
            except Exception:
                removed = 0
            if isinstance(self.store, JsonVectorStore):
                before = len(self.store.records)
                self.store.records = [
                    record
                    for record in self.store.records
                    if keyword.lower() not in record.get("text", "").lower()
                ]
                self.store._flush()  # noqa: SLF001 - internal, same module family
                removed = max(removed, before - len(self.store.records))
            return removed

        return await run_blocking(_delete)

    async def save(self) -> bool:
        """Flush everything to disk (Chroma persists automatically)."""
        try:
            if isinstance(self.store, JsonVectorStore):
                await run_blocking(self.store._flush)  # noqa: SLF001
            return True
        except Exception:
            return False

    async def clear_short_term(self) -> None:
        """Wipe the in-RAM conversation window and the running summary."""
        self.short_term.clear()
        self.conversation_summary = ""

    async def wipe_all(self) -> bool:
        """Destroy every stored memory. Irreversible."""

        def _wipe() -> bool:
            try:
                if self.store is not None:
                    self.store.wipe()
                with self._connect() as connection:
                    connection.execute("DELETE FROM facts")
                    connection.execute("DELETE FROM conversations")
                return True
            except Exception:
                return False

        self.short_term.clear()
        result = await run_blocking(_wipe)
        self.store = None
        await self.initialize()
        return result


__all__ = [
    "Memory",
    "MemoryHit",
    "ShortTermMemory",
    "Exchange",
    "OllamaEmbedder",
    "hash_embedding",
]

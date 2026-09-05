# /modules/knowledge.py
"""Retrieval-augmented answers over your own documents.

Indexes folders you nominate (PDF, DOCX, PPTX, Markdown, code, plain text…)
into a local ChromaDB collection and answers questions from them. Nothing
leaves the machine: extraction, embedding, retrieval and generation are all
local.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.memory import ChromaStore, JsonVectorStore, MemoryHit, OllamaEmbedder
from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.documents import chunk_text, extract_text, is_supported
from utils.helpers import ensure_dir, human_bytes, resolve_user_path, run_blocking, truncate

SKIP_DIRECTORIES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", ".Trash",
    "site-packages", "Library", "AppData", ".mypy_cache", ".pytest_cache", "dist",
    "build", ".next", "target",
}


class Knowledge(BaseModule):
    """A private, local knowledge base built from your own files."""

    name = "knowledge"
    description = (
        "Your personal document knowledge base: index folders of PDFs, Word docs, "
        "notes and code, then answer questions from them with citations. Use this "
        "whenever the user refers to their own documents, papers, contracts or notes."
    )
    intent_examples = [
        "what does my lease say about pets",
        "search my documents for the invoice total",
        "index my documents folder",
        "according to my notes, when is the deadline",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Prepare the vector store and the index bookkeeping table."""
        super().__init__(config, llm=llm, security=security)
        section = config.section("knowledge")
        self.roots: List[str] = list(section.get("paths", ["~/Documents"]) or [])
        self.store_path: Path = config.resolve(section.get("store_path", "data/knowledge"))
        self.collection: str = str(section.get("collection", "jarvis_documents"))
        self.chunk_size: int = int(section.get("chunk_size", 1200))
        self.chunk_overlap: int = int(section.get("chunk_overlap", 150))
        self.max_file_bytes: int = int(float(section.get("max_file_mb", 25)) * 1024 * 1024)
        self.max_files: int = int(section.get("max_files", 5000))
        self.top_k: int = int(section.get("top_k", 5))
        self.min_relevance: float = float(section.get("min_relevance", 0.05))
        self.auto_index: bool = bool(section.get("auto_index_on_start", False))

        self.db_path: Path = config.resolve(config.get("database.path", "data/jarvis.db"))
        self.embedder = OllamaEmbedder(
            host=str(config.get("llm.host", "http://localhost:11434")),
            model=str(config.get("memory.embedding_model", "nomic-embed-text")),
        )
        self.store: Optional[Any] = None
        self.backend: str = "none"
        self._indexing = False
        self._init_db()

    # ------------------------------------------------------------------ infra
    def _connect(self) -> sqlite3.Connection:
        """Open the shared SQLite database."""
        ensure_dir(self.db_path.parent)
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        """Create the table tracking which files have been indexed."""
        try:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS documents (
                        path TEXT PRIMARY KEY,
                        modified INTEGER,
                        size INTEGER,
                        chunks INTEGER,
                        indexed_at TEXT,
                        title TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_documents_indexed
                        ON documents(indexed_at);
                    """
                )
        except Exception as exc:
            self.log.debug("Document table init failed: %s", exc)

    async def setup(self) -> None:
        """Open the vector store, optionally kicking off a background index."""

        def _open() -> Tuple[Any, str]:
            try:
                store = ChromaStore(self.store_path, self.collection, self.embedder)
                return store, "chromadb"
            except Exception as exc:
                self.log.info("Knowledge base falling back to JSON store (%s).",
                              truncate(str(exc), 120))
                return JsonVectorStore(self.store_path / "documents.json", self.embedder), "json"

        self.store, self.backend = await run_blocking(_open)
        if self.auto_index:
            asyncio.create_task(self._background_index())

    async def _background_index(self) -> None:
        """Index the configured roots without blocking start-up."""
        await asyncio.sleep(2)
        for root in self.roots:
            try:
                await self.index_documents(path=root)
            except Exception as exc:
                self.log.debug("Auto-index of %s failed: %s", root, exc)

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing used when no LLM is available."""
        text = strip_command_prefix(command)
        lowered = text.lower()
        if "status" in lowered or "how many documents" in lowered or "what have you indexed" in lowered:
            return "index_status", {}
        if "forget" in lowered or "unindex" in lowered or "remove from knowledge" in lowered:
            return "forget_documents", {"path": text}
        if any(word in lowered for word in ("index", "reindex", "re-index", "scan my")):
            target = ""
            for candidate in ("documents", "downloads", "desktop", "notes"):
                if candidate in lowered:
                    target = candidate
                    break
            return "index_documents", {"path": target}
        if any(word in lowered for word in ("search", "find", "which document", "where did")):
            return "search_documents", {"query": text}
        return "ask_documents", {"question": text}

    # ---------------------------------------------------------------- indexing
    def _iter_documents(self, root: Path) -> List[Path]:
        """Collect indexable files under ``root``."""
        found: List[Path] = []
        if root.is_file():
            return [root] if is_supported(root) else []
        for current, directories, filenames in os.walk(root, topdown=True,
                                                       onerror=lambda _: None):
            directories[:] = [
                name for name in directories
                if name not in SKIP_DIRECTORIES and not name.startswith(".")
            ]
            for filename in filenames:
                if filename.startswith("."):
                    continue
                candidate = Path(current) / filename
                if not is_supported(candidate):
                    continue
                try:
                    if candidate.stat().st_size > self.max_file_bytes:
                        continue
                except Exception:
                    continue
                found.append(candidate)
                if len(found) >= self.max_files:
                    return found
        return found

    def _needs_index(self, path: Path, force: bool) -> bool:
        """Check whether a file is new or modified since the last index."""
        if force:
            return True
        try:
            stat = path.stat()
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT modified, size FROM documents WHERE path = ?", (str(path),)
                ).fetchone()
            if row is None:
                return True
            return int(row["modified"]) != int(stat.st_mtime) or int(row["size"]) != stat.st_size
        except Exception:
            return True

    def _index_one(self, path: Path) -> int:
        """Extract, chunk and embed a single document. Returns chunk count."""
        text = extract_text(path)
        if len(text.strip()) < 40:
            return 0
        chunks = chunk_text(text, self.chunk_size, self.chunk_overlap)
        if not chunks:
            return 0

        stat = path.stat()
        for index, chunk in chunks:
            doc_id = hashlib.sha1(f"{path}:{index}".encode("utf-8")).hexdigest()[:24]
            metadata = {
                "path": str(path),
                "name": path.name,
                "chunk": index,
                "total_chunks": len(chunks),
                "modified": int(stat.st_mtime),
                "suffix": path.suffix.lower(),
            }
            try:
                self.store.add(doc_id, chunk, metadata)  # type: ignore[union-attr]
            except Exception as exc:
                if "existing" not in str(exc).lower():
                    self.log.debug("Chunk insert failed for %s: %s", path.name, exc)

        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO documents"
                " (path, modified, size, chunks, indexed_at, title)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(path),
                    int(stat.st_mtime),
                    int(stat.st_size),
                    len(chunks),
                    datetime.now().isoformat(timespec="seconds"),
                    path.stem,
                ),
            )
        return len(chunks)

    @tool(
        description="Index a folder of documents into the private knowledge base.",
        params={
            "path": {
                "type": "string",
                "description": "Folder or file to index (blank = configured folders)",
                "default": "",
            },
            "force": {
                "type": "boolean",
                "description": "Re-index files even if unchanged",
                "default": False,
            },
        },
        keywords=["index", "reindex", "scan my documents", "build knowledge base",
                  "learn my files"],
        examples=['index_documents(path="~/Documents")'],
    )
    async def index_documents(self, path: str = "", force: bool = False) -> ModuleResult:
        """Walk a folder, extract text and embed it for later retrieval."""
        if self.store is None:
            await self.setup()
        if self.store is None:
            return ModuleResult.fail("The knowledge store could not be opened.")
        if self._indexing:
            return ModuleResult.fail("An indexing run is already in progress, sir.")

        targets = [resolve_user_path(path)] if path else [resolve_user_path(root)
                                                          for root in self.roots]
        targets = [target for target in targets if target.exists()]
        if not targets:
            configured = ", ".join(self.roots) or "(none configured)"
            return ModuleResult.fail(
                f"Nothing to index — no such path, and the configured folders "
                f"({configured}) don't exist."
            )

        self._indexing = True
        started = time.time()

        def _run() -> Dict[str, Any]:
            files_seen = 0
            files_indexed = 0
            chunks_added = 0
            skipped = 0
            errors = 0
            for target in targets:
                for candidate in self._iter_documents(target):
                    files_seen += 1
                    if not self._needs_index(candidate, force):
                        skipped += 1
                        continue
                    try:
                        added = self._index_one(candidate)
                        if added:
                            files_indexed += 1
                            chunks_added += added
                    except Exception as exc:
                        errors += 1
                        self.log.debug("Indexing %s failed: %s", candidate, exc)
            return {
                "seen": files_seen,
                "indexed": files_indexed,
                "chunks": chunks_added,
                "skipped": skipped,
                "errors": errors,
            }

        try:
            stats = await run_blocking(_run)
        finally:
            self._indexing = False

        elapsed = time.time() - started
        summary = (
            f"Indexed {stats['indexed']} document(s) into {stats['chunks']} chunks "
            f"from {', '.join(str(t) for t in targets)} in {elapsed:.1f}s "
            f"({stats['skipped']} already current, {stats['errors']} unreadable)."
        )
        return ModuleResult(
            success=True,
            output=summary,
            speak=f"Knowledge base updated — {stats['indexed']} new or changed documents.",
            data=stats,
        )

    # --------------------------------------------------------------- retrieval
    async def _retrieve(self, query: str, k: Optional[int] = None) -> List[MemoryHit]:
        """Vector-search the knowledge base."""
        if self.store is None:
            await self.setup()
        if self.store is None or not query.strip():
            return []
        try:
            hits: List[MemoryHit] = await run_blocking(self.store.query, query, k or self.top_k)
        except Exception as exc:
            self.log.debug("Knowledge query failed: %s", exc)
            return []
        return [hit for hit in hits if hit.score >= self.min_relevance]

    @tool(
        description="Search your indexed documents and show the matching passages.",
        params={
            "query": {"type": "string", "description": "What to look for", "required": True},
            "k": {"type": "integer", "description": "Number of passages", "default": 5},
        },
        keywords=["search my documents", "find in my files", "which document mentions",
                  "look in my notes"],
    )
    async def search_documents(self, query: str, k: int = 5) -> ModuleResult:
        """Return the most relevant passages with their source files."""
        hits = await self._retrieve(query, k)
        if not hits:
            return ModuleResult(
                success=True,
                output=f"Nothing in the knowledge base matches '{query}'. "
                "Index some folders first with 'index my documents'.",
                data={"hits": []},
            )
        lines = []
        for hit in hits:
            name = hit.metadata.get("name", "?")
            chunk = hit.metadata.get("chunk", 0)
            lines.append(
                f"[{name} · chunk {chunk} · {hit.score:.2f}]\n{truncate(hit.text, 400)}"
            )
        return ModuleResult(
            success=True,
            output="\n\n".join(lines),
            data={
                "hits": [
                    {"path": hit.metadata.get("path", ""), "score": hit.score,
                     "text": truncate(hit.text, 400)}
                    for hit in hits
                ]
            },
        )

    @tool(
        description="Answer a question using only your indexed documents, with citations.",
        params={
            "question": {"type": "string", "description": "The question", "required": True},
            "k": {"type": "integer", "description": "Passages to consider", "default": 6},
        },
        keywords=["according to my documents", "what does my", "in my files", "ask my documents",
                  "my notes say", "from my pdfs"],
        examples=['ask_documents(question="what is the notice period in my lease")'],
    )
    async def ask_documents(self, question: str, k: int = 6) -> ModuleResult:
        """Retrieval-augmented answer grounded in the user's own files."""
        hits = await self._retrieve(question, k)
        if not hits:
            return ModuleResult(
                success=True,
                output="I have nothing indexed that relates to that. Say 'index my documents' "
                "and point me at a folder.",
                data={"sources": []},
            )

        context = "\n\n".join(
            f"[{index}] {hit.metadata.get('name', 'document')} "
            f"(chunk {hit.metadata.get('chunk', 0)}):\n{hit.text}"
            for index, hit in enumerate(hits, 1)
        )
        sources = sorted({hit.metadata.get("path", "") for hit in hits if hit.metadata.get("path")})

        if self.llm is None or not getattr(self.llm, "available", False):
            return ModuleResult(
                success=True,
                output=f"(No LLM available, showing raw passages)\n\n{truncate(context, 2500)}",
                data={"sources": sources},
            )

        answer = await self.llm.complete(
            f"Answer the question using ONLY these excerpts from the user's own documents. "
            f"Cite the document names you used. If the excerpts don't contain the answer, "
            f"say so plainly.\n\nEXCERPTS:\n{truncate(context, 9000)}\n\n"
            f"QUESTION: {question}",
            temperature=0.2,
            max_tokens=600,
        )
        body = answer.strip() or truncate(context, 1500)
        names = ", ".join(Path(source).name for source in sources[:4])
        return ModuleResult(
            success=True,
            output=f"{body}\n\nSources: {names}" if names else body,
            data={"sources": sources},
        )

    @tool(
        description="Show what is currently in the knowledge base.",
        params={},
        keywords=["knowledge base status", "how many documents indexed", "index status"],
    )
    async def index_status(self) -> ModuleResult:
        """Report indexed document counts and the most recent additions."""

        def _stats() -> Dict[str, Any]:
            try:
                with self._connect() as connection:
                    total = connection.execute(
                        "SELECT COUNT(*) AS n, SUM(chunks) AS c, SUM(size) AS s FROM documents"
                    ).fetchone()
                    recent = connection.execute(
                        "SELECT path, chunks, indexed_at FROM documents"
                        " ORDER BY indexed_at DESC LIMIT 5"
                    ).fetchall()
                return {
                    "documents": int(total["n"] or 0),
                    "chunks": int(total["c"] or 0),
                    "bytes": int(total["s"] or 0),
                    "recent": [dict(row) for row in recent],
                }
            except Exception:
                return {"documents": 0, "chunks": 0, "bytes": 0, "recent": []}

        stats = await run_blocking(_stats)
        vectors = 0
        if self.store is not None:
            try:
                vectors = await run_blocking(self.store.count)
            except Exception:
                vectors = 0
        lines = [
            f"Knowledge base ({self.backend}): {stats['documents']} documents, "
            f"{stats['chunks']} chunks, {vectors} vectors, "
            f"{human_bytes(stats['bytes'])} of source material.",
            f"Watching: {', '.join(self.roots) or '(nothing configured)'}",
        ]
        if stats["recent"]:
            lines.append("Most recently indexed:")
            lines += [
                f"  {Path(row['path']).name} ({row['chunks']} chunks, {row['indexed_at'][:16]})"
                for row in stats["recent"]
            ]
        return ModuleResult(success=True, output="\n".join(lines), data=stats)

    @tool(
        description="Remove documents from the knowledge base by path fragment.",
        params={
            "path": {"type": "string", "description": "Path or filename fragment",
                     "required": True}
        },
        dangerous=True,
        keywords=["forget the document", "remove from knowledge base", "unindex"],
    )
    async def forget_documents(self, path: str) -> ModuleResult:
        """Drop indexed documents matching a path fragment."""
        needle = (path or "").strip()
        if not needle:
            return ModuleResult.fail("Which documents?")

        def _forget() -> int:
            removed = 0
            try:
                with self._connect() as connection:
                    cursor = connection.execute(
                        "DELETE FROM documents WHERE path LIKE ?", (f"%{needle}%",)
                    )
                    removed = cursor.rowcount or 0
            except Exception:
                removed = 0
            if isinstance(self.store, JsonVectorStore):
                before = len(self.store.records)
                self.store.records = [
                    record for record in self.store.records
                    if needle.lower() not in str(record.get("metadata", {}).get("path", "")).lower()
                ]
                self.store._flush()  # noqa: SLF001
                removed = max(removed, before - len(self.store.records))
            return removed

        removed = await run_blocking(_forget)
        note = (
            " (Chroma vectors remain until the next full re-index — "
            "run index_documents with force to rebuild.)"
            if self.backend == "chromadb" and removed
            else ""
        )
        return ModuleResult.ok(f"Removed {removed} document record(s).{note}")


__all__ = ["Knowledge"]

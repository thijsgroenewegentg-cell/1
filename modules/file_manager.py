# /modules/file_manager.py
"""Smart file operations: search, organise, summarise documents and analyse CSVs."""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Tuple

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.documents import extract_text
from utils.helpers import (
    ensure_dir,
    friendly_when,
    human_bytes,
    looks_binary,
    read_text_file,
    resolve_user_path,
    run_blocking,
    truncate,
)

# Extension -> category used by ``organize_files``.
CATEGORIES: Dict[str, Tuple[str, ...]] = {
    "Images": (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp", ".heic", ".tiff", ".ico"),
    "Documents": (".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".tex", ".epub"),
    "Spreadsheets": (".xls", ".xlsx", ".csv", ".ods", ".tsv"),
    "Presentations": (".ppt", ".pptx", ".odp", ".key"),
    "Audio": (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus", ".aiff"),
    "Video": (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"),
    "Archives": (".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".xz", ".tgz"),
    "Code": (".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs", ".rb", ".php",
             ".html", ".css", ".sh", ".sql", ".json", ".yaml", ".yml", ".toml", ".ipynb"),
    "Installers": (".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".appimage"),
    "Fonts": (".ttf", ".otf", ".woff", ".woff2"),
}

SKIP_DIRECTORIES = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache",
    "site-packages", ".cache", "Library", "AppData", "System Volume Information", ".Trash",
}

TEXT_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".csv",
                   ".log", ".ini", ".cfg", ".toml", ".html", ".css", ".sh", ".sql", ".xml"}


class FileManager(BaseModule):
    """Find, organise, read and summarise files on disk."""

    name = "file_manager"
    description = (
        "Smart file operations: find files by name or content, organise a folder by file "
        "type, summarise documents (PDF/DOCX/TXT/MD), analyse CSV files, find duplicates "
        "and report folder sizes."
    )
    intent_examples: ClassVar[List[str]] = [
        "find all PDFs on my desktop",
        "organize my downloads folder",
        "summarize this document",
        "what's taking up space in my home folder",
    ]

    #: Journal of every move JARVIS makes, so it can be undone.
    JOURNAL_SCHEMA = """
    CREATE TABLE IF NOT EXISTS file_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        description TEXT NOT NULL,
        moves TEXT NOT NULL,
        created TEXT NOT NULL,
        undone INTEGER DEFAULT 0
    );
    """

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Cache config values and prepare the undo journal."""
        super().__init__(config, llm=llm, security=security)
        self.max_scan_files = 40_000
        self.last_document: str = ""
        self.db_path: Path = config.resolve(config.get("database.path", "data/jarvis.db"))
        self.journal_limit: int = int(config.get("file_manager.journal_entries", 50) or 50)
        try:
            ensure_dir(self.db_path.parent)
            with self._journal() as connection:
                connection.executescript(self.JOURNAL_SCHEMA)
        except Exception as exc:  # pragma: no cover - defensive
            self.log.warning("Could not prepare the file journal: %s", exc)

    # -------------------------------------------------------------- journal
    @contextlib.contextmanager
    def _journal(self) -> Iterator[sqlite3.Connection]:
        """Open a SQLite connection and guarantee it is closed again.

        ``with sqlite3.connect(...) as connection`` commits the transaction
        but leaves the connection *open* — a long-running assistant leaked a
        file descriptor per database write and would eventually hit the
        process limit, at which point nothing could open a file at all.

        Yields:
            A connection with ``sqlite3.Row`` rows in WAL mode.
        """
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _record_moves(self, kind: str, description: str,
                      moves: List[Tuple[str, str]]) -> int:
        """Store a completed batch of moves so it can be reversed.

        Args:
            kind: ``organize``, ``move`` or ``rename``.
            description: Human summary shown by :meth:`recent_operations`.
            moves: ``(source, destination)`` pairs that actually happened.

        Returns:
            The journal entry id, or ``0`` when nothing was recorded.
        """
        if not moves:
            return 0
        try:
            with self._journal() as connection:
                cursor = connection.execute(
                    "INSERT INTO file_operations (kind, description, moves, created) "
                    "VALUES (?, ?, ?, ?)",
                    (kind, description, json.dumps(moves),
                     datetime.now().isoformat(timespec="seconds")),
                )
                # Keep the journal from growing without bound.
                connection.execute(
                    "DELETE FROM file_operations WHERE id NOT IN "
                    "(SELECT id FROM file_operations ORDER BY id DESC LIMIT ?)",
                    (self.journal_limit,),
                )
                return int(cursor.lastrowid or 0)
        except Exception as exc:  # pragma: no cover - defensive
            self.log.warning("Could not journal a file operation: %s", exc)
            return 0

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _iter_files(root: Path, recursive: bool = True, limit: int = 40_000) -> Iterable[Path]:
        """Walk ``root`` yielding files, skipping noisy directories."""
        count = 0
        if not recursive:
            try:
                for entry in root.iterdir():
                    if entry.is_file():
                        yield entry
                        count += 1
                        if count >= limit:
                            return
            except Exception:
                return
            return
        for current, directories, filenames in os.walk(root, topdown=True, onerror=lambda _: None):
            directories[:] = [
                name for name in directories
                if name not in SKIP_DIRECTORIES and not name.startswith(".")
            ]
            for filename in filenames:
                yield Path(current) / filename
                count += 1
                if count >= limit:
                    return

    @staticmethod
    def _describe(path: Path) -> str:
        """One-line description of a file."""
        try:
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            return f"{path} — {human_bytes(stat.st_size)}, modified {modified}"
        except Exception:
            return str(path)

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing with parameter extraction (used without an LLM)."""
        text = strip_command_prefix(command)
        lowered = text.lower()

        location = "~"
        for name in ("desktop", "downloads", "documents", "pictures", "music", "videos",
                     "home folder", "home directory"):
            if name in lowered:
                location = name.split()[0]
                break
        explicit = re.search(r"(?:in|on|under|inside)\s+(~?[\w./~-]+/[\w./~-]*|~[\w./-]*)", text)
        if explicit:
            location = explicit.group(1)
        else:
            # A bare folder name ("in core", "in Projects") only counts when a
            # directory of that name really exists, so ordinary English like
            # "in my todo list" cannot be mistaken for a path.
            bare = re.search(r"(?:in|under|inside)\s+(?:the\s+|my\s+)?([\w.-]+)\b", text)
            if bare:
                for base in (Path.cwd(), Path.home()):
                    if (base / bare.group(1)).is_dir():
                        location = str(base / bare.group(1))
                        break

        if any(phrase in lowered for phrase in
               ("undo that", "undo the move", "undo the last", "put them back",
                "put it back", "move them back", "revert the file", "unorganise",
                "unorganize", "undo the organis", "undo the organiz")):
            number = re.search(r"#?(\d+)", lowered)
            return "undo_file_operation", {"operation": int(number.group(1)) if number else 0}

        if any(phrase in lowered for phrase in
               ("what files did you move", "recent file operation", "file history",
                "what did you move", "list file operations")):
            return "recent_operations", {}

        if any(phrase in lowered for phrase in ("organize", "organise", "tidy", "clean up")):
            return "organize_files", {
                "path": location,
                "dry_run": not any(w in lowered for w in ("for real", "actually", "do it",
                                                          "confirm", "no preview")),
            }

        if any(phrase in lowered for phrase in
               ("summarize", "summarise", "tldr", "what's in this document")):
            path = re.search(r"([\w./~-]+\.(?:pdf|docx?|txt|md|csv|epub))", text, re.IGNORECASE)
            if path:
                return "summarize_document", {"path": path.group(1)}
            # "summarise this document" with no filename: the tool knows to ask
            # which one, or to reuse the document already in hand.
            if any(word in lowered for word in
                   ("document", "file", "pdf", "this doc", "the doc", "paper")):
                return "summarize_document", {"path": ""}

        csv_path = re.search(r"([\w./~-]+\.csv)", text, re.IGNORECASE)
        if csv_path:
            return "analyze_csv", {"path": csv_path.group(1)}
        if "csv" in lowered or "spreadsheet" in lowered:
            return "analyze_csv", {"path": ""}

        if any(phrase in lowered for phrase in ("duplicate", "duplicates", "same file twice")):
            return "find_duplicates", {"path": location}

        if any(phrase in lowered for phrase in ("biggest", "largest", "taking up space",
                                                "space hogs", "disk usage")):
            return "largest_files", {"path": location}

        if any(phrase in lowered for phrase in ("how big", "folder size", "count files",
                                                "what's in the folder")):
            return "folder_stats", {"path": location}

        contains = re.search(r"contain(?:ing|s)?\s+[\"']?([^\"']+)[\"']?", lowered)
        if contains and any(w in lowered for w in ("file", "files", "document")):
            return "search_content", {"text": contains.group(1).strip(), "path": location}

        # Content searches inside files: "search my files for the word budget"
        # is search_content (look inside the text), whereas a bare "find files"
        # matches by name. The tell is naming a word/phrase/term/mention.
        mention = re.search(
            r"\b(?:files?|documents?)\s+(?:that|which)?\s*(?:mention|refer to)\s+"
            r"(.+)$", lowered,
        )
        content = re.search(
            r"\b(?:search|look|scan|find|grep)\s+(?:my\s+|the\s+|your\s+)?files?\s+"
            r"for\s+(?:the\s+)?(?:word|text|phrase|term|contents?)?\s*(.+)$",
            lowered,
        )
        if content and any(marker in lowered for marker in
                           ("word", "text", "phrase", "term", "mention", "about",
                            "says", "mentions")):
            return "search_content", {
                "text": content.group(1).strip(), "path": location,
            }
        if mention:
            return "search_content", {
                "text": mention.group(1).strip(), "path": location,
            }

        known_extensions = {
            "pdf", "png", "jpg", "jpeg", "gif", "mp3", "mp4", "csv", "txt", "md", "doc",
            "docx", "xls", "xlsx", "ppt", "pptx", "zip", "py", "js", "ts", "json", "log",
        }
        # People ask for "python files", not "py files". Without this the
        # extension scan found nothing and quietly searched for *everything*.
        spoken_types = {
            "python": "*.py", "javascript": "*.js", "typescript": "*.ts",
            "markdown": "*.md", "spreadsheet": "*.xlsx|*.xls|*.csv",
            "spreadsheets": "*.xlsx|*.xls|*.csv",
            "presentation": "*.pptx|*.ppt", "presentations": "*.pptx|*.ppt",
            "image": "*.png|*.jpg|*.jpeg|*.gif|*.webp",
            "images": "*.png|*.jpg|*.jpeg|*.gif|*.webp",
            "photo": "*.jpg|*.jpeg|*.png", "photos": "*.jpg|*.jpeg|*.png",
            "picture": "*.png|*.jpg|*.jpeg", "pictures": "*.png|*.jpg|*.jpeg",
            "video": "*.mp4|*.mov|*.mkv|*.avi", "videos": "*.mp4|*.mov|*.mkv|*.avi",
            "music": "*.mp3|*.flac|*.m4a|*.wav", "song": "*.mp3|*.flac|*.m4a",
            "songs": "*.mp3|*.flac|*.m4a", "archive": "*.zip|*.tar|*.gz|*.7z",
            "archives": "*.zip|*.tar|*.gz|*.7z",
        }
        if any(word in lowered for word in ("find", "search", "list", "show", "locate", "where")):
            candidate = ""
            for token in re.findall(r"[a-z0-9]+", lowered):
                singular = token[:-1] if len(token) > 3 and token.endswith("s") else token
                if token in known_extensions:
                    candidate = token
                    break
                if singular in known_extensions:
                    candidate = singular
                    break
                if token in spoken_types:
                    return "find_files", {"pattern": spoken_types[token], "path": location}
            if candidate:
                return "find_files", {"pattern": f"*.{candidate}", "path": location}
            named = re.search(r"(?:file|files)\s+(?:called|named)\s+([\w.*?-]+)", lowered)
            if named:
                return "find_files", {"pattern": named.group(1), "path": location}
            return "find_files", {"pattern": "*", "path": location}

        path_like = re.search(r"([\w./~-]+\.[a-z0-9]{1,6})", text, re.IGNORECASE)
        if path_like and any(w in lowered for w in ("read", "open", "show", "cat")):
            return "read_file", {"path": path_like.group(1)}

        return None

    # ----------------------------------------------------------------- search
    @tool(
        description="Find files by name pattern, extension and/or text content.",
        params={
            "pattern": {
                "type": "string",
                "description": "Name pattern or extension, e.g. '*.pdf' or 'invoice'",
                "default": "*",
            },
            "path": {"type": "string", "description": "Folder to search", "default": "~"},
            "contains": {
                "type": "string",
                "description": "Only match files containing this text",
                "default": "",
            },
            "limit": {"type": "integer", "description": "Max results", "default": 25},
            "recursive": {"type": "boolean", "description": "Search subfolders", "default": True},
        },
        keywords=["find file", "find all", "search for files", "locate", "where is the file",
                  "list files", "pdfs on my", "files in"],
        examples=['find_files(pattern="*.pdf", path="desktop")'],
    )
    async def find_files(
        self,
        pattern: str = "*",
        path: str = "~",
        contains: str = "",
        limit: int = 25,
        recursive: bool = True,
    ) -> ModuleResult:
        """Search the filesystem for matching files."""
        root = resolve_user_path(path)
        if not root.exists():
            return ModuleResult.fail(f"{root} doesn't exist.")
        if root.is_file():
            root = root.parent

        raw_pattern = (pattern or "*").strip()
        if raw_pattern.startswith("."):
            glob_pattern = f"*{raw_pattern}"
        elif any(char in raw_pattern for char in "*?[") or raw_pattern == "*":
            glob_pattern = raw_pattern
        else:
            glob_pattern = f"*{raw_pattern}*"
        needle = (contains or "").strip().lower()
        # A pattern may list alternatives ("*.png|*.jpg"), which is how one
        # request for "images" covers every image extension.
        globs = [part.strip().lower() for part in re.split(r"[|,]", glob_pattern)
                 if part.strip()] or ["*"]

        def _scan() -> List[Dict[str, Any]]:
            matches: List[Dict[str, Any]] = []
            for file_path in self._iter_files(root, recursive, self.max_scan_files):
                name = file_path.name.lower()
                if not any(fnmatch.fnmatch(name, glob) for glob in globs):
                    continue
                if needle:
                    if file_path.suffix.lower() not in TEXT_EXTENSIONS:
                        continue
                    try:
                        if file_path.stat().st_size > 5_000_000:
                            continue
                    except Exception:
                        continue
                    if needle not in read_text_file(file_path, 400_000).lower():
                        continue
                try:
                    size = file_path.stat().st_size
                    modified = file_path.stat().st_mtime
                except Exception:
                    size, modified = 0, 0.0
                matches.append(
                    {"path": str(file_path), "size": size, "modified": modified,
                     "name": file_path.name}
                )
                if len(matches) >= int(limit):
                    break
            matches.sort(key=lambda item: item["modified"], reverse=True)
            return matches

        matches = await run_blocking(_scan)
        if not matches:
            hint = f" containing '{contains}'" if contains else ""
            return ModuleResult(
                success=True,
                output=f"No files matching '{raw_pattern}'{hint} under {root}.",
                data={"files": []},
            )

        lines = [
            f"{index}. {item['path']} ({human_bytes(item['size'])})"
            for index, item in enumerate(matches, 1)
        ]
        return ModuleResult(
            success=True,
            output=f"Found {len(matches)} file(s) under {root}:\n" + "\n".join(lines),
            speak=f"Found {len(matches)} matching files, the most recent being "
            f"{Path(matches[0]['path']).name}.",
            data={"files": matches, "root": str(root)},
        )

    @tool(
        description="Search inside text files for a phrase (like grep).",
        params={
            "text": {"type": "string", "description": "Phrase to find", "required": True},
            "path": {"type": "string", "description": "Folder to search", "default": "~"},
            "limit": {"type": "integer", "description": "Max matches", "default": 20},
        },
        untrusted=True,
        keywords=["grep", "search inside files", "which file contains", "find text in"],
    )
    async def search_content(self, text: str, path: str = "~", limit: int = 20) -> ModuleResult:
        """Grep-style content search with matching line previews."""
        needle = (text or "").strip()
        if not needle:
            return ModuleResult.fail("What text am I looking for?")
        root = resolve_user_path(path)
        if not root.exists():
            return ModuleResult.fail(f"{root} doesn't exist.")

        def _scan() -> List[Dict[str, Any]]:
            hits: List[Dict[str, Any]] = []
            lowered = needle.lower()
            for file_path in self._iter_files(root, True, self.max_scan_files):
                if file_path.suffix.lower() not in TEXT_EXTENSIONS:
                    continue
                # Skipped silently: prompting once per credential file during a
                # bulk scan is unusable, and a match line would print the key.
                if self.security is not None and self.security.is_sensitive_path(file_path):
                    continue
                try:
                    if file_path.stat().st_size > 5_000_000:
                        continue
                except Exception:
                    continue
                content = read_text_file(file_path, 400_000)
                if lowered not in content.lower():
                    continue
                for number, line in enumerate(content.splitlines(), 1):
                    if lowered in line.lower():
                        hits.append(
                            {"path": str(file_path), "line": number,
                             "text": truncate(line.strip(), 160)}
                        )
                        break
                if len(hits) >= int(limit):
                    break
            return hits

        hits = await run_blocking(_scan)
        if not hits:
            return ModuleResult(
                success=True, output=f"No files under {root} contain '{needle}'.", data={"hits": []}
            )
        lines = [f"{hit['path']}:{hit['line']}: {hit['text']}" for hit in hits]
        return ModuleResult(
            success=True,
            output=f"{len(hits)} match(es) for '{needle}':\n" + "\n".join(lines),
            data={"hits": hits},
        )

    # --------------------------------------------------------------- organise
    @tool(
        description="Organise a folder by moving files into type-based subfolders.",
        params={
            "path": {"type": "string", "description": "Folder to organise", "required": True},
            "dry_run": {
                "type": "boolean",
                "description": "Preview without moving anything",
                "default": True,
            },
        },
        dangerous=True,
        keywords=["organize", "organise", "tidy up", "clean up folder", "sort my files"],
        examples=['organize_files(path="downloads", dry_run=false)'],
    )
    async def organize_files(self, path: str, dry_run: bool = True) -> ModuleResult:
        """Sort loose files into Images/Documents/Code/… subfolders."""
        root = resolve_user_path(path)
        if not root.exists() or not root.is_dir():
            return ModuleResult.fail(f"{root} is not a folder.")

        refusal = await self.guard_path(root, write=True, what="reorganise")
        if refusal is not None:
            return refusal

        extension_map: Dict[str, str] = {
            extension: category
            for category, extensions in CATEGORIES.items()
            for extension in extensions
        }

        def _organize() -> Dict[str, Any]:
            plan: Dict[str, List[str]] = defaultdict(list)
            journal: List[Tuple[str, str]] = []
            moved, failed = 0, 0
            for entry in sorted(root.iterdir()):
                if not entry.is_file() or entry.name.startswith("."):
                    continue
                category = extension_map.get(entry.suffix.lower(), "Other")
                plan[category].append(entry.name)
                if dry_run:
                    continue
                destination = root / category
                try:
                    ensure_dir(destination)
                    target = destination / entry.name
                    counter = 1
                    while target.exists():
                        target = destination / f"{entry.stem}-{counter}{entry.suffix}"
                        counter += 1
                    shutil.move(str(entry), str(target))
                    journal.append((str(entry), str(target)))
                    moved += 1
                except Exception:
                    failed += 1
            return {"plan": dict(plan),
                    "moved": moved, "failed": failed, "journal": journal}

        result = await run_blocking(_organize)
        plan: Dict[str, List[str]] = result["plan"]
        if not plan:
            return ModuleResult(success=True, output=f"{root} has no loose files to organise.")

        summary = "\n".join(
            f"{category}: {len(names)} file(s) — {truncate(', '.join(names[:5]), 100)}"
            for category, names in sorted(plan.items())
        )
        if dry_run:
            return ModuleResult(
                success=True,
                output=f"Plan for {root} (nothing moved yet):\n{summary}\n\n"
                "Say yes and I'll apply it.",
                speak=f"I can sort {sum(len(v) for v in plan.values())} files into "
                f"{len(plan)} categories. Shall I go ahead?",
                data={"plan": plan, "dry_run": True},
            ).offering(
                "file_manager.organize_files",
                {"path": str(root), "dry_run": False},
                f"Organise {root} for real?",
            )
        entry_id = await run_blocking(
            self._record_moves, "organize", f"organised {root}", result.get("journal", [])
        )
        undo_hint = (f" Say 'undo that' if it is not what you wanted (operation #{entry_id})."
                     if entry_id else "")
        return ModuleResult(
            success=True,
            output=f"Organised {root}: moved {result['moved']} file(s), "
            f"{result['failed']} failure(s).\n{summary}{undo_hint}",
            speak=f"Moved {result['moved']} files into {len(plan)} folders, sir."
                  + (" Say undo that if you want them back." if entry_id else ""),
            data={"plan": result["plan"], "moved": result["moved"],
                  "failed": result["failed"], "operation": entry_id},
        )

    @tool(
        description="Show the biggest files or folders in a directory.",
        params={
            "path": {"type": "string", "description": "Folder", "default": "~"},
            "limit": {"type": "integer", "description": "How many entries", "default": 10},
        },
        keywords=["disk usage", "biggest files", "what's taking up space", "largest folders",
                  "space hogs"],
    )
    async def largest_files(self, path: str = "~", limit: int = 10) -> ModuleResult:
        """List the largest files under a directory."""
        root = resolve_user_path(path)
        if not root.exists():
            return ModuleResult.fail(f"{root} doesn't exist.")

        def _scan() -> List[Dict[str, Any]]:
            entries: List[Dict[str, Any]] = []
            for file_path in self._iter_files(root, True, self.max_scan_files):
                try:
                    entries.append({"path": str(file_path), "size": file_path.stat().st_size})
                except Exception:
                    continue
            entries.sort(key=lambda item: item["size"], reverse=True)
            return entries[: int(limit)]

        entries = await run_blocking(_scan)
        if not entries:
            return ModuleResult(success=True, output=f"No files found under {root}.")
        total = sum(entry["size"] for entry in entries)
        lines = [f"{human_bytes(entry['size']):>10}  {entry['path']}" for entry in entries]
        return ModuleResult(
            success=True,
            output=f"Largest files under {root} ({human_bytes(total)} combined):\n"
            + "\n".join(lines),
            data={"files": entries},
        )

    @tool(
        description="Find duplicate files by content hash.",
        params={
            "path": {"type": "string", "description": "Folder", "default": "~/Downloads"},
            "limit": {"type": "integer", "description": "Max duplicate groups", "default": 10},
        },
        keywords=["duplicates", "duplicate files", "same file twice", "copies of"],
    )
    async def find_duplicates(self, path: str = "~/Downloads", limit: int = 10) -> ModuleResult:
        """Group files that share identical content."""
        root = resolve_user_path(path)
        if not root.exists():
            return ModuleResult.fail(f"{root} doesn't exist.")

        def _scan() -> List[List[str]]:
            by_size: Dict[int, List[Path]] = defaultdict(list)
            for file_path in self._iter_files(root, True, self.max_scan_files):
                try:
                    size = file_path.stat().st_size
                except Exception:
                    continue
                if size > 0:
                    by_size[size].append(file_path)

            groups: List[List[str]] = []
            for size, paths in by_size.items():
                if len(paths) < 2 or size > 200_000_000:
                    continue
                by_hash: Dict[str, List[str]] = defaultdict(list)
                for candidate in paths:
                    try:
                        digest = hashlib.md5()
                        with candidate.open("rb") as handle:
                            for chunk in iter(lambda: handle.read(1 << 20), b""):
                                digest.update(chunk)
                        by_hash[digest.hexdigest()].append(str(candidate))
                    except Exception:
                        continue
                groups.extend([paths for paths in by_hash.values() if len(paths) > 1])
                if len(groups) >= int(limit):
                    break
            return groups[: int(limit)]

        groups = await run_blocking(_scan)
        if not groups:
            return ModuleResult(success=True, output=f"No duplicates found under {root}.")
        lines = []
        for index, group in enumerate(groups, 1):
            lines.append(f"{index}. {len(group)} copies:")
            lines.extend(f"    {item}" for item in group)
        return ModuleResult(
            success=True,
            output=f"Duplicate groups under {root}:\n" + "\n".join(lines),
            data={"groups": groups},
        )

    # -------------------------------------------------------------- documents
    def _extract_document(self, path: Path, limit: int = 60_000) -> str:
        """Extract plain text from PDF, DOCX, PPTX, HTML or any text-ish file.

        Delegates to :func:`utils.documents.extract_text` so the file manager and
        the knowledge base always read documents the same way.

        Args:
            path: File to read.
            limit: Maximum number of characters to return.

        Returns:
            The extracted text, or ``""`` when nothing could be read.
        """
        try:
            return extract_text(path, limit=limit)
        except Exception as exc:
            self.log.debug("Extraction failed for %s: %s", path, exc)
            return ""

    @tool(
        description="Summarise a document (PDF, DOCX, TXT, MD, CSV).",
        params={
            "path": {"type": "string", "description": "File path", "required": True},
            "question": {
                "type": "string",
                "description": "Optional question to answer from the document",
                "default": "",
            },
        },
        untrusted=True,
        keywords=["summarize this document", "summarise the pdf", "what's in this file",
                  "read this document", "tldr of the file"],
    )
    async def summarize_document(self, path: str = "", question: str = "") -> ModuleResult:
        """Extract a document's text and summarise it with the local LLM.

        Args:
            path: The document. Empty means "the one we were just discussing";
                if there is none, JARVIS asks which file to open.
            question: Optional question to answer from the document instead of
                a general summary.

        Returns:
            A :class:`ModuleResult` with the summary.
        """
        if not str(path or "").strip():
            if self.last_document.strip():
                return await self._summarise_text(self.last_document, question)
            return ModuleResult.fail(
                "Which document, sir? Give me a path and I'll read it."
            )
        target = resolve_user_path(path)
        if not target.exists() or not target.is_file():
            return ModuleResult.fail(f"No file at {target}.")
        refusal = await self.guard_path(target, write=False, what="read")
        if refusal is not None:
            return refusal

        text = await run_blocking(self._extract_document, target)
        if not text.strip():
            return ModuleResult.fail(
                f"I couldn't extract any text from {target.name} "
                "(it may be a scanned image or an unsupported format)."
            )
        self.last_document = text
        return await self._summarise_text(text, question, target.name, str(target))

    async def _summarise_text(
        self, text: str, question: str = "", label: str = "the document",
        path: str = "",
    ) -> ModuleResult:
        """Summarise already-extracted text, or answer a question about it.

        Args:
            text: The document's text.
            question: Optional question to answer instead of summarising.
            label: What to call the document in the reply.
            path: Where it came from, for the result data.

        Returns:
            A :class:`ModuleResult`; without a model it returns the opening
            of the document rather than nothing at all.
        """
        words = len(text.split())
        if self.llm is None or not getattr(self.llm, "available", False):
            return ModuleResult(
                success=True,
                output=f"{label} — {words} words. First part:\n{truncate(text, 1500)}",
                data={"path": path, "words": words},
            )

        instruction = (
            f"Answer this question using only the document: {question}"
            if question
            else "Summarise the document in 5 sentences, then list up to 5 key points."
        )
        summary = await self.llm.complete(
            f"DOCUMENT: {label}\n\n{truncate(text, 12000)}\n\n{instruction}",
            temperature=0.3,
            max_tokens=650,
        )
        return ModuleResult(
            success=True,
            output=summary.strip() or truncate(text, 1500),
            data={"path": path, "words": words},
        )

    @tool(
        description="Analyse a CSV file: shape, columns, statistics and a preview.",
        params={
            "path": {"type": "string", "description": "CSV path", "required": True},
            "question": {
                "type": "string",
                "description": "Optional question about the data",
                "default": "",
            },
        },
        untrusted=True,
        keywords=["csv", "spreadsheet", "analyse the data", "analyze the data", "read the csv"],
    )
    async def analyze_csv(self, path: str, question: str = "") -> ModuleResult:
        """Describe a CSV file, optionally answering a question about it."""
        target = resolve_user_path(path)
        if not target.exists():
            return ModuleResult.fail(f"No file at {target}.")
        refusal = await self.guard_path(target, write=False, what="read")
        if refusal is not None:
            return refusal

        def _analyze() -> Dict[str, Any]:
            try:
                import pandas as pd

                frame = pd.read_csv(target, nrows=200_000, on_bad_lines="skip")
                description = frame.describe(include="all").to_string()[:2500]
                return {
                    "rows": int(frame.shape[0]),
                    "columns": list(map(str, frame.columns)),
                    "head": frame.head(8).to_string()[:2000],
                    "describe": description,
                    "nulls": {str(k): int(v) for k, v in frame.isna().sum().items()},
                }
            except ImportError:
                import csv as csv_module

                with target.open(newline="", encoding="utf-8", errors="replace") as handle:
                    reader = csv_module.reader(handle)
                    rows = [row for _, row in zip(range(200), reader)]
                header = rows[0] if rows else []
                preview = "\n".join(", ".join(row) for row in rows[1:9])
                return {
                    "rows": max(0, len(rows) - 1),
                    "columns": header,
                    "head": preview,
                    "describe": "(install pandas for statistics)",
                    "nulls": {},
                }
            except Exception as exc:
                return {"error": str(exc)}

        info = await run_blocking(_analyze)
        if "error" in info:
            return ModuleResult.fail(f"Could not read the CSV: {info['error']}")

        body = (
            f"{target.name}: {info['rows']} rows × {len(info['columns'])} columns\n"
            f"Columns: {', '.join(info['columns'][:30])}\n\nPreview:\n{info['head']}\n\n"
            f"Statistics:\n{info['describe']}"
        )

        if question and self.llm is not None and getattr(self.llm, "available", False):
            answer = await self.llm.complete(
                f"CSV summary:\n{body}\n\nQuestion: {question}\n"
                "Answer from the data only; say so if the answer isn't derivable.",
                temperature=0.2,
                max_tokens=450,
            )
            if answer.strip():
                return ModuleResult(success=True, output=answer.strip(), data=info)

        return ModuleResult(
            success=True,
            output=body,
            speak=f"{target.name} has {info['rows']} rows and "
            f"{len(info['columns'])} columns.",
            data=info,
        )

    @tool(
        description="Read a plain text file.",
        params={
            "path": {"type": "string", "description": "File path", "required": True},
            "max_chars": {"type": "integer", "description": "Character cap", "default": 4000},
        },
        untrusted=True,
        keywords=["read the file", "show me the contents", "open the text file", "cat"],
    )
    async def read_file(self, path: str, max_chars: int = 4000) -> ModuleResult:
        """Return the contents of a text file."""
        target = resolve_user_path(path)
        if not target.exists() or not target.is_file():
            return ModuleResult.fail(f"No file at {target}.")
        refusal = await self.guard_path(target, write=False, what="read")
        if refusal is not None:
            return refusal
        if looks_binary(target):
            return ModuleResult.fail(
                f"{target.name} is a binary file ({human_bytes(target.stat().st_size)}), "
                "sir — reading it out would be gibberish. Ask me to summarise it "
                "instead if it's a document."
            )
        content = read_text_file(target, 300_000)
        self.last_document = content
        return ModuleResult(
            success=True,
            output=f"{target} ({human_bytes(target.stat().st_size)}):\n"
            f"{truncate(content, int(max_chars))}",
            data={"path": str(target), "chars": len(content)},
        )

    @tool(
        description="Create a folder.",
        params={"path": {"type": "string", "description": "Folder path", "required": True}},
        keywords=["make a folder", "create directory", "new folder", "mkdir"],
    )
    async def make_folder(self, path: str) -> ModuleResult:
        """Create a directory (with parents)."""
        target = resolve_user_path(path)
        refusal = await self.guard_path(target, write=True, what="create the folder")
        if refusal is not None:
            return refusal
        try:
            ensure_dir(target)
            return ModuleResult.ok(f"Created {target}.")
        except Exception as exc:
            return ModuleResult.fail(f"Could not create {target}: {exc}")

    @tool(
        description="Move or rename a file.",
        params={
            "source": {"type": "string", "description": "Existing path", "required": True},
            "destination": {"type": "string", "description": "New path", "required": True},
        },
        dangerous=True,
        keywords=["move the file", "rename the file", "put this file in"],
    )
    async def move_file(self, source: str, destination: str) -> ModuleResult:
        """Move or rename a file, refusing to overwrite silently."""
        origin = resolve_user_path(source)
        target = resolve_user_path(destination)
        if not origin.exists():
            return ModuleResult.fail(f"{origin} doesn't exist.")
        for candidate in (origin, target):
            refusal = await self.guard_path(candidate, write=True, what="move")
            if refusal is not None:
                return refusal
        try:
            if target.is_dir():
                target = target / origin.name
            if target.exists():
                return ModuleResult.fail(f"{target} already exists — pick another name.")
            ensure_dir(target.parent)
            shutil.move(str(origin), str(target))
            entry_id = await run_blocking(
                self._record_moves, "move", f"moved {origin.name} to {target}",
                [(str(origin), str(target))],
            )
            return ModuleResult.ok(f"Moved to {target}.", operation=entry_id)
        except Exception as exc:
            return ModuleResult.fail(f"Move failed: {exc}")

    @tool(
        description=(
            "Undo the last file move or folder organisation JARVIS performed, putting "
            "every file back where it came from."
        ),
        params={
            "operation": {"type": "integer", "default": 0,
                          "description": "Operation number (0 = the most recent)"},
        },
        keywords=["undo that", "undo the move", "put them back", "revert the files",
                  "undo the organisation", "move them back", "unorganise"],
        examples=["undo_file_operation()"],
    )
    async def undo_file_operation(self, operation: int = 0) -> ModuleResult:
        """Reverse a recorded batch of file moves.

        Args:
            operation: Which journal entry to undo, ``0`` for the latest.

        Returns:
            How many files went back, and why any could not.
        """
        def _load() -> Optional[Dict[str, Any]]:
            with self._journal() as connection:
                if operation:
                    row = connection.execute(
                        "SELECT * FROM file_operations WHERE id = ?", (int(operation),)
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT * FROM file_operations WHERE undone = 0 "
                        "ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                return dict(row) if row else None

        entry = await run_blocking(_load)
        if entry is None:
            return ModuleResult.fail(
                "I have no file operations to undo, sir — nothing has been moved."
            )
        if entry.get("undone"):
            return ModuleResult.fail(
                f"Operation #{entry['id']} ({entry['description']}) was already undone, sir."
            )
        try:
            moves = [(str(pair[0]), str(pair[1])) for pair in json.loads(entry["moves"])]
        except Exception:
            return ModuleResult.fail(f"Operation #{entry['id']} is unreadable, sir.")

        for source, destination in moves:
            for candidate in (Path(source), Path(destination)):
                refusal = await self.guard_path(candidate, write=True, what="restore")
                if refusal is not None:
                    return refusal

        def _restore() -> Dict[str, Any]:
            restored, missing, blocked = 0, 0, []
            emptied: List[Path] = []
            for source, destination in reversed(moves):
                origin, target = Path(destination), Path(source)
                if not origin.exists():
                    missing += 1
                    continue
                if target.exists():
                    blocked.append(target.name)
                    continue
                try:
                    ensure_dir(target.parent)
                    shutil.move(str(origin), str(target))
                    restored += 1
                    emptied.append(origin.parent)
                except Exception as exc:
                    self.log.debug("Could not restore %s: %s", origin, exc)
                    blocked.append(origin.name)
            # Clean up category folders that organise created and undo emptied.
            for folder in {str(path) for path in emptied}:
                candidate = Path(folder)
                try:
                    if candidate.is_dir() and not any(candidate.iterdir()):
                        candidate.rmdir()
                except Exception:
                    pass
            return {"restored": restored, "missing": missing, "blocked": blocked}

        outcome = await run_blocking(_restore)

        def _mark() -> None:
            with self._journal() as connection:
                connection.execute(
                    "UPDATE file_operations SET undone = 1 WHERE id = ?", (entry["id"],)
                )

        await run_blocking(_mark)

        lines = [f"Undid operation #{entry['id']} ({entry['description']}): "
                 f"{outcome['restored']} file(s) put back."]
        if outcome["missing"]:
            lines.append(f"{outcome['missing']} had already been moved or deleted elsewhere.")
        if outcome["blocked"]:
            lines.append(
                "Could not restore: " + truncate(", ".join(outcome["blocked"]), 160)
            )
        return ModuleResult(
            success=True,
            output="\n".join(lines),
            speak=f"Put {outcome['restored']} files back, sir.",
            data={"operation": entry["id"], **outcome},
        )

    @tool(
        description="List the recent file moves JARVIS made, and whether they were undone.",
        params={"limit": {"type": "integer", "default": 10,
                          "description": "How many entries to show"}},
        keywords=["what files did you move", "recent file operations", "file history",
                  "what did you move", "list file operations"],
    )
    async def recent_operations(self, limit: int = 10) -> ModuleResult:
        """Show the move journal.

        Args:
            limit: Maximum number of entries.

        Returns:
            One line per recorded operation, newest first.
        """
        def _read() -> List[Dict[str, Any]]:
            with self._journal() as connection:
                return [dict(row) for row in connection.execute(
                    "SELECT * FROM file_operations ORDER BY id DESC LIMIT ?",
                    (max(1, min(int(limit or 10), 50)),),
                ).fetchall()]

        rows = await run_blocking(_read)
        if not rows:
            return ModuleResult.ok("I have not moved any files, sir.", operations=[])
        lines = [f"{len(rows)} recent file operation(s):"]
        for row in rows:
            try:
                count = len(json.loads(row["moves"]))
            except Exception:
                count = 0
            try:
                when = friendly_when(datetime.fromisoformat(row["created"]))
            except Exception:
                when = row["created"]
            state = " [undone]" if row["undone"] else ""
            lines.append(f"  #{row['id']:<3} {row['description'][:52]:54} "
                         f"{count} file(s), {when}{state}")
        lines.append("Say 'undo that' to reverse the most recent one.")
        return ModuleResult.ok("\n".join(lines), operations=rows)

    @tool(
        description="Report how big a folder is and what it contains.",
        params={"path": {"type": "string", "description": "Folder", "default": "~"}},
        keywords=["how big is", "folder size", "what's in the folder", "count files"],
    )
    async def folder_stats(self, path: str = "~") -> ModuleResult:
        """Summarise a folder: file count, total size and type breakdown."""
        root = resolve_user_path(path)
        if not root.exists() or not root.is_dir():
            return ModuleResult.fail(f"{root} is not a folder.")

        def _scan() -> Dict[str, Any]:
            total_size, total_files = 0, 0
            by_type: Dict[str, Dict[str, int]] = defaultdict(lambda: {"count": 0, "size": 0})
            for file_path in self._iter_files(root, True, self.max_scan_files):
                try:
                    size = file_path.stat().st_size
                except Exception:
                    continue
                total_files += 1
                total_size += size
                extension = file_path.suffix.lower() or "(no extension)"
                by_type[extension]["count"] += 1
                by_type[extension]["size"] += size
            top = sorted(by_type.items(), key=lambda item: item[1]["size"], reverse=True)[:8]
            return {"files": total_files, "size": total_size, "top": top}

        info = await run_blocking(_scan)
        lines = [
            f"{root}: {info['files']} files, {human_bytes(info['size'])} total",
            "By type:",
        ]
        lines += [
            f"  {extension}: {stats['count']} files, {human_bytes(stats['size'])}"
            for extension, stats in info["top"]
        ]
        return ModuleResult(
            success=True,
            output="\n".join(lines),
            speak=f"{root.name or root} holds {info['files']} files, "
            f"{human_bytes(info['size'])} in total.",
            data={"files": info["files"], "size": info["size"]},
        )


__all__ = ["FileManager"]

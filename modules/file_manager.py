# /modules/file_manager.py
"""Smart file operations: search, organise, summarise documents and analyse CSVs."""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.documents import extract_text
from utils.helpers import (
    ensure_dir,
    human_bytes,
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
    intent_examples = [
        "find all PDFs on my desktop",
        "organize my downloads folder",
        "summarize this document",
        "what's taking up space in my home folder",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Cache config values used across tools."""
        super().__init__(config, llm=llm, security=security)
        self.max_scan_files = 40_000
        self.last_document: str = ""

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

        if any(phrase in lowered for phrase in ("organize", "organise", "tidy", "clean up")):
            return "organize_files", {
                "path": location,
                "dry_run": not any(w in lowered for w in ("for real", "actually", "do it",
                                                          "confirm", "no preview")),
            }

        if any(phrase in lowered for phrase in ("summarize", "summarise", "tldr", "what's in this document")):
            path = re.search(r"([\w./~-]+\.(?:pdf|docx?|txt|md|csv|epub))", text, re.IGNORECASE)
            if path:
                return "summarize_document", {"path": path.group(1)}

        csv_path = re.search(r"([\w./~-]+\.csv)", text, re.IGNORECASE)
        if csv_path:
            return "analyze_csv", {"path": csv_path.group(1)}

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

        known_extensions = {
            "pdf", "png", "jpg", "jpeg", "gif", "mp3", "mp4", "csv", "txt", "md", "doc",
            "docx", "xls", "xlsx", "ppt", "pptx", "zip", "py", "js", "ts", "json", "log",
        }
        if any(word in lowered for word in ("find", "search", "list", "show", "locate", "where")):
            candidate = ""
            for token in re.findall(r"[a-z0-9]+", lowered):
                if token in known_extensions:
                    candidate = token
                    break
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

        def _scan() -> List[Dict[str, Any]]:
            matches: List[Dict[str, Any]] = []
            for file_path in self._iter_files(root, recursive, self.max_scan_files):
                if not fnmatch.fnmatch(file_path.name.lower(), glob_pattern.lower()):
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

        if self.security is not None:
            assessment = self.security.is_path_allowed(root, write=True)
            if assessment.blocked:
                return ModuleResult.fail(f"Refused: {assessment.reason}")

        extension_map: Dict[str, str] = {
            extension: category
            for category, extensions in CATEGORIES.items()
            for extension in extensions
        }

        def _organize() -> Dict[str, Any]:
            plan: Dict[str, List[str]] = defaultdict(list)
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
                    moved += 1
                except Exception:
                    failed += 1
            return {"plan": {key: value for key, value in plan.items()},
                    "moved": moved, "failed": failed}

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
        return ModuleResult(
            success=True,
            output=f"Organised {root}: moved {result['moved']} file(s), "
            f"{result['failed']} failure(s).\n{summary}",
            speak=f"Moved {result['moved']} files into {len(plan)} folders.",
            data=result,
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
    async def summarize_document(self, path: str, question: str = "") -> ModuleResult:
        """Extract a document's text and summarise it with the local LLM."""
        target = resolve_user_path(path)
        if not target.exists() or not target.is_file():
            return ModuleResult.fail(f"No file at {target}.")

        text = await run_blocking(self._extract_document, target)
        if not text.strip():
            return ModuleResult.fail(
                f"I couldn't extract any text from {target.name} "
                "(it may be a scanned image or an unsupported format)."
            )
        self.last_document = text

        if self.llm is None or not getattr(self.llm, "available", False):
            return ModuleResult(
                success=True,
                output=f"{target.name} — {len(text.split())} words. First part:\n"
                f"{truncate(text, 1500)}",
                data={"path": str(target), "words": len(text.split())},
            )

        instruction = (
            f"Answer this question using only the document: {question}"
            if question
            else "Summarise the document in 5 sentences, then list up to 5 key points."
        )
        summary = await self.llm.complete(
            f"DOCUMENT: {target.name}\n\n{truncate(text, 12000)}\n\n{instruction}",
            temperature=0.3,
            max_tokens=650,
        )
        return ModuleResult(
            success=True,
            output=summary.strip() or truncate(text, 1500),
            data={"path": str(target), "words": len(text.split())},
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
        if self.security is not None:
            assessment = self.security.is_path_allowed(target, write=True)
            if assessment.blocked:
                return ModuleResult.fail(f"Refused: {assessment.reason}")
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
        if self.security is not None:
            for candidate in (origin, target):
                assessment = self.security.is_path_allowed(candidate, write=True)
                if assessment.blocked:
                    return ModuleResult.fail(f"Refused: {assessment.reason}")
        try:
            if target.is_dir():
                target = target / origin.name
            if target.exists():
                return ModuleResult.fail(f"{target} already exists — pick another name.")
            ensure_dir(target.parent)
            shutil.move(str(origin), str(target))
            return ModuleResult.ok(f"Moved to {target}.")
        except Exception as exc:
            return ModuleResult.fail(f"Move failed: {exc}")

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

# /core/projects.py
"""Project contexts — tag your data by what you are working on.

``focus on the bike project`` activates a context; while one is active every
new todo, note, reminder and stored fact is tagged with the project name, so
``what's open in the bike project?`` later shows only that project's items.
All state lives in ``data/projects.json`` beside the journal and the tags
live in the shared SQLite database — no model, no network, survives restarts.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.projects")

#: Tables that carry project tags; ``field`` is where the project name is
#: appended (comma-separated tags, or the fact category).
_TABLES = (
    {"table": "todos", "field": "tags"},
    {"table": "notes", "field": "tags"},
    {"table": "reminders", "field": "tags"},
    {"table": "facts", "field": "category"},
)


def _path(config: Any) -> Path:
    try:
        journal = config.resolve(
            config.get("assistant.journal_file", "data/journal.json")
        )
        return journal.parent / "projects.json"
    except Exception:
        return Path("data/projects.json")


def _load(config: Any) -> Dict[str, Any]:
    path = _path(config)
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("active", "")
                raw.setdefault("projects", {})
                return raw
    except Exception as exc:  # pragma: no cover - best-effort store
        logger.debug("Projects state unreadable: %s", exc)
    return {"active": "", "projects": {}}


def _save(config: Any, state: Dict[str, Any]) -> None:
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def _slug(name: str) -> str:
    """A safe, searchable tag for a project name."""
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "project"


def _max_rowids(config: Any) -> Dict[str, int]:
    """Current high-water rowid per tagged table (activation snapshot)."""
    marks: Dict[str, int] = {}
    connection = _connect(config)
    try:
        with connection:
            for spec in _TABLES:
                row = connection.execute(
                    f"SELECT COALESCE(MAX(rowid), 0) AS top "
                    f"FROM {spec['table']}"
                ).fetchone()
                marks[spec["table"]] = int(row["top"])
    finally:
        connection.close()
    return marks


def activate(config: Any, name: str) -> str:
    """Start working inside a project context.

    Only rows created from now on are tagged — older data is not retro-fitted
    (the watermark snapshots the current state of every table).

    Args:
        config: Configuration (locates state and the database).
        name: The project's name.

    Returns:
        The active (slugged) project name.
    """
    state = _load(config)
    slug = _slug(name)
    projects = state.setdefault("projects", {})
    if slug not in projects:
        projects[slug] = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "display": (name or "").strip()[:60] or slug,
        }
    # Snapshot now so a re-focus never retro-tags the rows created in
    # between; anything above this mark belongs to this focus period.
    projects[slug]["last_ids"] = _max_rowids(config)
    state["active"] = slug
    _save(config, state)
    return slug


def deactivate(config: Any) -> None:
    """Leave the current project context."""
    state = _load(config)
    state["active"] = ""
    _save(config, state)


def active(config: Any) -> str:
    """The project context currently in force (empty when none)."""
    return str(_load(config).get("active", "") or "")


def list_projects(config: Any) -> List[Dict[str, str]]:
    """Every known project with its display name and creation date."""
    state = _load(config)
    projects = state.get("projects", {})
    return [{
        "name": str(name),
        "display": str(entry.get("display", "") or name),
        "created": str(entry.get("created", "")),
    } for name, entry in sorted(projects.items())]


def display_name(config: Any, name: str) -> str:
    """The human name stored for a project slug, or the slug itself."""
    entry = _load(config).get("projects", {}).get(str(name), {})
    return str(entry.get("display", "") or name)


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL,
            priority TEXT DEFAULT 'normal', due TEXT,
            tags TEXT DEFAULT '', done INTEGER DEFAULT 0,
            created TEXT, completed TEXT);
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT,
            tags TEXT DEFAULT '', created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
            due TEXT NOT NULL, fired INTEGER DEFAULT 0, created TEXT);
        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY, timestamp TEXT, category TEXT,
            content TEXT, importance REAL DEFAULT 0.5, source TEXT);
        """
    )
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(reminders)")
    }
    if "tags" not in columns:  # older databases predate the column
        connection.execute(
            "ALTER TABLE reminders ADD COLUMN tags TEXT DEFAULT ''"
        )


def _connect(config: Any) -> sqlite3.Connection:
    db = config.resolve(config.get("database.path", "data/jarvis.db"))
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db), timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        _ensure_schema(connection)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Schema ensure failed: %s", exc)
    return connection


def _append_tag(existing: Optional[str], slug: str) -> str:
    parts = [part.strip() for part in str(existing or "").split(",") if part.strip()]
    if slug not in parts:
        parts.append(slug)
    return ", ".join(parts)


def tag_new_rows(config: Any, project: str = "") -> int:
    """Tag rows created since the last pass with a project context.

    Args:
        config: Configuration (state file + database).
        project: Project to tag with; empty means the active context.

    Returns:
        How many rows were newly tagged (0 when no context is active).
    """
    slug = project or active(config)
    if not slug:
        return 0
    state = _load(config)
    projects = state.setdefault("projects", {})
    entry = projects.setdefault(slug, {
        "created": datetime.now().isoformat(timespec="seconds"),
        "display": slug,
    })
    marks = entry.setdefault("last_ids", {})
    tagged = 0
    connection = _connect(config)
    try:
        with connection:
            for spec in _TABLES:
                table = spec["table"]
                field = spec["field"]
                low = marks.get(table, 0)
                rows = connection.execute(
                    f"SELECT *, rowid AS __rid FROM {table} "
                    f"WHERE rowid > ? ORDER BY rowid", (low,),
                ).fetchall()
                for row in rows:
                    if slug in str(row[field] or "").split(","):
                        continue
                    current = str(row[field] or "")
                    connection.execute(
                        f"UPDATE {table} SET {field} = ? WHERE rowid = ?",
                        (_append_tag(current, slug), int(row["__rid"])),
                    )
                    tagged += 1
                marks[table] = int(rows[-1]["__rid"]) if rows else low
    finally:
        connection.close()
    _save(config, state)
    return tagged


def project_overview(
    config: Any, name: str, limit: int = 8
) -> Dict[str, List[Dict[str, str]]]:
    """Open items of one project, grouped by store.

    Args:
        config: Configuration.
        name: Project name or slug.
        limit: How many items per group at most.

    Returns:
        ``{"todos": [...], "reminders": [...], "notes": [...],
        "facts": [...], "counts": {...}}`` with newest first.
    """
    slug = _slug(name)
    needle = f"%{slug}%"
    overview: Dict[str, List[Dict[str, str]]] = {
        "todos": [], "reminders": [], "notes": [], "facts": [],
    }
    counts = {"todos": 0, "reminders": 0, "notes": 0, "facts": 0}
    connection = _connect(config)
    try:
        with connection:
            rows = connection.execute(
                "SELECT task, due, tags FROM todos WHERE done = 0 "
                "AND tags LIKE ? ORDER BY id DESC LIMIT ?", (needle, limit),
            ).fetchall()
            for row in rows:
                counts["todos"] += 1
                overview["todos"].append({"text": str(row["task"]),
                                          "when": str(row["due"] or "")})
            rows = connection.execute(
                "SELECT text, due, tags FROM reminders WHERE fired = 0 "
                "AND tags LIKE ? ORDER BY id DESC LIMIT ?", (needle, limit),
            ).fetchall()
            for row in rows:
                counts["reminders"] += 1
                overview["reminders"].append({"text": str(row["text"]),
                                              "when": str(row["due"] or "")})
            rows = connection.execute(
                "SELECT title, updated, tags FROM notes "
                "WHERE tags LIKE ? ORDER BY id DESC LIMIT ?", (needle, limit),
            ).fetchall()
            for row in rows:
                counts["notes"] += 1
                overview["notes"].append({"text": str(row["title"] or "")[:90],
                                          "when": str(row["updated"] or "")})
            rows = connection.execute(
                "SELECT content, timestamp, category FROM facts "
                "WHERE category LIKE ? ORDER BY rowid DESC LIMIT ?",
                (needle, limit),
            ).fetchall()
            for row in rows:
                counts["facts"] += 1
                overview["facts"].append({"text": str(row["content"] or "")[:90],
                                          "when": str(row["timestamp"] or "")})
    finally:
        connection.close()
    overview["counts"] = counts
    return overview


__all__ = [
    "activate", "active", "deactivate", "display_name", "list_projects",
    "project_overview", "tag_new_rows",
]

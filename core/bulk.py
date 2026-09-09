# /core/bulk.py
"""Bulk & batch actions across the productivity stores.

One sentence moves many rows: "tick off everything in the bike project",
"snooze all reminders due today until tomorrow", "delete every note tagged
holiday". Every operation is a local SQL transaction on the shared database
and nothing needs a model. Actions are two-phase so JARVIS can show a short
preview and ask before touching more than a few rows.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.bulk")

#: Below this many affected rows the action applies instantly; above it the
#: caller should ask for confirmation first.
PREVIEW_LIMIT = 5


def _connect(config: Any) -> sqlite3.Connection:
    db = config.resolve(config.get("database.path", "data/jarvis.db"))
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db), timeout=15)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL,
            priority TEXT DEFAULT 'normal', due TEXT,
            tags TEXT DEFAULT '', done INTEGER DEFAULT 0,
            created TEXT, completed TEXT);
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
            due TEXT NOT NULL, fired INTEGER DEFAULT 0,
            created TEXT, repeat TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT,
            tags TEXT DEFAULT '', created TEXT, updated TEXT);
        """
    )
    for table in ("todos", "notes", "reminders"):
        columns = {
            row[1] for row in connection.execute(f"PRAGMA table_info({table})")
        }
        if "tags" not in columns:
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN tags TEXT DEFAULT ''"
            )
    return connection


def _tag_like(project: str) -> str:
    return f"%{project}%"


def _ensure_schema(config: Any) -> None:
    """Make sure the tables and their tags column exist before any query."""
    try:
        connection = _connect(config)
        connection.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Bulk schema ensure failed: %s", exc)


def complete_todos(
    config: Any, *, project: str = "", everything: bool = False,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """Mark open todos done (optionally only those tagged with a project).

    Args:
        config: Configuration (locates the database).
        project: Only todos carrying this project tag.
        everything: Act on every open todo when no project is given.
        dry_run: Return a preview without changing anything.

    Returns:
        ``{"count": n, "rows": [task text...]}``.
    """
    _ensure_schema(config)
    where = "WHERE done = 0"
    params: List[Any] = []
    if project:
        where += " AND tags LIKE ?"
        params.append(_tag_like(project))
    elif not everything:
        return {"count": 0, "rows": []}
    stamp = datetime.now().isoformat(timespec="seconds")
    return _act(
        config, table="todos", action="complete", where=where, params=params,
        stamp=stamp, dry_run=dry_run,
    )


def delete_rows(
    config: Any, *, table: str, project: str = "", everything: bool = False,
    done_only: bool = False, dry_run: bool = True,
) -> Dict[str, Any]:
    """Delete todos/reminders/notes, filtered by project tag or everything.

    Args:
        config: Configuration (locates the database).
        table: ``"todos"``, ``"reminders"`` or ``"notes"``.
        project: Only rows carrying this project tag.
        everything: Act on every row when no project is given.
        done_only: For todos, only delete completed ones.
        dry_run: Return a preview without changing anything.

    Returns:
        ``{"count": n, "rows": [...]}``.
    """
    _ensure_schema(config)
    where = ""
    params: List[Any] = []
    if project:
        where = "WHERE tags LIKE ?"
        params.append(_tag_like(project))
    elif not everything:
        return {"count": 0, "rows": []}
    if table == "todos" and done_only:
        where = f"{where} AND done = 1" if where else "WHERE done = 1"
    return _act(
        config, table=table, action="delete", where=where, params=params,
        stamp="", dry_run=dry_run,
    )


def snooze_reminders(
    config: Any, *, project: str = "", everything: bool = False,
    until: Optional[str] = None, dry_run: bool = True,
) -> Dict[str, Any]:
    """Push unfired reminders to a later due time (default tomorrow 09:00).

    Args:
        config: Configuration (locates the database).
        project: Only reminders carrying this project tag.
        everything: Act on every unfired reminder when no project is given.
        until: ISO timestamp to postpone to.
        dry_run: Return a preview without changing anything.

    Returns:
        ``{"count": n, "rows": [...]}``.
    """
    _ensure_schema(config)
    where = "WHERE fired = 0"
    params: List[Any] = []
    if project:
        where += " AND tags LIKE ?"
        params.append(_tag_like(project))
    elif not everything:
        return {"count": 0, "rows": []}
    target = until or (datetime.now() + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    ).isoformat(timespec="seconds")
    return _act(
        config, table="reminders", action="snooze", where=where, params=params,
        stamp=target, dry_run=dry_run,
    )


def _act(
    config: Any, *, table: str, action: str, where: str, params: List[Any],
    stamp: str, dry_run: bool,
) -> Dict[str, Any]:
    """Shared worker: preview or apply one bulk action."""
    text_column = {"todos": "task", "reminders": "text", "notes": "title"}[table]
    try:
        connection = _connect(config)
        try:
            rows = connection.execute(
                f"SELECT id, {text_column} AS text FROM {table} {where} "
                f"ORDER BY id", params,
            ).fetchall()
            preview = [str(row["text"])[:90] for row in rows[:PREVIEW_LIMIT]]
            count = len(rows)
            if not dry_run and count:
                stamp_value = stamp or None
                if action == "complete":
                    connection.execute(
                        f"UPDATE {table} SET done = 1, completed = ? WHERE "
                        f"{_primary(connection, table)} IN "
                        f"({','.join('?' for _ in rows)})",
                        [stamp_value, *[row["id"] for row in rows]],
                    )
                elif action == "snooze":
                    connection.execute(
                        f"UPDATE {table} SET due = ? WHERE "
                        f"{_primary(connection, table)} IN "
                        f"({','.join('?' for _ in rows)})",
                        [stamp_value, *[row["id"] for row in rows]],
                    )
                elif action == "delete":
                    connection.execute(
                        f"DELETE FROM {table} WHERE "
                        f"{_primary(connection, table)} IN "
                        f"({','.join('?' for _ in rows)})",
                        [row["id"] for row in rows],
                    )
            connection.commit()
            return {"count": count, "rows": preview}
        finally:
            connection.close()
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Bulk %s %s failed: %s", action, table, exc)
        return {"count": 0, "rows": []}


def _primary(connection: sqlite3.Connection, table: str) -> str:
    """The rowid-based primary key of a table (works for all three)."""
    info = connection.execute(f"PRAGMA table_info({table})").fetchall()
    for column in info:
        if column["pk"]:
            return column["name"]
    return "id"


__all__ = ["complete_todos", "delete_rows", "snooze_reminders"]

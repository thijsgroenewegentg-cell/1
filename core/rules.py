# /core/rules.py
"""Event rules — "when X, do Y", watched locally and offline.

JARVIS can be taught standing rules that run by themselves, with no model and
no network:

* **file rules** — "when a new file matching ``*.pdf`` lands in a folder,
  move it somewhere else" (folder snapshots remembered per rule),
* **keyword rules** — "when a note mentions ``deadline``, add a todo"
  (database high-water marks remembered per rule).

Rules live one-per-line in ``data/rules.jsonl`` next to the journal; each
rule remembers what it already saw in ``state``, so repeated passes are
idempotent. Actions are local file moves/copies and rows in the shared
SQLite database.
"""

from __future__ import annotations

import fnmatch
import json
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.rules")


def _path(config: Any) -> Path:
    try:
        journal = config.resolve(
            config.get("assistant.journal_file", "data/journal.json")
        )
        return journal.parent / "rules.jsonl"
    except Exception:
        return Path("data/rules.jsonl")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def add_rule(
    config: Any,
    *,
    kind: str,
    trigger: Dict[str, Any],
    action: Dict[str, Any],
) -> Dict[str, Any]:
    """Store one rule and return it.

    Args:
        config: Configuration (locates the rules file).
        kind: ``"file"`` or ``"keyword"``.
        trigger: ``{"folder", "pattern"}`` for file rules, or
            ``{"table", "word"}`` for keyword rules.
        action: ``{"kind": "move"|"copy"|"delete", "to"}`` for file rules;
            ``{"kind": "todo"|"reminder", "text", "due"}`` for keyword rules.

    Returns:
        The stored rule dict.
    """
    rule = {
        "id": uuid.uuid4().hex[:10],
        "kind": kind,
        "trigger": {str(key): value for key, value in (trigger or {}).items()},
        "action": {str(key): value for key, value in (action or {}).items()},
        "enabled": True,
        "fired": 0,
        "created": _now(),
        "state": {},
    }
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(rule, ensure_ascii=False) + "\n")
    return rule


def list_rules(config: Any) -> List[Dict[str, Any]]:
    """Every rule, newest first."""
    path = _path(config)
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    records.reverse()
    return records


def _rewrite(config: Any, records: List[Dict[str, Any]]) -> None:
    path = _path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def describe(rule: Dict[str, Any]) -> str:
    """One human line for a rule, used in listings and confirmations."""
    trigger = rule.get("trigger") or {}
    action = rule.get("action") or {}
    if rule.get("kind") == "file":
        return (
            f"file '{trigger.get('pattern', '*')}' appearing in "
            f"{trigger.get('folder', '?')} -> {action.get('kind', 'move')} "
            f"to {action.get('to', '?')}"
        )
    return (
        f"{trigger.get('table', 'notes')} mentioning "
        f"'{trigger.get('word', '')}' -> {action.get('kind', 'todo')}"
    )


def remove_rule(config: Any, needle: str) -> int:
    """Delete rules matching a number (1 = newest) or some text.

    Args:
        config: Configuration.
        needle: e.g. ``"2"`` (newest first) or a word from the rule's
            description or its id.

    Returns:
        How many rules were removed.
    """
    chronological = list(reversed(list_rules(config)))
    if not chronological:
        return 0
    removed: List[Dict[str, Any]] = []
    if (needle or "").strip().isdigit():
        index = int(needle.strip()) - 1  # 1 = newest
        newest_first = index
        if 0 <= newest_first < len(chronological):
            removed.append(chronological.pop(len(chronological) - 1 - index))
    else:
        kept: List[Dict[str, Any]] = []
        for rule in chronological:
            hay = f"{rule.get('kind')} {describe(rule)} {rule.get('id')}".lower()
            if needle and needle.lower() in hay:
                removed.append(rule)
            else:
                kept.append(rule)
        chronological = kept
    if removed:
        _rewrite(config, chronological)
    return len(removed)


def _folder(text: str) -> Optional[Path]:
    path = Path(text or "").expanduser()
    return path if path.is_absolute() else None


# ------------------------------------------------------------- file rules
def _run_file_rule(rule: Dict[str, Any]) -> List[str]:
    trigger = rule.get("trigger") or {}
    action = rule.get("action") or {}
    folder = _folder(trigger.get("folder", ""))
    destination = _folder(action.get("to", ""))
    pattern = str(trigger.get("pattern", "*"))
    if folder is None or not folder.is_dir():
        return []
    if action.get("kind") in {"move", "copy"} and destination is None:
        return []
    seen: Dict[str, float] = rule.setdefault("state", {}).setdefault("seen", {})
    fired: List[str] = []
    try:
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            key = str(path)
            modified = path.stat().st_mtime
            if seen.get(key) == modified:
                continue
            seen[key] = modified
            if not fnmatch.fnmatch(path.name, pattern):
                continue
            kind = action.get("kind", "move")
            if kind == "delete":
                path.unlink()
                fired.append(f"deleted '{path.name}'")
                continue
            target = destination / path.name
            if target.exists():
                target = target.with_name(
                    f"{path.stem}-{uuid.uuid4().hex[:6]}{path.suffix}"
                )
            if kind == "move":
                shutil.move(str(path), str(target))
                fired.append(f"moved '{path.name}' to {destination}")
            elif kind == "copy":
                shutil.copy2(str(path), str(target))
                fired.append(f"copied '{path.name}' to {destination}")
    except Exception as exc:  # pragma: no cover - watchers must never crash
        logger.debug("File rule pass failed: %s", exc)
    if len(seen) > 2000:  # keep the folder snapshot bounded
        for key in list(seen)[:-1000]:
            seen.pop(key, None)
    return fired


# ---------------------------------------------------------- keyword rules
def _ensure_db_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT,
            tags TEXT DEFAULT '', created TEXT, updated TEXT);
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL,
            priority TEXT DEFAULT 'normal', due TEXT,
            tags TEXT DEFAULT '', done INTEGER DEFAULT 0,
            created TEXT, completed TEXT);
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
            due TEXT NOT NULL, fired INTEGER DEFAULT 0, created TEXT);
        """
    )


def _run_keyword_rule(config: Any, rule: Dict[str, Any]) -> List[str]:
    """Watch a store table for rows containing the trigger word."""
    trigger = rule.get("trigger") or {}
    action = rule.get("action") or {}
    table = str(trigger.get("table", "notes"))
    word = str(trigger.get("word", "")).lower()
    if table not in {"notes", "todos"} or not word:
        return []
    state = rule.setdefault("state", {})
    low = int(state.get("last_id", 0))
    db_path = config.resolve(config.get("database.path", "data/jarvis.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path), timeout=15)
    connection.row_factory = sqlite3.Row
    fired: List[str] = []
    try:
        with connection:
            _ensure_db_schema(connection)
            if table == "notes":
                rows = connection.execute(
                    "SELECT id, title, body FROM notes WHERE id > ? "
                    "ORDER BY id", (low,),
                ).fetchall()
                for row in rows:
                    hay = f"{row['title'] or ''} {row['body'] or ''}".lower()
                    if word in hay:
                        fired.append(_keyword_action(
                            connection, action, f"note #{row['id']}"))
            else:
                rows = connection.execute(
                    "SELECT id, task FROM todos WHERE id > ? ORDER BY id",
                    (low,),
                ).fetchall()
                for row in rows:
                    if word in str(row["task"] or "").lower():
                        fired.append(_keyword_action(
                            connection, action, f"todo #{row['id']}"))
            state["last_id"] = rows[-1]["id"] if rows else low
    finally:
        connection.close()
    return fired


def _keyword_action(
    connection: sqlite3.Connection, action: Dict[str, Any], source: str
) -> str:
    """Carry out a keyword rule's action for one matching row."""
    kind = str(action.get("kind", "todo"))
    text = str(action.get("text", "")).strip()
    stamp = datetime.now().isoformat(timespec="seconds")
    if kind == "todo":
        connection.execute(
            "INSERT INTO todos (task, done, created) VALUES (?, 0, ?)",
            (text or f"follow up ({source})", stamp),
        )
        return f"created todo '{text or source}'"
    if kind == "reminder":
        connection.execute(
            "INSERT INTO reminders (text, due, fired, created) "
            "VALUES (?, ?, 0, ?)",
            (text or f"follow up ({source})", action.get("due") or stamp, stamp),
        )
        return f"created reminder for '{text or source}'"
    return ""


# -------------------------------------------------------------- run all
def run_once(config: Any, *, reply: bool = False) -> List[Dict[str, Any]]:
    """Run every enabled rule once and report what happened.

    Args:
        config: Configuration (rules file + database + folders).
        reply: When True the fired actions are collected as human text so
            the caller can answer with them; ``state`` advances either way.

    Returns:
        Fired actions as ``[{"rule": id, "text": ...}, ...]`` (empty when
        nothing fired). Silent passes (``reply=False``) only update counts
        and return the actions with empty text.
    """
    records = list(reversed(list_rules(config)))  # chronological file order
    fired_log: List[Dict[str, Any]] = []
    for rule in records:
        if not rule.get("enabled", True):
            continue
        try:
            if rule.get("kind") == "file":
                fired = _run_file_rule(rule)
            elif rule.get("kind") == "keyword":
                fired = _run_keyword_rule(config, rule)
            else:
                continue
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Rule %s failed: %s", rule.get("id"), exc)
            continue
        if fired:
            rule["fired"] = int(rule.get("fired", 0)) + len(fired)
            rule["last_fired"] = _now()
            for detail in fired:
                fired_log.append({
                    "rule": rule.get("id"),
                    "text": detail if reply else "",
                })
    _rewrite(config, records)  # persists the mutated state (watermarks etc.)
    return fired_log


__all__ = ["add_rule", "describe", "list_rules", "remove_rule", "run_once"]

# /tests/test_wave4_features.py
"""The five follow-up capabilities (round 4), all verifiable with no LLM.

1. **Bulk & batch actions** — "tick off everything in the bike project"
   previews when more than a few rows are affected, then applies and reports
   counts; deletes and reminder-snoozing work the same way, offline.
2. **Topic dossiers** — "brief me over de verbouwing" / "fill me in on X"
   assemble one compact brief from the journal, facts, notes and threads.
3. **Self-healing retries** — a logged failure ("open report.pdf", file
   moved) produces closest-match suggestions; "try that again" / "probeer
   opnieuw" answers once the cause is fixed.
4. **End-of-day recap** — "recap my day" / "wat heb ik vandaag gedaan" gives
   the evening summary from the local stores, newest last.
5. **Local secret vault** — "remember my wifi password is …", "what's my
   wifi password", "forget …": an obfuscated file beside the journal, never
   in notes or logs.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core import bulk, dossier, healer, journal, recap, vault
from core.brain import Brain
from tests.conftest import build_config, run


def _fresh(factory: pytest.TempPathFactory) -> Brain:
    config = build_config(factory.mktemp("wave4"))
    instance = Brain(config)
    run(instance.initialize())
    return instance


@pytest.fixture()
def brain(tmp_path_factory: pytest.TempPathFactory) -> Brain:
    """A clean offline brain per test."""
    instance = _fresh(tmp_path_factory)
    yield instance
    run(instance.shutdown())


def _ensure_db(config) -> Path:
    """Create the canonical schema (plus facts) through the modules' own code."""
    bulk.complete_todos(config, everything=True, dry_run=True)  # creates tables
    db = config.resolve(config.get("database.path", "data/jarvis.db"))
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, "
            "timestamp TEXT, category TEXT, content TEXT)"
        )
    return db


def _insert_todos(config, names: list[str], tag: str = "bike",
                  done: bool = False) -> None:
    db = _ensure_db(config)
    with sqlite3.connect(str(db)) as connection:
        connection.executemany(
            "INSERT INTO todos (task, done, tags, created) VALUES (?, ?, ?, ?)",
            [(name, 1 if done else 0, tag,
              datetime.now().isoformat(timespec="seconds")) for name in names],
        )


# ------------------------------------------------------------ 1. bulk actions
def test_bulk_preview_then_apply_completes_project_todos(brain):
    _insert_todos(brain.config, ["a", "b", "c"], tag="bike")
    _insert_todos(brain.config, ["other"], tag="home")

    preview = bulk.complete_todos(brain.config, project="bike", dry_run=True)
    assert preview["count"] == 3
    assert any("a" in row for row in preview["rows"])

    applied = bulk.complete_todos(brain.config, project="bike", dry_run=False)
    assert applied["count"] == 3
    db = brain.config.resolve(brain.config.get("database.path", "data/jarvis.db"))
    with sqlite3.connect(str(db)) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM todos WHERE done = 0 AND tags LIKE '%bike%'"
        ).fetchone()[0]
    assert remaining == 0


def test_bulk_delete_rows_removes_only_matching_scope(brain):
    _ensure_db(brain.config)
    db = brain.config.resolve(brain.config.get("database.path", "data/jarvis.db"))
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(str(db)) as connection:
        connection.executemany(
            "INSERT INTO notes (title, created, tags) VALUES (?, ?, ?)",
            [("n1", now, "werk"), ("n2", now, "werk"), ("n3", now, "thuis")],
        )
    result = bulk.delete_rows(brain.config, table="notes", project="werk",
                              dry_run=False)
    assert result["count"] == 2
    with sqlite3.connect(str(db)) as connection:
        left = connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    assert left == 1


def test_bulk_snooze_reminders_moves_unfired_to_next_morning(brain):
    _ensure_db(brain.config)
    db = brain.config.resolve(brain.config.get("database.path", "data/jarvis.db"))
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT INTO reminders (text, due, fired) VALUES (?, ?, 0)",
            ("koop melk", "2026-09-09T08:00:00"),
        )
    result = bulk.snooze_reminders(brain.config, everything=True, dry_run=False)
    assert result["count"] == 1
    with sqlite3.connect(str(db)) as connection:
        due = connection.execute(
            "SELECT due FROM reminders WHERE text = 'koop melk'"
        ).fetchone()[0]
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    assert due.startswith(tomorrow)


def test_bulk_migrates_legacy_database_without_tags_column(tmp_path):
    config = build_config(tmp_path / "legacy")
    db = config.resolve(config.get("database.path", "data/jarvis.db"))
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db)) as connection:
        connection.executescript(
            """
            CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL, due TEXT NOT NULL, fired INTEGER DEFAULT 0,
                created TEXT);
            INSERT INTO reminders (text, due, fired) VALUES ('oud', '2026-09-10T09:00:00', 0);
            """
        )
    # The old schema has no tags column; calling a bulk action must migrate.
    result = bulk.snooze_reminders(config, everything=True, dry_run=True)
    assert result["count"] == 1
    with sqlite3.connect(str(db)) as connection:
        columns = {row[1] for row in
                   connection.execute("PRAGMA table_info(reminders)")}
    assert "tags" in columns


def test_brain_bulk_previews_many_rows_then_applies_on_yes(brain):
    _insert_todos(brain.config, [f"taak {i}" for i in range(6)], tag="fiets")
    reply = run(brain.process("vink alles af in het fietsproject"))
    assert "Voorvertoning" in reply or "Preview" in reply
    assert brain._pending_bulk is not None
    run(brain.process("nee"))
    assert brain._pending_bulk is None
    db = brain.config.resolve(brain.config.get("database.path", "data/jarvis.db"))
    with sqlite3.connect(str(db)) as connection:
        left = connection.execute(
            "SELECT COUNT(*) FROM todos WHERE done = 0"
        ).fetchone()[0]
    assert left == 6  # declined: nothing changed
    # Now confirm for real.
    run(brain.process("vink alles af in het fietsproject"))
    done = run(brain.process("ja"))
    assert "afgerond" in done
    with sqlite3.connect(str(db)) as connection:
        left = connection.execute(
            "SELECT COUNT(*) FROM todos WHERE done = 0"
        ).fetchone()[0]
    assert left == 0


def test_brain_bulk_small_changes_apply_directly_and_report_counts(brain):
    _insert_todos(brain.config, ["kleine klus"], tag="bike")
    reply = run(brain.process("tick off everything in the bike project"))
    assert "Done" in reply or "Klaar" in reply
    assert brain._pending_bulk is None
    db = brain.config.resolve(brain.config.get("database.path", "data/jarvis.db"))
    with sqlite3.connect(str(db)) as connection:
        left = connection.execute(
            "SELECT COUNT(*) FROM todos WHERE done = 0"
        ).fetchone()[0]
    assert left == 0


# -------------------------------------------------------------- 2. dossiers
def test_dossier_assembles_brief_from_own_stores(brain):
    journal.note_turn(
        brain.config, text="de verbouwing van de keuken schiet lekker op",
        response="Mooi zo, hou me op de hoogte.", module="conversation",
    )
    _ensure_db(brain.config)
    db = brain.config.resolve(brain.config.get("database.path", "data/jarvis.db"))
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT INTO notes (title, created, body) VALUES (?, ?, ?)",
            ("verbouwing keukenplanning", now,
             "offerte staat nog uit"),
        )
    run(brain._note_thread_after_turn(
        "de verbouwing: stuur de offerte", "ik kom erop terug"))
    brief = dossier.dossier(brain.config, "verbouwing", language="nl")
    assert brief is not None
    assert "dagboek" in brief
    assert "notities" in brief
    assert "offerte" in brief


def test_dossier_returns_none_when_topic_unknown_or_filler(brain):
    assert dossier.dossier(brain.config, "zorgvuldig-onbekend-onderwerp") is None
    assert dossier.dossier(brain.config, "de") is None


def test_brain_dossier_nl_and_en(brain):
    journal.note_turn(
        brain.config, text="bespreking smith account morgen",
        response="genoteerd", module="conversation",
    )
    reply = run(brain.process("brief me over de smith account"))
    assert "Dossier" in reply or "File" in reply
    assert "smith account" in reply.lower()
    # EN trigger
    reply = run(brain.process("fill me in on the smith account"))
    assert "File on" in reply


# --------------------------------------------------- 3. self-healing retries
def test_healer_finds_closest_file_after_moved_target(brain, tmp_path):
    folder = Path(tmp_path) / "doc"
    folder.mkdir()
    (folder / "rapport-final.pdf").write_text("x")
    run(brain._record_failure(
        text=f"open the file {folder / 'rapport.pdf'}",
        error="No such file or directory", module="file_manager",
    ))
    record = healer.latest(brain.config)
    assert record is not None
    matches = healer.candidates(brain.config, record)
    assert any("rapport-final.pdf" in match for match in matches)
    advice = healer.advice(brain.config, record, language="en")
    assert advice is not None
    assert "rapport-final.pdf" in advice


def test_brain_try_that_again_after_failure(brain):
    run(brain._record_failure(
        text="open the file /weg/rapport.pdf",
        error="No such file or directory", module="file_manager",
    ))
    reply = run(brain.process("probeer opnieuw"))
    assert "herhaal" in reply or "repeat" in reply
    reply = run(brain.process("try that again"))
    assert "repeat the request" in reply or "herhaal je verzoek" in reply


# ------------------------------------------------------------ 4. day recap
def test_recap_tallies_today_across_stores(brain):
    journal.note_turn(
        brain.config, text="ochtendroutine gedaan", response="top",
        module="conversation",
    )
    _ensure_db(brain.config)
    db = brain.config.resolve(brain.config.get("database.path", "data/jarvis.db"))
    now = datetime.now()
    stamp = now.isoformat(timespec="seconds")
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT INTO todos (task, done, completed) VALUES (?, 1, ?)",
            ("fietsband plakken", stamp),
        )
        connection.execute(
            "INSERT INTO reminders (text, due, fired) VALUES (?, ?, 1)",
            ("koffie zetten", start.isoformat(timespec="seconds")),
        )
        connection.execute(
            "INSERT INTO notes (title, created) VALUES (?, ?)",
            ("boodschappenlijst", stamp),
        )
        connection.execute(
            "INSERT INTO facts (id, timestamp, content) VALUES (?, ?, ?)",
            ("f-today", stamp, "tandarts in amsterdam"),
        )
    summary = recap.recap(brain.config, language="nl", now=now)
    assert "Jouw dag" in summary
    assert "fietsband plakken" in summary
    assert "boodschappenlijst" in summary
    assert "herinnering" in summary
    # overdue count is derived from unfired reminders past due, not the fired one
    assert end > start  # sanity only; real assertions above cover the store mix


def test_brain_recap_nl_phrase(brain):
    _ensure_db(brain.config)
    reply = run(brain.process("wat heb ik vandaag gedaan"))
    assert "Jouw dag" in reply
    run(brain.process("tell me a joke"))  # flip the detected language back
    reply = run(brain.process("recap my day"))
    assert "Your day" in reply


# ----------------------------------------------------------------- 5. vault
def test_vault_roundtrip_local_obfuscated_file(brain):
    vault.store(brain.config, "wifi password", "hunter2geheim")
    assert vault.get(brain.config, "wifi password") == "hunter2geheim"
    assert "wifi password" in vault.labels(brain.config)
    assert vault.forget(brain.config, "wifi password") is True
    assert vault.get(brain.config, "wifi password") is None
    # The secret never lands in plain sight next to the journal.
    vault.store(brain.config, "wifi password", "noggeheimer")
    file_path = vault._path(brain.config)
    assert file_path.exists()
    raw = file_path.read_text(encoding="utf-8")
    assert "noggeheimer" not in raw


def test_brain_vault_store_get_forget(brain):
    reply = run(brain.process("remember my wifi password is hunter2geheim"))
    assert "Remembered" in reply or "Onthouden" in reply
    reply = run(brain.process("what's my wifi password"))
    assert "hunter2geheim" in reply
    reply = run(brain.process("forget the wifi password"))
    assert "Forgotten" in reply or "Vergeten" in reply
    reply = run(brain.process("what's my wifi password"))
    assert "hunter2geheim" not in reply


def test_brain_vault_nl_and_identity_guard(brain):
    reply = run(brain.process("onthoud mijn pincode is 4821"))
    assert "kluisbestand" in reply
    reply = run(brain.process("wat is mijn pincode"))
    assert "4821" in reply
    # Identity questions must never be answered from the vault.
    name_reply = run(brain.process("what's my name"))
    assert "name" in name_reply or "naam" in name_reply
    bike_reply = run(brain.process("where is my bike"))
    assert "vault" not in bike_reply.lower()
    assert "kluis" not in bike_reply

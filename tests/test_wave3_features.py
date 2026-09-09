# /tests/test_wave3_features.py
"""The five follow-up capabilities (round 3), all verifiable with no LLM.

1. **Plan-first mode** — "make a plan to X and Y" shows a numbered preview
   and waits for "go ahead" / "ga je gang" before executing; "cancel" drops
   it. Nothing fires without approval.
2. **Nudge-until-done** — "nudge me about the report in 2 hours" arms an
   open thread; once/hourly/daily reminders come due and reschedule or stop,
   and the thread stays open until "that's sorted".
3. **Event rules** — "when a new file matching '*.pdf' lands in a folder,
   move it to another" and "when a note mentions 'deadline', add a todo",
   watched locally and idempotently.
4. **Improvement coach** — "what should we improve?" digests his own logs:
   repeated failure signatures, stale open threads, standing corrections.
5. **Project contexts** — "focus on the bike project" tags every new
   todo/note/reminder/fact with the project, and "what's open in the bike
   project?" lists only that project's items.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.brain import Brain
from tests.conftest import build_config, run


def _fresh(factory: pytest.TempPathFactory) -> Brain:
    config = build_config(factory.mktemp("wave3"))
    instance = Brain(config)
    run(instance.initialize())
    return instance


@pytest.fixture()
def brain(tmp_path_factory: pytest.TempPathFactory) -> Brain:
    """A clean offline brain per test."""
    instance = _fresh(tmp_path_factory)
    yield instance
    run(instance.shutdown())


def _seed_thread(brain: Brain, request: str = "the report for tuesday",
                 reply: str = "I'll look into the report and come back to "
                              "you, sir.") -> None:
    """Store an open thread exactly as the after-turn note would."""
    run(brain._note_thread_after_turn(request, reply))


def _ensure_db(config) -> Path:
    db = config.resolve(config.get("database.path", "data/jarvis.db"))
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db))
    with connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL,
                due TEXT, tags TEXT DEFAULT '', done INTEGER DEFAULT 0,
                created TEXT);
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
                due TEXT NOT NULL, fired INTEGER DEFAULT 0, created TEXT);
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT,
                tags TEXT DEFAULT '', created TEXT, updated TEXT);
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY, timestamp TEXT, category TEXT,
                content TEXT, importance REAL DEFAULT 0.5, source TEXT);
            """
        )
    return db


# ---------------------------------------------------------- 1. plan first
def test_plan_first_previews_then_executes_after_approval(brain):
    reply = run(brain.process(
        "make a plan to set a timer for 3 minutes and convert 5 miles "
        "to kilometers"
    ))
    assert "Here's my plan (2 steps):" in reply
    assert "1. productivity" in reply and "2. smart_assistant" in reply
    assert "go ahead" in reply

    reply = run(brain.process("go ahead"))
    assert "Done in one go. 2 step(s):" in reply
    assert "Timer" in reply and "kilometer" in reply.lower()
    # No dangling plan: the approval was consumed.
    assert getattr(brain, "_pending_plan", None) is None


def test_plan_first_cancel_drops_without_executing(brain):
    reply = run(brain.process(
        "make a plan to convert 5 miles to kilometers and set a timer "
        "for 9 minutes"
    ))
    assert "Here's my plan" in reply
    reply = run(brain.process("cancel the plan"))
    assert "Plan dropped" in reply
    # Without approval, nothing ran (no timer was created).
    from core import threads

    assert threads.list_threads(brain.config) == []  # bookkeeping intact
    # And a normal compound still executes instantly afterwards.
    reply = run(brain.process(
        "set a timer for 3 minutes and convert 5 miles to kilometers"
    ))
    assert "Done in one go" in reply or "step" in reply


# ------------------------------------------------------- 2. nudge-until-done
def test_nudge_store_cycle_pure(config):
    from core import threads

    threads.note_thread(
        config, request="check the offer",
        response="I'll look into the offer and come back to you, sir.",
    )
    past = (datetime.now() - timedelta(seconds=5)).isoformat(timespec="seconds")
    assert threads.nudge(config, "1", past, every="hourly") is not None
    assert len(threads.due(config)) == 1

    record = threads.due(config)[0]
    threads.settle(config, record, datetime.now())
    after = threads.list_threads(config)[0]
    assert after["nudge"]["every"] == "hourly"
    assert after["nudge"]["at"] > datetime.now().isoformat(timespec="seconds")

    # A once-nudge is removed after firing.
    assert threads.nudge(config, "1", past, every="once")
    threads.settle(config, threads.due(config)[0], datetime.now())
    assert "nudge" not in threads.list_threads(config)[0]
    assert threads.clear_nudge(config, "1") is False  # nothing left to clear


def test_nudge_flow_dutch_and_clock_parsing(brain):
    run(brain.process("hello"))  # warm-up, English baseline
    _seed_thread(brain, request="de offerte voor klant x")
    from core import threads

    reply = run(brain.process("blijf me herinneren aan nummer 1 over 2 uur"))
    assert "porren" in reply or "herinneren" in reply.lower()
    record = threads.list_threads(brain.config)[0]
    nudge = record["nudge"]
    assert nudge["every"] == "once"
    assert datetime.fromisoformat(nudge["at"]) > datetime.now()

    # A clock must not be mistaken for a thread number ("morgen om 9:00"
    # must not select thread 9) and overwrites the schedule.
    reply = run(brain.process(
        "herinner me nogmaals over de offerte morgen om 9:00"
    ))
    assert "9:00" in reply
    nudge = threads.list_threads(brain.config)[0]["nudge"]
    tomorrow = datetime.now() + timedelta(days=1)
    assert datetime.fromisoformat(nudge["at"]).day == tomorrow.day


def test_due_nudge_messages_reschedule(brain):
    run(brain.process("hello"))
    _seed_thread(brain)
    from core import threads

    past = (datetime.now() - timedelta(seconds=5)).isoformat(timespec="seconds")
    threads.nudge(brain.config, "1", past, every="hourly")
    messages = run(brain.due_nudge_messages())
    assert len(messages) == 1 and "still open" in messages[0]
    assert threads.due(brain.config) == []  # already advanced


# ---------------------------------------------------------- 3. event rules
def test_file_rule_moves_matching_files_once(config, tmp_path: Path):
    from core import rules

    source = tmp_path / "incoming"
    target = tmp_path / "sorted"
    source.mkdir()
    target.mkdir()
    rules.add_rule(
        config, kind="file",
        trigger={"folder": str(source), "pattern": "*.pdf"},
        action={"kind": "move", "to": str(target)},
    )
    (source / "a.pdf").write_text("one")
    (source / "b.txt").write_text("two")
    fired = rules.run_once(config, reply=True)
    assert any("a.pdf" in item["text"] for item in fired)
    assert (target / "a.pdf").exists() and (source / "b.txt").exists()
    # Idempotent: the watcher remembers the folder, so a second pass is empty.
    assert rules.run_once(config) == []
    # A *new* matching file still fires.
    (source / "c.pdf").write_text("three")
    assert len(rules.run_once(config, reply=True)) == 1


def test_keyword_rule_creates_todo_from_note(config):
    from core import rules

    _ensure_db(config)
    rules.add_rule(
        config, kind="keyword",
        trigger={"table": "notes", "word": "deadline"},
        action={"kind": "todo", "text": "follow up on the deadline"},
    )
    db = config.resolve(config.get("database.path", "data/jarvis.db"))
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT INTO notes (title, body) VALUES ('report', "
            "'the deadline is friday')"
        )
    fired = rules.run_once(config, reply=True)
    assert any("created todo" in item["text"] for item in fired)
    with sqlite3.connect(str(db)) as connection:
        tasks = [row[0] for row in connection.execute(
            "SELECT task FROM todos")]
    assert any("deadline" in task for task in tasks)
    # High-water mark: the same note does not re-fire.
    assert rules.run_once(config) == []


def test_rule_create_list_remove_via_brain(config, tmp_path: Path):
    from core import rules

    source = tmp_path / "watch"
    target = tmp_path / "sorted"
    source.mkdir()
    target.mkdir()
    rule = rules.add_rule(
        config, kind="file",
        trigger={"folder": str(source), "pattern": "*.pdf"},
        action={"kind": "move", "to": str(target)},
    )
    assert rules.list_rules(config)
    assert rules.remove_rule(config, rule["id"]) == 1
    assert rules.list_rules(config) == []


# ---------------------------------------------------------- 4. coach
def test_coach_digest_points_at_repeated_failures(brain):
    from core import coach, failures

    failures.note_failure(brain.config, text="set a timer",
                          error="boom boom", module="productivity")
    failures.note_failure(brain.config, text="convert miles",
                          error="boom boom", module="productivity")
    digest = coach.digest(brain, "en")
    assert "Most repeated failure" in digest
    assert "2x in productivity" in digest

    reply = run(brain.process("what should we improve?"))
    assert "Most repeated failure" in reply

    reply = run(brain.process("wat moeten we verbeteren"))
    assert "herhaalde fout" in reply


def test_coach_digest_clean_and_stale_thread(brain):
    from core import coach, threads

    assert "Good news" in coach.digest(brain, "en")
    # A stale open thread surfaces as a coaching point. Craft one directly
    # with an old timestamp, since the live note is always "now".
    journal = brain.config.resolve(
        brain.config.get("assistant.journal_file", "data/journal.json")
    )
    store = journal.parent / "threads.jsonl"
    old = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
    store.parent.mkdir(parents=True, exist_ok=True)
    import json

    with store.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "id": "stale1", "ts": old, "day": old[:10],
            "request": "stale thing", "reply": "I'll come back to you, sir.",
            "module": "conversation", "kind": "promise",
        }, ensure_ascii=False) + "\n")
    digest = coach.digest(brain, "en")
    assert "stale thing" in digest and "dangling" in digest
    assert threads.list_threads(brain.config)  # and still an open thread


# ---------------------------------------------------- 5. project contexts
def test_projects_tag_only_future_rows(config):
    from core import projects

    _ensure_db(config)
    db = config.resolve(config.get("database.path", "data/jarvis.db"))
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT INTO todos (task, done) VALUES ('oud klusje', 0)"
        )
    projects.activate(config, "Bike project")
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT INTO todos (task, done, created) VALUES "
            "('nieuw zadel kopen', 0, 'x')"
        )
        connection.execute(
            "INSERT INTO reminders (text, due, fired) VALUES "
            "('reminder fiets', '2026-09-10T09:00:00', 0)"
        )
    assert projects.tag_new_rows(config) == 2
    with sqlite3.connect(str(db)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT task, tags FROM todos ORDER BY id"
        ).fetchall()
    tags = {row["task"]: row["tags"] for row in rows}
    assert tags["oud klusje"] == ""          # never retro-fitted
    assert "bike-project" in tags["nieuw zadel kopen"]

    overview = projects.project_overview(config, "bike")
    assert overview["counts"]["todos"] == 1
    assert overview["counts"]["reminders"] == 1
    projects.deactivate(config)
    assert projects.active(config) == ""


def test_projects_flow_overview_beats_thread_list(brain):
    from core import projects

    reply = run(brain.process("focus op het fietsproject"))
    assert "fietsproject" in reply
    assert projects.active(brain.config) == "fietsproject"

    _ensure_db(brain.config)
    db = brain.config.resolve(
        brain.config.get("database.path", "data/jarvis.db")
    )
    with sqlite3.connect(str(db)) as connection:
        connection.execute(
            "INSERT INTO todos (task, done, created) VALUES "
            "('nieuw zadel', 0, 'x')"
        )
    # A normal turn runs the after-turn housekeeping that tags the row.
    run(brain.process("dank je wel"))
    with sqlite3.connect(str(db)) as connection:
        row = connection.execute(
            "SELECT tags FROM todos WHERE task = 'nieuw zadel'"
        ).fetchone()
    assert "fietsproject" in (row[0] or "")

    # "wat staat er open in het fietsproject" must answer with the project
    # overview, not with the open-thread listing.
    reply = run(brain.process("wat staat er open in het fietsproject"))
    assert "fietsproject" in reply and "nieuw zadel" in reply
    assert "Openstaande zaken" not in reply

    reply = run(brain.process("focus uit"))
    assert "uitgezet" in reply and projects.active(brain.config) == ""

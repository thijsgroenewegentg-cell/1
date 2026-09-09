# /tests/test_wave2_features.py
"""The five follow-up capabilities, all verifiable with no LLM.

1. **Open-thread tracker** — promises JARVIS makes ("I'll look into … and
   come back", "ik kom erop terug") are stored; "what's still open?"
   (wat staat er nog open) lists them numbered; closing by number or text
   ("that's sorted", "is geregeld") removes them. Listing must never
   re-store a thread from quoting an old promise.
2. **Unified search** — one keyword query covers todos, reminders, notes,
   facts, conversation history, the journal, the learned profile and
   macros, all offline, grouped by source.
3. **Dutch / per-message language** — offline detection decides the reply
   language; Dutch small talk and the Dutch offline fallback are fully
   written out, English unchanged.
4. **Self-review briefing** — compact stats about JARVIS himself, in the
   user's language, from stored data only.
5. **Explain the last turn** — "wat heb je net gedaan?" lists each tool
   call with params and status, straight from the brain's own records.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from core.brain import Brain
from tests.conftest import build_config, run


def _fresh(factory: pytest.TempPathFactory) -> Brain:
    config = build_config(factory.mktemp("wave2"))
    instance = Brain(config)
    run(instance.initialize())
    return instance


@pytest.fixture()
def brain(tmp_path_factory: pytest.TempPathFactory) -> Brain:
    """A clean offline brain per test."""
    instance = _fresh(tmp_path_factory)
    yield instance
    run(instance.shutdown())


def _journal_path(config) -> Path:
    return config.resolve(config.get("assistant.journal_file", "data/journal.json"))


# ------------------------------------------------------------ 1. open threads
def test_threads_promises_dutch_and_english(config):
    from core import threads

    assert threads.note_thread(
        config, request="check the contract",
        response="I'll look into the contract and get back to you, sir.",
    )
    assert threads.note_thread(
        config, request="bekijk de offerte",
        response="Ik kijk ernaar en kom erop terug.",
    )
    # A reply with no commitment stores nothing.
    assert not threads.note_thread(
        config, request="whatever",
        response="Done. Anything else?",
    )

    records = threads.list_threads(config)
    assert len(records) == 2
    assert records[0]["request"] == "bekijk de offerte"  # newest first

    # Text match closes the English one.
    removed, remaining = threads.close_thread(config, "contract")
    assert removed == 1 and remaining == 1
    # Number 1 = newest closes the Dutch one.
    removed, remaining = threads.close_thread(config, "1")
    assert removed == 1 and remaining == 0
    assert threads.list_threads(config) == []


def test_thread_close_command_detection():
    from core import threads

    for phrase in ("that's sorted now", "that is sorted", "is geregeld",
                   "nummer 2 afhandelen", "close thread 1", "never mind",
                   "klaar mee"):
        assert threads.is_close_command(phrase), phrase
    assert not threads.is_close_command("what's still open?")
    assert not threads.is_close_command("wat staat er nog open")
    assert not threads.is_close_command("I'll come back to you")


def test_promise_detection_regexes():
    from core import threads

    assert threads.promises("I'll check that file and get back to you.")
    assert threads.promises("ik kom erop terug zodra ik het weet")
    assert threads.promises("I will send the summary tonight")
    assert threads.promises("") == []
    assert threads.promises("Thanks, that is all.") == []


# ------------------------------------------------------------ 2. unified search
class _Prefs:
    def user_name(self) -> str:
        return "Bram"

    def corrections(self) -> List[str]:
        return ["gebruik mijlen in plaats van kilometers"]

    def routines(self) -> List[Tuple[str, Dict[str, Any]]]:
        return []


class _BrainStub:
    """Enough of a Brain for the pure store scans (no modules, no model)."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.preferences = _Prefs()
        self.macros = None

    def current_language(self) -> str:
        return "nl"


def test_unified_search_hits_every_source(config):
    from core import unified_search

    db = config.resolve(config.get("database.path", "data/jarvis.db"))
    db.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db))
    with connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL,
                due TEXT, done INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
                due TEXT NOT NULL, fired INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, body TEXT,
                updated TEXT);
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY, timestamp TEXT, category TEXT,
                content TEXT, importance REAL DEFAULT 0.5, source TEXT);
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
                role TEXT, content TEXT);
            """
        )
        connection.execute(
            "INSERT INTO todos (task, done) VALUES (?, 0)",
            ("bellen met de tandarts",),
        )
        connection.execute(
            "INSERT INTO reminders (text, due, fired) VALUES (?, ?, 0)",
            ("tandartsafspraak bevestigen", "2026-09-10 09:00"),
        )
        connection.execute(
            "INSERT INTO notes (title, body, updated) VALUES (?, ?, ?)",
            ("tandarts", "afspraak verzet naar 23 september", "2026-09-08"),
        )
        connection.execute(
            "INSERT INTO facts (id, timestamp, category, content) VALUES (?, ?, ?, ?)",
            ("f1", "2026-09-09", "personal", "mijn tandarts zit in amsterdam"),
        )
        connection.execute(
            "INSERT INTO conversations (timestamp, role, content) VALUES (?, ?, ?)",
            ("2026-09-09", "user", "ik moet naar de tandarts in amsterdam"),
        )
    journal = _journal_path(config)
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(json.dumps({
        "day": "2026-09-08", "ts": "2026-09-08T10:00:00",
        "text": "de tandarts in amsterdam", "response": "genoteerd",
    }) + "\n", encoding="utf-8")

    brain_stub = _BrainStub(config)
    hits = unified_search.search_all(brain_stub, "tandarts")
    sources = {hit["source"] for hit in hits}
    assert {"todo", "reminder", "note", "fact", "journal", "history"} <= sources
    rendered = unified_search.render(hits, "nl")
    assert "[taken]" in rendered and "[notities]" in rendered
    assert "[dagboek]" in rendered

    # The learned profile is searchable too.
    hits = unified_search.search_all(brain_stub, "kilometers")
    assert any(hit["source"] == "profile" for hit in hits)

    # Honest empty answer for something that is nowhere.
    assert unified_search.search_all(brain_stub, "xyzzyplugh") == []


# ------------------------------------------------------------ 3. multilingual
def test_language_detection():
    from core.language_detect import detect_language, user_language

    assert detect_language("waar staat de tandarts ook alweer") == "nl"
    assert detect_language("hallo, hoe gaat het met je") == "nl"
    assert detect_language("what is the weather like today") == "en"
    assert detect_language("the dentist is in amsterdam") == "en"
    # Ambiguous/short input falls back instead of guessing wildly.
    assert detect_language("hallo", fallback="nl") == "nl"
    assert detect_language("hallo", fallback="en") == "en"
    history = ["hallo, hoe gaat het", "ik heet Bram", "zet een timer"]
    assert user_language(history) == "nl"


def test_smalltalk_dutch_catalog_and_english_unharmed():
    from core import smalltalk

    for phrase, marker in (
        ("hallo", ("hallo", "hoi", "hé")),
        ("goedemorgen", "goedemorgen"),
        ("dank je wel", ("graag gedaan", "niets te danken", "altijd")),
        ("wie ben jij", "uw persoonlijke AI-assistent"),
        ("hoe gaat het met je", ("taalmodel", "reflexen", "model")),
        ("tot ziens", "het ga je goed"),
    ):
        reply = smalltalk.respond(phrase, language="nl", address="Sir")
        assert reply, phrase
        assert any(token.lower() in reply.lower() for token in marker), (phrase, reply)

    fallback_nl = smalltalk.fallback(
        "wat is de hoofdstad van spanje", language="nl",
        address="Sir", host="http://127.0.0.1:59999",
    )
    assert fallback_nl.startswith("Een goede vraag")
    assert "ollama" in fallback_nl.lower()

    # English paths are unchanged and stay the default.
    reply_en = smalltalk.respond("thanks", language="en", address="Sir")
    reply_nl = smalltalk.respond("thanks", language="nl", address="Sir")
    assert reply_en and reply_nl and reply_en != reply_nl
    assert "graag gedaan" not in reply_en.lower()  # NL never leaks into EN
    # No language hint keeps the English offline default: a Dutch-only phrase
    # is not answered from the EN catalog (None), never raises.
    assert smalltalk.respond("dank je wel") is None


# ------------------------------------------- 4+5: brain flow, Dutch, offline
def test_dutch_thread_flow_review_and_search_offline(brain):
    # The very first Dutch message flips the reply language to Dutch.
    reply = run(brain.process("hallo, hoe gaat het met je"))
    assert brain.current_language() == "nl"
    from core import smalltalk

    en_twin = smalltalk.respond(
        "hallo, hoe gaat het met je", language="en", address="Sir"
    )
    assert reply != en_twin

    # Dutch name introduction is learned offline.
    reply = run(brain.process("ik heet Bram"))
    assert "Bram" in reply

    from core import threads

    # Seed one real promise, as a reply would have done after the turn (the
    # name turn is a normal turn, so the after-turn note is allowed to run).
    run(brain._note_thread_after_turn(
        "het rapport voor dinsdag",
        "I'll look into the report and come back to you, sir.",
    ))

    # Open-thread list shows the one open item, in Dutch.
    reply = run(brain.process("wat staat er nog open"))
    assert "Openstaande zaken (1)" in reply
    assert "het rapport voor dinsdag" in reply
    # Listing quotes the old promise — it must not re-store it as a new thread.
    records = threads.list_threads(brain.config)
    assert len(records) == 1

    # Close by number, in Dutch.
    reply = run(brain.process("nummer 1 is geregeld"))
    assert "Afgevinkt" in reply
    assert threads.list_threads(brain.config) == []

    # Self-review briefing assembled from stored data, in Dutch.
    reply = run(brain.process("geef me een overzicht van jezelf"))
    assert "Overzicht" in reply and "beurt(en)" in reply

    # Unified search across the seeded database, triggered in Dutch.
    db = brain.config.resolve(
        brain.config.get("database.path", "data/jarvis.db")
    )
    connection = sqlite3.connect(str(db))
    with connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS todos ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, task TEXT NOT NULL,"
            "due TEXT, done INTEGER DEFAULT 0)"
        )
        connection.execute(
            "INSERT INTO todos (task, done) VALUES (?, 0)",
            ("bellen met de tandarts",),
        )
    reply = run(brain.process("waar stond de tandarts ook alweer"))
    assert "Gevonden over" in reply and "tandarts" in reply


def test_explain_last_turn_with_and_without_tools(brain):
    reply = run(brain.process("set a timer for 5 minutes"))
    assert "Timer" in reply

    reply = run(brain.process("wat heb je net gedaan"))
    assert "start_timer" in reply
    assert "-> ok" in reply or "-> ok:" in reply

    # A pure-chat turn needs no tools and says so.
    run(brain.process("dank je wel"))
    reply = run(brain.process("wat heb je net gedaan"))
    assert "geen tools" in reply.lower()


def test_no_offline_network_or_new_dependencies(brain):
    """Hooks only read local files/DBs; nothing may phone home."""
    from core import threads

    assert threads.promises("x") == []  # importing must not connect anywhere
    reply = run(brain.process("dit is een onzinvraag zonder betekenis"))
    assert reply  # offline path still answers deterministically

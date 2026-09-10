# /tests/test_presence_and_blender.py
"""Presence that shows up unasked, Dutch canned lines, Blender primitives."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from core import journal, presence, threads
from modules.blender import Blender
from tests.conftest import PROJECT_ROOT, run

FAKE_BLENDER = PROJECT_ROOT / "tests" / "fake_blender.py"


def _yesterday() -> str:
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def test_presence_surfaces_yesterday_and_open_threads(config):
    day = _yesterday()
    path = config.resolve(config.get("assistant.journal_file", "data/journal.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "ts": f"{day}T09:00:00",
            "day": day,
            "text": "rendered the donut",
            "response": "Done.",
            "module": "blender",
            "tools": ["blender.render"],
            "ok": True,
        })
        + "\n",
        encoding="utf-8",
    )
    threads.note_thread(
        config,
        request="check the lighting",
        response="I'll look into the lighting and get back to you.",
        module="blender",
    )
    spoken = presence.spoken(config, blender_last="/tmp/donut.blend")
    assert "Yesterday" in spoken
    assert "Still open" in spoken or "donut.blend" in spoken
    block = presence.block(config, blender_last="/tmp/donut.blend")
    assert "Already on file" in block
    assert "rendered the donut" not in block or "Yesterday" in block
    dutch = presence.spoken(config, dutch=True, blender_last="/tmp/donut.blend")
    assert "Gisteren" in dutch or "Nog open" in dutch or "Laatste" in dutch


def _brain(config):
    from core.brain import Brain

    brain = Brain(config)
    run(brain.initialize())
    return brain


def test_greeting_is_dutch_when_the_language_is(config):
    config.set("assistant.language", "nl")
    brain = _brain(config)
    try:
        text = run(brain.greeting())
        assert text.startswith(("Goedemorgen", "Goedemiddag", "Goedenavond"))
        assert "Good morning" not in text
        assert "Good afternoon" not in text
        assert "Good evening" not in text
    finally:
        run(brain.shutdown())


def test_greeting_mentions_what_is_already_on_file(config):
    day = _yesterday()
    path = config.resolve(config.get("assistant.journal_file", "data/journal.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "ts": f"{day}T10:00:00",
            "day": day,
            "text": "rigged the bike",
            "response": "Done.",
            "module": "productivity",
            "tools": ["productivity.add_todo"],
            "ok": True,
        })
        + "\n",
        encoding="utf-8",
    )
    brain = _brain(config)
    try:
        spoken = brain.presence_spoken()
        assert "Yesterday" in spoken
        text = run(brain.greeting())
        assert "Yesterday" in text
    finally:
        run(brain.shutdown())


def test_a_cube_is_built_without_a_language_model(config, tmp_path):
    config.set("blender.executable", str(FAKE_BLENDER))
    config.set("blender.output_dir", str(tmp_path / "renders"))
    module = Blender(config)
    module.llm = None
    result = run(module.call_tool("make_scene", {
        "description": "a red cube on a plane",
        "preview": True,
    }))
    assert result.success, result.error
    blend = result.data["blend"]
    assert blend.endswith(".blend")
    saved = json.loads(Path(blend).read_text(encoding="utf-8"))
    types = {entry["type"] for entry in saved["objects"]}
    assert "MESH" in types
    assert "CAMERA" in types
    assert "LIGHT" in types
    assert result.data.get("preview"), "preview still should render"


def test_a_castle_still_needs_the_model(config, tmp_path):
    config.set("blender.executable", str(FAKE_BLENDER))
    config.set("blender.output_dir", str(tmp_path / "renders"))
    module = Blender(config)
    module.llm = None
    result = run(module.call_tool("make_scene", {"description": "a castle"}))
    assert not result.success
    assert "language model" in result.error.lower()


def test_dutch_connects_and_builds_in_the_blender_router(config, tmp_path):
    config.set("blender.executable", str(FAKE_BLENDER))
    config.set("blender.output_dir", str(tmp_path / "renders"))
    module = Blender(config)
    assert module.offline_router("verbind blender")[0] == "blender_status"
    assert module.offline_router("maak een rode kubus")[0] == "make_scene"
    assert module.offline_router("blender openen")[0] == "open_blender"


def test_brief_line_has_a_dutch_form(config):
    day = _yesterday()
    path = config.resolve(config.get("assistant.journal_file", "data/journal.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "ts": f"{day}T09:00:00",
            "day": day,
            "text": "hello",
            "response": "hi",
            "module": "conversation",
            "tools": [],
            "ok": True,
        })
        + "\n",
        encoding="utf-8",
    )
    assert journal.brief_line(config, day).startswith("Yesterday:")
    assert journal.brief_line(config, day, dutch=True).startswith("Gisteren:")

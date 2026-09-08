# /tests/test_guardian.py
"""The data guardian (B): snapshots, retention, restore and auto-backup.

Everything runs inside pytest's ``tmp_path`` with a dead LLM host, so the
backup zips are real but never touch the working tree.
"""

from __future__ import annotations

import zipfile
from datetime import datetime, timedelta

import pytest

from modules.guardian import Guardian
from tests.conftest import run


@pytest.fixture
def guardian(config):
    """A Guardian module with a fresh backup directory under tmp_path."""
    module = Guardian(config)
    yield module
    run(module.shutdown())


def _precious(config, text: str = "top secret plans") -> None:
    path = config.resolve("data/precious.txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_backup_data_creates_a_zip_and_lists_it(config, guardian):
    _precious(config)
    result = run(guardian.backup_data())
    assert result.success
    assert "Snapshot complete" in result.speak
    assert result.data["backup"]["files"] >= 1

    listing = run(guardian.list_backups())
    assert listing.success
    assert listing.data["backups"]
    assert "top secret plans" not in listing.speak  # speakable: names, not contents
    newest = listing.data["backups"][0]
    assert zipfile.is_zipfile(config.resolve(newest["path"]))


def test_restore_puts_deleted_files_back(config, guardian):
    _precious(config, "version one")
    created = run(guardian.backup_data())
    name = created.data["backup"]["name"]

    path = config.resolve("data/precious.txt")
    path.write_text("clobbered", encoding="utf-8")
    restored = run(guardian.restore_backup_tool(name=name))
    assert restored.success
    assert "Restored" in restored.speak
    assert path.read_text(encoding="utf-8") == "version one"


def test_restore_with_no_name_lists_what_is_available(config, guardian):
    _precious(config)
    run(guardian.backup_data())
    result = run(guardian.restore_backup_tool())
    assert result.success          # a question, not a failure
    assert result.data["backups"]


def test_restore_with_an_unknown_name_fails_politely(config, guardian):
    _precious(config)
    run(guardian.backup_data())
    result = run(guardian.restore_backup_tool(name="never-existed.zip"))
    assert not result.success
    assert "can't find" in result.error.lower()


def test_keep_backups_prunes_the_oldest(config, monkeypatch):
    config.set("assistant.keep_backups", 2)
    module = Guardian(config)  # created after the knob, so retention reads 2
    _precious(config)
    base = datetime.now()

    class RollingClock(datetime):
        _tick = 0

        @classmethod
        def now(cls, tz=None) -> "RollingClock":
            RollingClock._tick += 1
            return base + timedelta(seconds=RollingClock._tick)

    import utils.backup as backup_utils

    monkeypatch.setattr(backup_utils, "datetime", RollingClock)
    first = run(module.backup_data()).data["backup"]["name"]
    run(module.backup_data())
    third = run(module.backup_data()).data["backup"]["name"]

    listing = run(module.list_backups())
    names = [item["name"] for item in listing.data["backups"]]
    assert len(names) == 2
    assert first not in names
    assert third in names
    run(module.shutdown())


def test_auto_backup_runs_a_single_daily_loop(config):
    config.set("assistant.auto_backup", True)
    module = Guardian(config)

    async def scenario() -> None:
        await module.setup()
        assert module._snapshot_task is not None
        assert not module._snapshot_task.done()
        await module.shutdown()

    run(scenario())
    assert module._snapshot_task is None


def test_auto_backup_is_off_by_default(config):
    module = Guardian(config)
    assert module.auto_backup is False
    assert module.keep == 5
    assert module.backup_dir.name == "backups"


def test_the_backup_phrase_reaches_the_guardian_offline(config):
    """The spoken backup phrase routes to guardian without any model."""
    from core.brain import Brain

    brain = Brain(config)
    run(brain.initialize())
    try:
        reply = run(brain.process("back up my data"))
        assert "Snapshot complete" in reply
    finally:
        run(brain.shutdown())
    listing = Guardian(config).list_backups()
    assert run(listing).data["backups"]

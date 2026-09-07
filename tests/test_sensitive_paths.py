"""Credential files are gated before they can be read out.

Every path check in the guard was roots-based: is this inside $HOME or an
allowed root? Credentials fail that test in the worst possible direction —
``~/.ssh/id_rsa`` and ``~/.aws/credentials`` sit *inside* $HOME, so they were
graded SAFE and ``read_file`` handed them over without a word. The module's own
injection patterns already anticipate ``cat ~/.ssh/id_rsa`` arriving from a
scraped web page, so the exposure was reachable, not theoretical.

Credentials are now DANGEROUS (confirm), never BLOCKED: the user can still say
yes to their own files. Bulk readers skip them silently instead of prompting
per file, and with confirmation switched off — the web UI and service case —
they are refused rather than waved through.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from core.config import Config
from modules.file_manager import FileManager
from utils.security import SecurityGuard


@pytest.fixture
def guard() -> SecurityGuard:
    """A guard built from the shipped configuration."""
    config = Config.load("config.yaml")
    return SecurityGuard.from_config(config.section("security"))


@pytest.fixture
def secrets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake home containing the credential files worth stealing."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_rsa").write_text("PRIVATE KEY MATERIAL\n")
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "credentials").write_text("aws_secret_access_key = s3cret\n")
    (tmp_path / "certs").mkdir()
    (tmp_path / "certs" / "server.pem").write_text("PEM MATERIAL\n")
    (tmp_path / "notes.txt").write_text("an ordinary file\n")
    return tmp_path


# ------------------------------------------------------------- classification
@pytest.mark.parametrize(
    "relative",
    [
        ".ssh/id_rsa",
        ".ssh/id_ed25519",
        ".aws/credentials",
        ".gnupg/secring.gpg",
        ".netrc",
        ".git-credentials",
        ".npmrc",
        ".kube/config",
        ".docker/config.json",
        "certs/server.pem",
        "keys/private.key",
        "project/.env",
    ],
)
def test_credential_files_need_confirmation(
    guard: SecurityGuard, secrets: Path, relative: str
) -> None:
    assessment = guard.is_path_allowed(secrets / relative, write=False)
    assert assessment.needs_confirmation, f"{relative} was graded {assessment.level}"
    # Confirmable, not blocked: they are the user's own files.
    assert not assessment.blocked


@pytest.mark.parametrize(
    "relative", ["notes.txt", "Documents/report.pdf", "photo.png", "code/main.py"]
)
def test_ordinary_files_are_untouched(
    guard: SecurityGuard, secrets: Path, relative: str
) -> None:
    assert not guard.is_path_allowed(secrets / relative, write=False).needs_confirmation


def test_reading_is_gated_not_only_writing(guard: SecurityGuard, secrets: Path) -> None:
    # The danger is exfiltration, so a read must be graded like a write.
    key = secrets / ".ssh" / "id_rsa"
    assert guard.is_path_allowed(key, write=False).needs_confirmation
    assert guard.is_path_allowed(key, write=True).needs_confirmation


def test_keys_outside_home_are_recognised(guard: SecurityGuard) -> None:
    assert guard.is_path_allowed("/srv/deploy/id_rsa", write=False).needs_confirmation


def test_the_helper_agrees_with_the_assessment(guard: SecurityGuard, secrets: Path) -> None:
    assert guard.is_sensitive_path(secrets / ".ssh" / "id_rsa")
    assert not guard.is_sensitive_path(secrets / "notes.txt")


def test_the_helper_survives_nonsense(guard: SecurityGuard) -> None:
    assert not guard.is_sensitive_path("")


# ----------------------------------------------------------------- read_file
def _manager(confirm: bool, answer: bool | None = None) -> FileManager:
    """A FileManager whose confirmation hook answers ``answer``."""
    config = Config.load("config.yaml")
    config.set("security.confirm_dangerous", confirm)
    manager = FileManager(config)

    async def hook(_prompt: str) -> bool:
        return bool(answer)

    if answer is not None:
        manager.security._confirm_hook = hook  # type: ignore[attr-defined]
    return manager


def test_read_file_refuses_a_key_when_nobody_can_be_asked(secrets: Path) -> None:
    # confirm_dangerous: false is how the web UI and the service run. Treating
    # "cannot ask" as "go ahead" is what made this exploitable unattended.
    manager = _manager(confirm=False)
    result = asyncio.run(
        manager.call_tool("read_file", {"path": str(secrets / ".ssh" / "id_rsa")})
    )
    assert not result.success
    assert "PRIVATE KEY MATERIAL" not in result.output
    assert "credential" in result.output.lower()


def test_read_file_asks_and_honours_no(secrets: Path) -> None:
    manager = _manager(confirm=True, answer=False)
    result = asyncio.run(
        manager.call_tool("read_file", {"path": str(secrets / ".aws" / "credentials")})
    )
    assert not result.success
    assert "s3cret" not in result.output


def test_read_file_still_allows_an_explicit_yes(secrets: Path) -> None:
    # The user must remain able to read their own key on request.
    manager = _manager(confirm=True, answer=True)
    result = asyncio.run(
        manager.call_tool("read_file", {"path": str(secrets / ".ssh" / "id_rsa")})
    )
    assert result.success
    assert "PRIVATE KEY MATERIAL" in result.output


def test_ordinary_reads_are_not_slowed_down(secrets: Path) -> None:
    manager = _manager(confirm=False)
    result = asyncio.run(
        manager.call_tool("read_file", {"path": str(secrets / "notes.txt")})
    )
    assert result.success
    assert "an ordinary file" in result.output


# --------------------------------------------------------------- bulk readers
def test_grep_skips_credentials_without_prompting(secrets: Path) -> None:
    # A per-file prompt during a scan is unusable and trains the user to
    # say yes; the match line would print the key anyway.
    manager = _manager(confirm=False)
    result = asyncio.run(
        manager.call_tool("search_content", {"text": "MATERIAL", "path": str(secrets)})
    )
    assert result.success
    assert "id_rsa" not in result.output
    assert "server.pem" not in result.output


def test_the_indexer_skips_credentials(secrets: Path) -> None:
    from modules.knowledge import Knowledge

    config = Config.load("config.yaml")
    config.set("security.confirm_dangerous", False)
    knowledge = Knowledge(config)
    discovered = knowledge._iter_documents(secrets)
    names = {path.name for path in discovered}
    assert "server.pem" not in names
    assert "id_rsa" not in names

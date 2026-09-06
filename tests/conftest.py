# /tests/conftest.py
"""Shared pytest configuration and fixtures.

``tests/test_smoke.py`` is an end-to-end script, not a pytest module: it
boots a mock Ollama, builds the whole assistant and prints its own report.
``modules/self_improve.py`` runs it with ``python tests/test_smoke.py``, so
it must keep working as a standalone program — pytest ignores it and runs the
per-module unit tests instead.

Run everything with::

    pytest                      # fast per-module unit tests
    python tests/test_smoke.py  # full integration sweep

Every test here runs offline: the LLM host points at a closed port so the
modules take their rule-based paths, nothing touches the network, and all
writes land in pytest's ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path
from typing import Any, Awaitable, TypeVar

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

collect_ignore = ["test_smoke.py", "mock_ollama.py"]

T = TypeVar("T")

#: A port nothing is listening on, so every LLM call fails fast.
DEAD_LLM_HOST = "http://127.0.0.1:59999"


def run(coro: Awaitable[T]) -> T:
    """Run a coroutine to completion from a synchronous test.

    The project has no pytest-asyncio dependency on purpose — one helper is
    cheaper than a plugin.

    Args:
        coro: The awaitable to run.

    Returns:
        Whatever the coroutine returned.
    """
    return asyncio.run(coro)  # type: ignore[arg-type]


def build_config(tmp_path: Path, **overrides: Any) -> Any:
    """Create a Config that writes only inside ``tmp_path`` and has no LLM.

    Args:
        tmp_path: pytest's per-test temporary directory.
        **overrides: Dotted keys to set afterwards, e.g. ``**{"voice.enabled": False}``.

    Returns:
        A ready :class:`core.config.Config`.
    """
    from core.config import DEFAULT_CONFIG, Config

    data = copy.deepcopy(DEFAULT_CONFIG)
    data["llm"]["host"] = DEAD_LLM_HOST
    data["paths"] = {
        "data": str(tmp_path / "data"),
        "logs": str(tmp_path / "data" / "logs"),
        "backups": str(tmp_path / "data" / "backups"),
        "screenshots": str(tmp_path / "data" / "screenshots"),
        "knowledge": str(tmp_path / "data" / "knowledge"),
    }
    data["database"] = {"path": str(tmp_path / "data" / "jarvis.db")}
    data["memory"]["path"] = str(tmp_path / "data" / "chroma")
    data["voice"]["enabled"] = False
    # Nothing can block on input() in a test run.
    data["security"]["confirm_dangerous"] = False

    config = Config(data=data, path=tmp_path / "config.yaml")
    for key, value in overrides.items():
        config.set(key, value)
    config.ensure_directories()
    return config


@pytest.fixture
def config(tmp_path: Path) -> Any:
    """An offline Config rooted in ``tmp_path``."""
    return build_config(tmp_path)


@pytest.fixture(scope="session")
def shared_config(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """One offline Config for read-only tests, built once per session."""
    return build_config(tmp_path_factory.mktemp("jarvis"))

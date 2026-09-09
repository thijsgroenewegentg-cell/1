# /tests/test_wave4_ui.py
"""Wave-4 discoverability: bilingual help text + web-console suggestions.

The five wave-4 features (bulk actions, dossiers, self-healing retries, the
day recap and the local vault) are brain-level hooks rather than modules, so
they were invisible in the generated "what can you do?" catalogue. These
tests pin the help-text block (EN + NL) and the web console affordances
(suggestion chips near the dock and command-palette quick entries).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.brain import Brain
from tests.conftest import build_config, run

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "interfaces" / "app.html"


@pytest.fixture()
def brain(tmp_path_factory: pytest.TempPathFactory) -> Brain:
    """A clean offline brain per test."""
    config = build_config(tmp_path_factory.mktemp("wave4ui"))
    instance = Brain(config)
    run(instance.initialize())
    yield instance
    run(instance.shutdown())


def test_help_text_lists_wave4_features_in_english(brain):
    brain._user_language = "en"
    reply = brain.help_text()
    assert "Here's what I can do" in reply
    assert "Bulk actions" in reply
    assert "Topic dossiers" in reply
    assert "Self-healing retries" in reply
    assert "Day recap" in reply
    assert "Local vault" in reply
    assert "never in notes, logs or the cloud" in reply


def test_help_text_lists_wave4_features_in_dutch(brain):
    brain._user_language = "nl"
    reply = brain.help_text()
    assert "Hier is wat ik kan" in reply
    assert "Bulkacties" in reply
    assert "Topic-dossiers" in reply
    assert "Zelfherstellende retries" in reply
    assert "Dagoverzicht" in reply
    assert "Lokaal kluisje" in reply
    assert "nooit in notities, logs of de cloud" in reply


def test_help_via_chat_answers_offline(brain):
    """The capability question itself must stay answerable offline."""
    reply = run(brain.process("what can you do?"))
    assert "Here's what I can do" in reply
    assert "Local vault" in reply
    assert "never in notes, logs or the cloud" in reply


def test_app_html_has_suggestion_chips():
    html = APP_HTML.read_text(encoding="utf-8")
    assert '<div id="chips"' in html
    for example in (
        "Recap my day",
        "Wat heb ik vandaag gedaan",
        "vink alles af in het fietsproject",
        "brief me over de verbouwing",
        "what's my wifi password",
    ):
        assert f'data-send="{example}"' in html
    # Chips disappear once the conversation starts.
    assert "body.talked #chips { display: none; }" in html
    assert 'classList.add("talked")' in html
    assert 'querySelectorAll(".chip")' in html or 'closest(".chip")' in html


def test_app_html_command_palette_has_wave4_quick_entries():
    html = APP_HTML.read_text(encoding="utf-8")
    for entry in (
        'label: "Recap my day"',
        'label: "tick off everything in the bike project"',
        'label: "brief me over de verbouwing"',
        'label: "what\'s my wifi password"',
        'label: "try that again"',
    ):
        assert entry in html

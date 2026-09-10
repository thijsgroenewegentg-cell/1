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


def test_suggestions_follow_the_reply_language(brain):
    brain._user_language = "nl"
    dutch = brain.suggestions()
    brain._user_language = "en"
    english = brain.suggestions()
    assert len(dutch) == len(english) == 5
    assert any("vandaag" in line for line in dutch)
    assert any("wifi-wachtwoord" in line for line in dutch)
    assert any("Recap my day" in line for line in english)
    assert any("wifi password" in line for line in english)
    assert dutch != english


def test_status_endpoint_publishes_suggestions():
    """The console reads the chip list off /api/status."""
    web_py = (ROOT / "interfaces" / "web.py").read_text(encoding="utf-8")
    assert '"suggestions": self.brain.suggestions()' in web_py


def test_app_html_renders_language_aware_chips():
    html = APP_HTML.read_text(encoding="utf-8")
    # The container starts empty; JS fills it from /api/status.
    assert '<div id="chips" aria-label="Try asking"></div>' in html
    assert "function renderChips(" in html
    assert "renderChips(data.suggestions)" in html
    # A bilingual fallback shows before (or without) a status answer.
    assert "DEFAULT_CHIPS" in html
    assert "renderChips(null)" in html
    for example in (
        "Recap my day",
        "Wat heb ik vandaag gedaan",
        "vink alles af in het fietsproject",
        "brief me over de verbouwing",
        "what's my wifi password",
    ):
        assert f'"{example}"' in html
    # Chips disappear once the conversation starts.
    assert "body.talked #chips { display: none; }" in html
    assert 'classList.add("talked")' in html
    assert 'closest(".chip")' in html


def test_app_html_reveals_one_shot_replies():
    """Deterministic answers type themselves out; esc completes the reveal."""
    html = APP_HTML.read_text(encoding="utf-8")
    assert "function reveal(" in html
    assert "function finishReveal(" in html
    assert "tokenSeen = true;" in html
    assert "else reveal(replyText);" in html
    assert "if (revealTimer) { finishReveal(); return; }" in html


def test_app_html_keeps_a_mobile_transcript():
    """Narrow screens get a scrollable rail instead of none at all."""
    html = APP_HTML.read_text(encoding="utf-8")
    assert "#rail { display: none; }" not in html
    assert "#rail .line { text-align: left;" in html
    assert "overflow-y: auto; scrollbar-width: thin;" in html


def test_app_html_renders_lists_and_links():
    html = APP_HTML.read_text(encoding="utf-8")
    assert "function inlineMd(" in html
    assert 'rel="noopener noreferrer"' in html
    assert "#caption ul, #caption ol" in html


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

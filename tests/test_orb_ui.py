# /tests/test_orb_ui.py
"""The reactive sphere: honest states and robust geometry.

Four properties of the orb are pinned here:

1. Its vertical band is measured from the live dock element instead of
   hand-synced percentage constants (which drift whenever the dock CSS or
   its content — chips, typing bar — changes).
2. The red "speaking" state also fires on the deterministic path: the
   typewriter reveal and TTS playback carry it, not only token streams.
3. Without a language model the sphere rests in a dimmer "degraded"
   temperature, matching what the degraded banner reports.
4. prefers-reduced-motion calms the spin, shake and noise swell.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_HTML = ROOT / "interfaces" / "app.html"


def html() -> str:
    return APP_HTML.read_text(encoding="utf-8")


def test_orb_band_is_measured_from_the_live_dock():
    page = html()
    assert '$("dock").getBoundingClientRect()' in page
    # The hand-synced constants that used to drift from the CSS are gone.
    assert "dockCentre" not in page
    assert "DOCK_HEIGHT" not in page


def test_orb_speaks_on_the_deterministic_path():
    page = html()
    assert "function voiceMood(" in page
    # The reveal puts the sphere in the speaking colour…
    assert 'mood("speak", 0.4);' in page
    assert "JARVIS is delivering his answer" in page
    # …and both voice engines report their play state into the mood.
    assert 'audio.addEventListener("play", () => voiceMood(true));' in page
    assert 'audio.addEventListener("ended", () => voiceMood(false));' in page
    assert "line.onstart = () => { started = true; voiceMood(true); };" in page
    assert "line.onend = () => voiceMood(false);" in page


def test_orb_rests_honestly_when_degraded():
    page = html()
    assert "degraded: [156, 159, 166]," in page
    assert "function restMood()" in page
    assert "degradedMode = !llmOnline;" in page
    # Resting call sites go through the capability-aware helper.
    assert 'mood("idle", 0)' not in page
    assert page.count("restMood()") >= 6


def test_reduced_motion_calms_the_sphere():
    page = html()
    assert 'const shakeX = CALM ? 0 : Math.sin(orb.time * 97.3) * shakeAmp;' in page
    assert "(CALM ? 0.0005 : 0.0022)" in page
    assert "(CALM ? NOISE_AMOUNT * 0.55 : NOISE_AMOUNT)" in page

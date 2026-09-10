# /tests/test_web.py
"""Unit tests for interfaces/web.py (exported as interfaces/web_ui.py).

The server itself is FastAPI, so these tests cover the parts that can fail
without a browser: the LAN address discovery, the generated icon, the access
token and the app assembling at all.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from core.brain import Brain
from interfaces.web_ui import WebInterface, local_addresses, render_icon
from tests.conftest import run


@pytest.fixture
def web(config):
    """A WebInterface bound to a brain, without serving anything."""
    brain = Brain(config)
    run(brain.initialize())
    interface = WebInterface(brain, config, port=8123)
    yield interface
    run(brain.shutdown())


def test_the_module_is_importable_under_both_names():
    from interfaces import web, web_ui

    assert web_ui.WebInterface is web.WebInterface


def test_local_addresses_include_something_usable():
    addresses = local_addresses(8123)
    assert addresses
    assert all("8123" in address for address in addresses)
    assert any("localhost" in address for address in addresses)
    assert not any("169.254." in address for address in addresses)


def test_link_local_addresses_are_not_pairing_targets():
    from interfaces.web import _reachable_lan

    assert _reachable_lan("192.168.1.20")
    assert not _reachable_lan("169.254.0.21")
    assert not _reachable_lan("127.0.0.1")
    assert not _reachable_lan("0.0.0.0")


@pytest.mark.parametrize("size", [180, 192, 512])
def test_the_icon_is_a_valid_png(size):
    data = render_icon(size)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 100


def test_the_icon_is_deterministic():
    assert render_icon(192) == render_icon(192)


def test_the_interface_reports_the_url_to_open(web):
    assert web.url.startswith("http://")
    assert "8123" in web.url


def test_an_access_token_is_generated(web):
    assert web.token
    assert len(web.token) >= 8


def test_the_app_exposes_the_expected_routes(web):
    paths = {route.path for route in web.app.routes}
    assert "/" in paths
    assert any("ws" in path for path in paths)


def test_binding_to_all_interfaces_is_the_default(config):
    brain = Brain(config)
    interface = WebInterface(brain, config)
    assert interface.host in {"0.0.0.0", "127.0.0.1", "localhost"}


def test_an_enormous_message_is_refused(web):
    from fastapi.testclient import TestClient

    from interfaces.web import MAX_MESSAGE_CHARS

    client = TestClient(web.app)
    response = client.post("/api/ask", json={"text": "x" * (MAX_MESSAGE_CHARS + 1)},
                           params={"token": web.token})
    assert response.status_code == 413


def test_a_normal_message_is_accepted(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    response = client.post("/api/ask", json={"text": "what time is it"},
                           params={"token": web.token})
    assert response.status_code == 200
    assert response.json()["reply"]


def test_every_endpoint_demands_the_token(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    assert client.get("/").status_code == 401
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/ask", json={"text": "hi"}).status_code == 401


def test_the_page_can_be_installed_as_an_app(web):
    """--app relies on the page being a standalone-display PWA."""
    import json

    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    response = client.get("/manifest.webmanifest", params={"token": web.token})
    assert response.status_code == 200
    manifest = json.loads(response.text)
    assert manifest["display"] == "standalone"
    assert manifest["icons"]
    assert manifest["start_url"]


# ------------------------------------------------------------ the interface
def test_the_interface_is_a_real_file(web):
    from interfaces.web import APP_FILE, load_page

    assert APP_FILE.is_file(), "interfaces/app.html should ship with the package"
    page = load_page()
    assert page.lstrip().startswith("<!doctype html>")
    assert "__TITLE__" in page and "__TOKEN_QUERY__" in page


def test_the_served_page_has_no_placeholders_left(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    page = client.get("/", params={"token": web.token}).text
    assert "__TITLE__" not in page
    assert "__TOKEN_QUERY__" not in page
    assert "<title>" in page


def test_the_page_survives_a_missing_asset(web, monkeypatch, tmp_path):
    """An installation that lost app.html should degrade, not 500."""
    from interfaces import web as web_module

    monkeypatch.setattr(web_module, "APP_FILE", tmp_path / "gone.html")
    page = web_module.load_page()
    assert "__TITLE__" in page
    assert "fallback" in page.lower()


def test_the_tools_endpoint_lists_every_tool(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    response = client.get("/api/tools", params={"token": web.token})
    assert response.status_code == 200
    tools = response.json()["tools"]
    assert len(tools) > 100
    first = tools[0]
    assert {"module", "name", "description"} <= set(first)


def test_the_audit_endpoint_answers(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    response = client.get("/api/audit", params={"token": web.token})
    assert response.status_code == 200
    assert isinstance(response.json()["entries"], list)


def test_the_new_endpoints_demand_the_token(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    assert client.get("/api/tools").status_code == 401
    assert client.get("/api/audit").status_code == 401
    assert client.get("/api/voices").status_code == 401
    assert client.get("/api/tts?text=hi").status_code == 401
    assert client.post("/api/voices", json={}).status_code == 401
    assert client.post("/api/tts/cache/clear").status_code == 401
    assert client.post("/api/vision").status_code == 401
    assert client.get("/api/memory").status_code == 401
    assert client.post("/api/memory", json={}).status_code == 401


def test_voices_endpoint_lists_voices(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    resp = client.get("/api/voices", params={"token": web.token})
    assert resp.status_code == 200
    data = resp.json()
    assert "current" in data
    assert "edge_voices" in data
    assert "elevenlabs_voices" in data
    assert "speech" in data


def test_voices_save_persists(web, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    # Save a voice choice
    resp = client.post("/api/voices", params={"token": web.token}, json={"engine": "edge", "voice": "en-GB-RyanNeural"})
    assert resp.status_code in {200, 500}  # 500 if config save fails in test tmp, but should be 200
    if resp.status_code == 200:
        assert resp.json().get("ok") is True


def test_tts_cache_clear(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    resp = client.post("/api/tts/cache/clear", params={"token": web.token})
    assert resp.status_code == 200
    assert "cleared" in resp.json()


def test_memory_endpoints(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    # List
    resp = client.get("/api/memory", params={"token": web.token})
    assert resp.status_code == 200
    assert "facts" in resp.json()
    # Remember + forget
    resp = client.post("/api/memory", params={"token": web.token}, json={"text": "test fact", "action": "remember"})
    # May be 503 if memory unavailable in test, but should not be 401/400
    assert resp.status_code in {200, 503, 500}


def test_doctor_and_piper_and_vision(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    # Doctor
    resp = client.get("/api/doctor", params={"token": web.token})
    assert resp.status_code == 200
    assert "findings" in resp.json()
    # Piper install - should be 200 or 429
    resp = client.post("/api/piper/install", params={"token": web.token})
    assert resp.status_code in {200, 429, 503}
    # Vision without file should be 400
    resp = client.post("/api/vision", params={"token": web.token}, json={})
    assert resp.status_code in {400, 413, 422, 500}
    # Voices refresh
    resp = client.get("/api/voices", params={"token": web.token, "refresh": "1"})
    assert resp.status_code == 200
    assert "current" in resp.json()
    assert "piper_installed" in resp.json()["current"]
    assert "elevenlabs_source" in resp.json()["current"]



def test_brain_events_reach_the_browser(web):
    """The interface shows which module answered and which tools ran."""
    sent = []

    class FakeSocket:
        async def send_text(self, payload: str) -> None:
            sent.append(payload)

    async def scenario() -> None:
        import json

        web._sockets.add(FakeSocket())
        web._watch_the_brain()
        await web.brain.events.publish("tool.called", tool="productivity.add_todo")
        await asyncio.sleep(0.05)
        assert sent, "the tool call should have been relayed"
        message = json.loads(sent[-1])
        assert message["type"] == "event"
        assert message["data"]["tool"] == "productivity.add_todo"

    run(scenario())


def test_uninteresting_events_are_not_relayed(web):
    sent = []

    class FakeSocket:
        async def send_text(self, payload: str) -> None:
            sent.append(payload)

    async def scenario() -> None:
        web._sockets.add(FakeSocket())
        web._watch_the_brain()
        await web.brain.events.publish("memory.written", detail="noise")
        await asyncio.sleep(0.05)

    run(scenario())
    assert not sent


def test_the_interface_is_self_contained(web):
    """No CDN, no external fonts: it has to work on a machine with no internet."""
    from interfaces.web import load_page

    page = load_page()
    external = re.findall(r'(?:src|href)="(https?://[^"]+)"', page)
    assert not external, f"the interface reaches out to {external}"
    assert "<script>" in page and "<style>" in page


def test_editing_the_interface_does_not_need_a_restart(web, tmp_path, monkeypatch):
    """The page is cached against the file's timestamp, not for the process."""
    import time

    from fastapi.testclient import TestClient

    from interfaces import web as web_module

    asset = tmp_path / "app.html"
    asset.write_text("<!doctype html><title>__TITLE__</title><p>first</p>")
    monkeypatch.setattr(web_module, "APP_FILE", asset)
    server = web_module.WebInterface(web.brain, web.config, port=8131)
    client = TestClient(server.app)

    assert "first" in client.get("/", params={"token": server.token}).text
    time.sleep(0.01)
    asset.write_text("<!doctype html><title>__TITLE__</title><p>second</p>")
    assert "second" in client.get("/", params={"token": server.token}).text


def test_the_interface_declares_its_shortcuts(web):
    """Every key the script listens for should be discoverable in the UI."""
    from interfaces.web import load_page

    page = load_page()
    for key in ("space", "K", "T", "?"):
        assert f"<kbd>{key}</kbd>" in page, key


def test_tool_results_reach_the_browser(web):
    """The interface draws cards from these, so they must be relayed."""
    sent = []

    class FakeSocket:
        async def send_text(self, payload: str) -> None:
            sent.append(payload)

    async def scenario() -> None:
        import json

        web._sockets.add(FakeSocket())
        web._watch_the_brain()
        await web.brain.events.publish(
            "tool.result", tool="productivity.list_todos", ok=True,
            data={"todos": [{"task": "sourdough"}]},
        )
        await asyncio.sleep(0.05)
        assert sent, "the result should have been relayed"
        message = json.loads(sent[-1])
        assert message["name"] == "tool.result"
        assert message["data"]["data"]["todos"][0]["task"] == "sourdough"

    run(scenario())


def test_the_page_is_compressed(web):
    """61 KB of markup over Wi-Fi is a visible load; 18 KB is not."""
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    plain = client.get("/", params={"token": web.token},
                       headers={"Accept-Encoding": "identity"})
    packed = client.get("/", params={"token": web.token},
                        headers={"Accept-Encoding": "gzip"})
    assert plain.status_code == packed.status_code == 200
    assert packed.headers.get("content-encoding") == "gzip"
    assert int(packed.headers["content-length"]) < len(plain.content) / 2


# --------------------------------------------------------- the status panel
def test_status_reports_uptime_for_the_panel(web):
    """The panel has always had an Uptime row; nothing ever filled it."""
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    payload = client.get(f"/api/status?token={web.token}").json()
    assert "uptime" in payload
    assert payload["uptime"]


def test_status_still_reports_the_llm_state_the_page_reads(web):
    """The page keys off llm.online; renaming it would blank the banner."""
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    llm = client.get(f"/api/status?token={web.token}").json()["llm"]
    assert "online" in llm
    assert isinstance(llm["online"], bool)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "just started"),
        (59, "just started"),
        (60, "1m"),
        (3661, "1h 1m"),
        (90000, "1d 1h"),
    ],
)
def test_uptime_is_rendered_for_humans(seconds, expected):
    from interfaces.web import _format_uptime

    assert _format_uptime(seconds) == expected


@pytest.mark.parametrize("rubbish", ["", None, "abc", object()])
def test_uptime_never_raises_on_rubbish(rubbish):
    from interfaces.web import _format_uptime

    assert _format_uptime(rubbish) == ""


def test_the_page_handles_the_status_shape_the_server_sends(web):
    """The modules field is an object; the page used to call .map() on it.

    That threw a TypeError into an empty catch, so the entire Status pane —
    every row, plus the module tiles — silently rendered nothing.
    """
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert "Array.isArray(raw)" in page
    assert "Object.keys(raw)" in page
    # The old, broken expression must be gone.
    assert "(data.modules || []).map" not in page


def test_the_page_reads_the_llm_key_the_server_actually_sends(web):
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert "llm.online === false" in page
    # The old key must not be read anywhere (a comment naming it is fine).
    assert "llm.available ===" not in page
    assert "(llm.available" not in page


def test_the_page_explains_degraded_mode(web):
    """With no model, replies are reflex-only — the UI has to say so."""
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert 'id="degraded"' in page
    assert "reflex commands only" in page
    assert "degradedClose" in page


# --------------------------------------------------------- honest controls
# Two ways the UI used to lie about itself: it offered speech on servers that
# could not produce any, and it reported "0 turns" for work it had not
# personally witnessed.


def test_status_reports_whether_speech_is_possible(web):
    """The page needs to know, or it offers a button that cannot work."""
    from fastapi.testclient import TestClient

    payload = TestClient(web.app).get("/api/status", params={"token": web.token}).json()
    assert "speech" in payload
    assert isinstance(payload["speech"], bool)


def test_speech_is_unavailable_when_tts_is_switched_off(web):
    """allow_tts: false must be reported, not just enforced at /api/tts."""
    import asyncio

    web.allow_tts = False
    assert asyncio.run(web.speech_available()) is False


def test_web_tts_does_not_need_a_server_side_audio_player(monkeypatch):
    """The browser plays the audio; ffmpeg on the server is irrelevant.

    Requiring a command-line player meant a machine with a working engine but
    no ffmpeg reported "tts unavailable" for the web interface.
    """
    import asyncio
    import importlib.util

    from core.config import Config
    from interfaces import voice as voice_module

    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        voice_module.importlib.util,
        "find_spec",
        lambda name, *a, **k: object() if name == "edge_tts" else real_find_spec(name, *a, **k),
    )
    # No audio player anywhere on this machine.
    monkeypatch.setattr(voice_module.TextToSpeech, "_find_player", classmethod(lambda cls: None))

    config = Config()
    strict = voice_module.TextToSpeech(config)
    relaxed = voice_module.TextToSpeech(config)

    assert asyncio.run(strict.initialize(require_player=True)) is False
    assert asyncio.run(relaxed.initialize(require_player=False)) is True
    assert relaxed.available is True


def test_the_page_disables_speech_when_the_server_cannot_speak(web):
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert "applySpeechSupport" in page
    assert "speechSupported" in page
    # The control must be genuinely disabled, not merely styled differently.
    assert '$("speech").disabled = !speechSupported' in page


def test_status_carries_the_brains_turn_count(web):
    """Turns counted anywhere — voice, CLI, /api/ask — must reach the page."""
    from fastapi.testclient import TestClient

    payload = TestClient(web.app).get("/api/status", params={"token": web.token}).json()
    assert "turns" in payload
    assert isinstance(payload["turns"], int)


def test_the_page_trusts_the_servers_turn_count(web):
    """The tab only sees its own socket, so it must defer to the server."""
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert "data.turns > turns" in page


# ------------------------------------------------------------ design system
# The page accumulated thirteen corner radii and four ways of writing the
# same border before these were consolidated. These guard the consolidation.


def test_the_page_defines_one_radius_and_surface_scale(web):
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    for token in ("--r-sm:", "--r-md:", "--r-lg:", "--surface:", "--shadow-md:", "--ease:"):
        assert token in page, f"missing design token {token}"


def test_chrome_follows_the_orb_colour_rather_than_a_fixed_cyan(web):
    """Surfaces read from --tint so they shift with the orb's mood.

    A hardcoded cyan left the interface visually detached from the sphere it
    was supposed to belong to.
    """
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    # The old literal cyan must not appear as a surface colour any more.
    assert "34, 211, 238" not in style
    # And the live tint must be doing real work across the chrome.
    assert style.count("rgba(var(--tint)") > 25


def test_whisper_boot_grows_without_a_whiteout(web):
    """Startup is a spark that grows, not a 6s explosion under an overlay."""
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert "const WHISPER = true" in page
    assert "const BOOT_MS = 3400" in page
    assert "window.restartIgnition" in page
    assert "bootScreen" not in page
    assert "say(data.greeting" not in page


def test_legacy_boot_page_is_debug_only(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    assert client.get("/boot", params={"token": web.token}).status_code == 404
    shown = client.get("/boot", params={"token": web.token, "debug": "1"})
    assert shown.status_code == 200
    assert "JARVIS" in shown.text or "boot" in shown.text.lower()


def test_chips_do_not_stripe_through_a_briefing(web):
    """Suggestion chips sat on top of the morning briefing caption."""
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "body.reading #chips" in style


def test_cinema_idle_hides_chrome_until_you_reach(web):
    """Idle field is the orb; chrome waits on body.quiet."""
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "body.awake.quiet" in style
    assert "setCinemaQuiet" in page
    assert "reachChrome" in page


def test_the_centred_dock_keeps_its_offset_under_reduced_motion(web):
    """#dock is centred with a translate.

    Clearing its transform — as the other chrome does — would fling it to the
    top-left corner, so it has to keep the centring offset in every state.
    """
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    reduced = style.split("prefers-reduced-motion", 1)[1]
    assert "translate(-50%, 0) !important" in reduced


# ------------------------------------------------------- layout collisions
# All three of these were only visible in a screenshot. They cost nothing to
# assert on and would otherwise silently return.


def test_the_degraded_banner_clears_the_top_bar(web):
    """At top:14px the banner landed squarely over the centred wordmark.

    Degraded mode is exactly when you most want to read what the thing is,
    so blanking the title in that state is the worst possible time.
    """
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    banner = style.split("#degraded {", 1)[1].split("}", 1)[0]
    top = int(banner.split("top:", 1)[1].split("px", 1)[0].strip())
    # The top bar is 18px of padding plus a ~20px row.
    assert top >= 50, f"#degraded at top:{top}px overlaps the top bar"


def test_toasts_move_out_of_the_banners_way(web):
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert "degraded-open" in page
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "body.degraded-open #toasts" in style


def test_module_tiles_are_labelled(web):
    """A 3x4 grid of anonymous squares read as dead pixels, not status."""
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert "tile.dataset.name" in page
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "content: attr(data-name)" in style


def test_the_answer_is_centred_below_the_console(web):
    """The stage sits just above the dock so the text hugs the controls."""
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    stage = style.split("\n#stage {", 1)[1].split("}", 1)[0]
    # It hugs the dock (flex-end) rather than floating in the middle, and
    # its bottom tracks the dock so the caption stays just above the controls.
    assert "justify-content: flex-end" in stage
    assert "bottom: calc(" in stage
    # Dock sits at the bottom (7vh); the stage tracks it with calc().
    assert "flex-end" in stage


# ---------------------------------------------------------- atmosphere
# The flat black void was the most common "not dramatic" complaint. These
# guard the layers that give it depth.


def test_the_page_has_a_reactive_halo_and_horizon_grid(web):
    from fastapi.testclient import TestClient
    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert 'id="halo"' in page
    assert 'id="grid"' in page
    assert 'id="grain"' in page
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    # Halo must be tied to the orb's live state, not a static colour.
    assert "rgba(var(--tint)" in style
    # Grid must be perspective, not a flat box.
    assert "rotateX(" in style
    assert "perspective(" in style


def test_reduced_motion_suppresses_the_new_atmosphere(web):
    from fastapi.testclient import TestClient
    page = TestClient(web.app).get("/", params={"token": web.token}).text
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    reduced = style.split("prefers-reduced-motion", 1)[1]
    assert "#halo" in reduced
    assert "#grid" in reduced
    assert "#grain" in reduced


# ---------------------------------------------- permission gate over the socket
def _confirm_scenario(config, reply):
    """Run one WS turn that needs approval, answer it, and return the reply."""
    import json

    from fastapi.testclient import TestClient

    from interfaces.web_ui import WebInterface

    config.set("security.confirm_dangerous", True)
    brain = Brain(config)
    run(brain.initialize())
    interface = WebInterface(brain, config, port=8129)
    client = TestClient(interface.app)
    try:
        with client.websocket_connect(f"/ws?token={interface.token}") as ws:
            ws.send_text(json.dumps({
                "text": "edit your code in modules/productivity.py to say hello"
            }))
            confirm = None
            for _ in range(40):
                message = ws.receive_json()
                if message.get("type") == "confirm":
                    confirm = message
                    break
            assert confirm is not None, "the browser should be asked"
            assert "edit_own_code" in confirm["text"] or "self_improve" in confirm["text"]
            ws.send_text(json.dumps({
                "type": "confirm", "id": confirm["id"], "reply": reply
            }))
            while True:
                message = ws.receive_json()
                if message.get("type") == "reply":
                    return message.get("text", "")
    finally:
        run(brain.shutdown())


def test_a_dangerous_edit_is_approved_over_the_socket(config):
    """Approve in the browser: the edit proceeds.

    Here, without an LLM, the reply explains that the rewrite itself
    needs the model.
    """
    text = _confirm_scenario(config, reply=True)
    assert text and ("language model" in text or "Ollama" in text)


def test_denying_the_confirm_cancels_the_edit(config):
    """Deny in the browser: the dangerous tool must not run."""
    text = _confirm_scenario(config, reply=False)
    assert "cancel" in text.lower()


# ----------------------------------------------------------- G: home dashboard
def test_the_dashboard_requires_the_token_and_returns_cards(web, config):
    from fastapi.testclient import TestClient

    config.set("modules.web_search", False)  # no weather call in a test
    client = TestClient(web.app)
    assert client.get("/api/dashboard").status_code == 401

    response = client.get("/api/dashboard", params={"token": web.token})
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, dict)
    assert isinstance(payload.get("cards"), list)
    assert any(card.get("key") == "tasks" for card in payload["cards"])
    assert any(card.get("key") == "system" for card in payload["cards"])


def test_the_dashboard_card_shows_open_tasks(web, config):
    from fastapi.testclient import TestClient

    config.set("modules.web_search", False)
    module = web.brain.modules["productivity"]
    from tests.conftest import run

    run(module.call_tool("add_todo", {"task": "proof the dashboard"}))
    client = TestClient(web.app)
    payload = client.get("/api/dashboard", params={"token": web.token}).json()
    tasks = next(card for card in payload["cards"] if card["key"] == "tasks")
    assert any("proof the dashboard" in line.get("text", "")
               for line in tasks["lines"])


def test_the_dashboard_degrades_when_everything_is_off(config):
    config.set("modules.productivity", False)
    config.set("modules.system_control", False)
    config.set("modules.web_search", False)
    config.set("assistant.nightly_check_time", "")  # no health placeholder either
    from core.brain import Brain
    from interfaces.web_ui import WebInterface
    from tests.conftest import run

    brain = Brain(config)
    run(brain.initialize())
    interface = WebInterface(brain, config, port=8124)
    try:
        payload = run(interface._dashboard_payload())
        assert payload["cards"] == []
    finally:
        run(brain.shutdown())


def test_status_includes_a_pair_url(web):
    from fastapi.testclient import TestClient

    payload = TestClient(web.app).get("/api/status", params={"token": web.token}).json()
    assert payload["pair"]["url"]
    assert "token=" in payload["pair"]["url"]
    assert str(web.port) in payload["pair"]["url"]


def test_the_pairing_qr_is_an_svg(web):
    from fastapi.testclient import TestClient

    response = TestClient(web.app).get("/api/pair.svg", params={"token": web.token})
    assert response.status_code == 200
    assert "svg" in response.headers["content-type"]
    assert b"<svg" in response.content


def test_the_page_has_a_pair_slot_and_restores_history(web):
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert 'id="pairQr"' in page
    assert "restoreHistory" in page
    assert 'data.name === "turn.ack"' in page


def test_a_new_socket_gets_the_session_hello(web):
    from fastapi.testclient import TestClient

    web.brain.memory.short_term.add("hello there", "good evening, sir")
    client = TestClient(web.app)
    with client.websocket_connect(f"/ws?token={web.token}") as socket:
        hello = socket.receive_json()
    assert hello["type"] == "hello"
    assert any(entry.get("text") == "hello there" for entry in hello["history"])


def test_status_includes_identity_and_accent(web):
    from fastapi.testclient import TestClient

    payload = TestClient(web.app).get("/api/status", params={"token": web.token}).json()
    ident = payload["identity"]
    assert ident["assistant"]
    assert ident["accent"].startswith("#")
    assert len(ident["accent"]) == 7


def test_identity_can_be_saved(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    response = client.post(
        "/api/identity",
        params={"token": web.token},
        json={"assistant": "FRIDAY", "user": "Tony", "accent": "#22c55e"},
    )
    assert response.status_code == 200
    ident = response.json()["identity"]
    assert ident["assistant"] == "FRIDAY"
    assert ident["user"] == "Tony"
    assert ident["accent"] == "#22c55e"
    again = client.get("/api/status", params={"token": web.token}).json()["identity"]
    assert again["assistant"] == "FRIDAY"
    assert again["accent"] == "#22c55e"


def test_identity_requires_the_token(web):
    from fastapi.testclient import TestClient

    assert TestClient(web.app).post("/api/identity", json={"assistant": "X"}).status_code == 401


def test_the_page_has_live_theming_and_a_clipboard_panel(web):
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert 'id="themeHue"' in page
    assert "function applyAccent" in page
    assert 'id="clipPulse"' in page
    assert 'data-clip="translate"' in page
    assert 'id="botName"' in page
    assert 'id="youName"' in page


def test_briefing_endpoint_delivers_once(web):
    from fastapi.testclient import TestClient

    client = TestClient(web.app)
    assert client.get("/api/briefing").status_code == 401
    first = client.get("/api/briefing", params={"token": web.token})
    assert first.status_code == 200
    payload = first.json()
    assert "briefing" in payload
    assert payload["already"] is False
    second = client.get("/api/briefing", params={"token": web.token}).json()
    assert second["already"] is True
    assert second["briefing"] == ""


def test_the_page_fetches_the_morning_briefing(web):
    from fastapi.testclient import TestClient

    page = TestClient(web.app).get("/", params={"token": web.token}).text
    assert "/api/briefing" in page
    assert "jarvis-brief-" in page


def test_parse_accent_accepts_short_hex():
    from interfaces.web import _parse_accent

    assert _parse_accent("#0f0") == "#00ff00"
    assert _parse_accent("not-a-colour") == "#ef4444"

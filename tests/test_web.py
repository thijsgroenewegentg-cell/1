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

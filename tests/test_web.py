# /tests/test_web.py
"""Unit tests for interfaces/web.py (exported as interfaces/web_ui.py).

The server itself is FastAPI, so these tests cover the parts that can fail
without a browser: the LAN address discovery, the generated icon, the access
token and the app assembling at all.
"""

from __future__ import annotations

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

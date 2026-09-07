# /tests/test_web_search.py
"""Unit tests for modules/web_search.py.

No test here touches the network. What is exercised is the routing, the
query cleaning, the HTML-to-text extraction and the way failures are
reported when DuckDuckGo or wttr.in cannot be reached.
"""

from __future__ import annotations

import pytest

from modules.web_search import WebSearch
from tests.conftest import run


@pytest.fixture
def web(config):
    """A WebSearch module pointed at nothing in particular."""
    return WebSearch(config)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("search for quantum computing", "search"),
        ("google the best pizza in rome", "search"),
        ("how's the weather", "weather"),
        ("what's the weather in tokyo", "weather"),
        ("what's in the news", "news"),
        ("look up marie curie on wikipedia", "wikipedia"),
    ],
)
def test_offline_router_recognises_search_intents(web, phrase, expected):
    routed = web.offline_router(phrase)
    assert routed is not None, f"{phrase!r} should route without an LLM"
    assert routed[0] == expected


def test_the_weather_router_extracts_the_place(web):
    tool, params = web.offline_router("what's the weather in tokyo")
    assert tool == "weather"
    assert "tokyo" in str(params.get("location", "")).lower()


def test_the_search_router_strips_the_command_words(web):
    tool, params = web.offline_router("search for quantum computing")
    assert tool == "search"
    assert params["query"].strip().lower() == "quantum computing"


def test_an_empty_search_is_refused(web):
    result = run(web.call_tool("search", {"query": ""}))
    assert not result.success


def test_html_is_reduced_to_readable_text(web):
    html = """
    <html><head><title>Test</title><style>p {color: red}</style></head>
    <body><script>alert('no')</script><nav>menu</nav>
    <article><h1>Headline</h1><p>First paragraph.</p><p>Second paragraph.</p></article>
    </body></html>
    """
    text = web._html_to_text(html)
    assert "First paragraph." in text
    assert "alert" not in text
    assert "color: red" not in text


def test_unreachable_services_produce_an_explanation_not_a_crash(web):
    # The config points at a dead host, so this exercises the failure path.
    result = run(web.call_tool("read_page", {"url": "http://127.0.0.1:59999/nothing"}))
    assert not result.success
    assert result.error


def test_a_url_is_required_to_read_a_page(web):
    result = run(web.call_tool("read_page", {"url": ""}))
    assert not result.success


def test_scraped_pages_are_marked_untrusted(web):
    spec = web.tools["read_page"]
    assert spec.untrusted, "web pages must be fenced before the model sees them"


def test_search_results_are_marked_untrusted(web):
    assert web.tools["search"].untrusted


def test_a_network_failure_reads_like_a_sentence(web):
    # The search client pastes the whole tracking URL into its error message.
    import httpx

    message = web._search_failure(
        httpx.ConnectError("error sending request for url (https://search.yahoo.com/"
                           "search;_ylt=5bKEW6yYfZUzyX0iStcvHZIe;_ylu=ce94P8ieBDacCNjY)")
    )
    assert "http" not in message
    assert "internet" in message.lower()


def test_rate_limiting_is_named(web):
    assert "rate-limit" in web._search_failure(RuntimeError("Ratelimit 429")).lower()


def test_an_unexpected_failure_still_says_something(web):
    assert "failed" in web._search_failure(RuntimeError("something odd")).lower()


def test_weather_is_a_registered_tool(web):
    # The @tool decorator once sat on the private _locate_by_ip helper directly
    # above it, so `weather` was never registered and every routed weather
    # request died with "Unknown tool 'weather'".
    assert "weather" in web.tools
    assert "_locate_by_ip" not in web.tools
    assert web.tools["weather"].params.keys() == {"location"}


def test_no_private_helper_is_exposed_as_a_tool(web):
    assert not [name for name in web.tools if name.startswith("_")]

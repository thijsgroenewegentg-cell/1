"""Local web search action.

The original action used a cloud grounded-search API. This version fetches
public DuckDuckGo results and lets the configured Ollama model summarise those
results locally. If Ollama is unavailable, the raw links are still returned.
"""
from __future__ import annotations

import re
from pathlib import Path


def _ddg_client():
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    return DDGS


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    DDGS = _ddg_client()
    results = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            results.append({
                "title": item.get("title", ""),
                "snippet": item.get("body", ""),
                "url": item.get("href", ""),
            })
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    DDGS = _ddg_client()
    results = []
    try:
        with DDGS() as ddgs:
            for item in ddgs.news(query, max_results=max_results):
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("body", ""),
                    "url": item.get("url", ""),
                    "source": item.get("source", ""),
                })
    except Exception as e:
        print(f"[WebSearch] news search failed ({e}); using text search")
        results = _ddg_search(query, max_results)
    return results


def _format_results(query: str, results: list[dict], news: bool = False) -> str:
    if not results:
        return f"No results found for: {query}"
    lines = [f"{'Latest news' if news else 'Search results'} for: {query}", ""]
    for i, item in enumerate(results, 1):
        title = item.get("title", "")
        source = f" [{item['source']}]" if item.get("source") else ""
        if title:
            lines.append(f"{i}. {title}{source}")
        if item.get("snippet"):
            lines.append(f"   {item['snippet'][:500]}")
        if item.get("url"):
            lines.append(f"   Source: {item['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _summarize_locally(question: str, source_text: str) -> str:
    """Use Ollama for synthesis, but retain source text if it cannot be reached."""
    try:
        from core.llm_client import call_llm_text
        return call_llm_text(
            f"Answer the user's question using ONLY the web results below. "
            f"Mention uncertainty and include useful source URLs when relevant. "
            f"Be concise.\n\nUser question: {question}\n\nWeb results:\n{source_text[:16000]}",
            system="You are a careful local research assistant. Do not invent facts that are not supported by the supplied results.",
            num_predict=700,
            timeout=240,
        ) or source_text
    except Exception as e:
        print(f"[WebSearch] Local synthesis unavailable: {e}")
        return source_text


def _search(query: str) -> str:
    results = _ddg_search(query)
    raw = _format_results(query, results)
    return _summarize_locally(query, raw)


def _news(query: str) -> str:
    query = query or "world news today"
    results = _ddg_news(query)
    raw = _format_results(query, results, news=True)
    return _summarize_locally(f"Give me the latest news about {query}", raw)


def _research(query: str) -> str:
    results = _ddg_search(query, max_results=10)
    raw = _format_results(query, results)
    return _summarize_locally(
        f"Research {query} comprehensively: background, key facts and current status.", raw
    )


def _price(query: str) -> str:
    results = _ddg_search(f"{query} current price buy", max_results=8)
    raw = _format_results(query, results)
    return _summarize_locally(f"What are the current prices and buying options for {query}?", raw)


def _compare(items: list[str], aspect: str) -> str:
    query = f"Compare {', '.join(items)} regarding {aspect}"
    results = []
    for item in items:
        try:
            results.extend(_ddg_search(f"{item} {aspect}", max_results=3))
        except Exception as e:
            print(f"[WebSearch] comparison lookup failed for {item}: {e}")
    raw = _format_results(query, results)
    return _summarize_locally(query, raw)


def web_search(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    query = str(params.get("query", "")).strip()
    mode = str(params.get("mode", "search")).lower().strip()
    items = params.get("items", []) or []
    aspect = str(params.get("aspect", "general")).strip() or "general"

    if not query and not items:
        return "Please provide a search query."
    if items and mode != "compare":
        mode = "compare"
    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")
    try:
        if mode == "compare" and items:
            return _compare([str(x) for x in items], aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        return _search(query)
    except Exception as e:
        print(f"[WebSearch] search failed: {e}")
        return f"Search failed: {e}"


TOOL = {
    "name": "web_search",
    "description": (
        "Search the web for current facts, events, prices, research or news. "
        "Results are fetched from DuckDuckGo and summarised locally. Modes: "
        "search, news, research, price and compare."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {"type": "STRING", "description": "Search query or topic"},
            "mode": {"type": "STRING", "description": "search | news | research | price | compare"},
            "items": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items for compare mode"},
            "aspect": {"type": "STRING", "description": "Comparison aspect: price, specs, reviews or features"},
        },
        "required": ["query"],
    },
    "handler": web_search,
}

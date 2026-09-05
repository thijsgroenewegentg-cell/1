# /modules/web_search.py
"""Internet research with zero API keys.

* DuckDuckGo for search (``duckduckgo_search`` / ``ddgs``, no key)
* requests/httpx + BeautifulSoup for scraping and summarising pages
* wttr.in for weather (free, no key)
* Public RSS feeds for news
* Wikipedia's open REST API for encyclopaedic summaries
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import clean_text, run_blocking, truncate


class WebSearch(BaseModule):
    """Search, scrape, weather, news and Wikipedia — all free."""

    name = "web_search"
    description = (
        "Research the internet: DuckDuckGo web search, reading and summarising web pages, "
        "current weather, latest news headlines and Wikipedia summaries."
    )
    intent_examples = [
        "search for quantum computing breakthroughs",
        "how's the weather",
        "what's in the news today",
        "look up the Roman Empire on Wikipedia",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Read the ``web`` configuration section."""
        super().__init__(config, llm=llm, security=security)
        self.max_results = int(config.get("web.max_results", 5))
        self.timeout = float(config.get("web.timeout", 20))
        self.scrape_chars = int(config.get("web.scrape_chars", 6000))
        self.user_agent = str(config.get("web.user_agent", "Mozilla/5.0"))
        self.feeds: List[str] = list(config.get("web.news_feeds", []) or [])
        self.units = str(config.get("user.units", "metric"))
        self.default_location = str(config.get("user.location", "auto"))

    # ------------------------------------------------------------- internals
    async def _get(self, url: str, **kwargs: Any) -> Optional[Any]:
        """HTTP GET with a browser-ish user agent. Returns the response or None."""
        try:
            import httpx

            headers = {"User-Agent": self.user_agent, "Accept-Language": "en"}
            headers.update(kwargs.pop("headers", {}))
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=True, headers=headers
            ) as client:
                response = await client.get(url, **kwargs)
                response.raise_for_status()
                return response
        except Exception as exc:
            self.log.debug("GET %s failed: %s", url, exc)
            return None

    @staticmethod
    def _ddgs_class() -> Optional[Any]:
        """Import the DuckDuckGo client, supporting both package names.

        The library was renamed from ``duckduckgo_search`` to ``ddgs``; try the
        current name first and fall back to the legacy one.
        """
        try:
            from ddgs import DDGS  # type: ignore

            return DDGS
        except Exception:
            pass
        try:
            from duckduckgo_search import DDGS  # type: ignore

            return DDGS
        except Exception:
            return None

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing with parameter extraction (used without an LLM)."""
        text = strip_command_prefix(command)
        lowered = text.lower()

        if any(word in lowered for word in ("weather", "forecast", "raining", "temperature outside",
                                            "how hot", "how cold")):
            place = re.search(r"\b(?:in|for|at)\s+([A-Za-z\s'-]{2,40})$", text.strip(" ?"))
            return "weather", {"location": place.group(1).strip() if place else ""}

        if any(word in lowered for word in ("news", "headlines", "what's happening",
                                            "current events", "top stories")):
            topic = re.search(r"(?:news|headlines)\s+(?:about|on|for)\s+(.+)", lowered)
            return "news", {"topic": topic.group(1).strip(" ?") if topic else ""}

        url = re.search(r"(https?://\S+)", text)
        if url:
            return "read_page", {"url": url.group(1)}

        if "wikipedia" in lowered:
            topic = re.sub(r".*wikipedia\s*(?:page\s*)?(?:for|on|about)?\s*", "", lowered).strip(" ?")
            return "wikipedia", {"topic": topic or text}

        if lowered.startswith(("who is", "who was", "what is the", "tell me about")):
            topic = re.sub(r"^(who is|who was|what is the|tell me about)\s+", "", lowered).strip(" ?")
            if topic:
                return "wikipedia", {"topic": topic}

        if any(phrase in lowered for phrase in ("where is", "address of", "location of")):
            place = re.sub(r".*(where is|address of|location of)\s*", "", lowered).strip(" ?")
            return "find_place", {"query": place or text}

        query = re.sub(
            r"^(search(?:\s+the\s+web)?(?:\s+for)?|google|look up|find(?:\s+online)?|"
            r"duckduckgo)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" ?")
        return "search", {"query": query or text}

    # ---------------------------------------------------------------- search
    @tool(
        description="Search the web with DuckDuckGo and return the top results.",
        params={
            "query": {"type": "string", "description": "Search query", "required": True},
            "max_results": {"type": "integer", "description": "How many results", "default": 5},
        },
        keywords=["search", "google", "look up", "find online", "web search", "duckduckgo"],
        examples=['search(query="quantum computing 2026")'],
    )
    async def search(self, query: str, max_results: int = 0) -> ModuleResult:
        """Run a DuckDuckGo text search.

        Args:
            query: What to search for.
            max_results: Result count (defaults to ``web.max_results``).

        Returns:
            A :class:`ModuleResult` whose ``data['results']`` holds the hits.
        """
        query = (query or "").strip()
        if not query:
            return ModuleResult.fail("What should I search for, sir?")
        limit = int(max_results) or self.max_results

        ddgs_class = self._ddgs_class()
        if ddgs_class is None:
            return ModuleResult.fail(
                "The DuckDuckGo client isn't installed — run: pip install ddgs"
            )

        def _search() -> List[Dict[str, str]]:
            rows: List[Dict[str, str]] = []
            with ddgs_class() as ddgs:
                for entry in ddgs.text(query, max_results=limit) or []:
                    rows.append(
                        {
                            "title": clean_text(entry.get("title", "")),
                            "url": entry.get("href") or entry.get("url", ""),
                            "snippet": clean_text(entry.get("body") or entry.get("snippet", "")),
                        }
                    )
            return rows

        try:
            results = await run_blocking(_search)
        except Exception as exc:
            return ModuleResult.fail(f"Search failed: {truncate(str(exc), 200)}")

        if not results:
            return ModuleResult.ok(f"No results for '{query}'.", results=[])

        lines = [
            f"{index}. {row['title']}\n   {truncate(row['snippet'], 220)}\n   {row['url']}"
            for index, row in enumerate(results, 1)
        ]
        return ModuleResult(
            success=True,
            output=f"Top results for '{query}':\n" + "\n".join(lines),
            data={"results": results, "query": query},
        )

    @tool(
        description="Search the web and return a short synthesised answer with sources.",
        params={"query": {"type": "string", "description": "Question", "required": True}},
        keywords=["what is the latest", "research", "find out about", "tell me about the news on"],
    )
    async def research(self, query: str) -> ModuleResult:
        """Search, read the top pages and summarise them with the local LLM."""
        search_result = await self.search(query, max_results=self.max_results)
        if not search_result.success:
            return search_result
        results: List[Dict[str, str]] = search_result.data.get("results", [])
        if not results:
            return ModuleResult.ok(f"Nothing turned up for '{query}'.")

        corpus: List[str] = []
        for row in results[:3]:
            page = await self._fetch_text(row["url"])
            snippet = page or row["snippet"]
            corpus.append(f"SOURCE: {row['title']} ({row['url']})\n{truncate(snippet, 2200)}")

        joined = "\n\n".join(corpus)
        if self.llm is None or not getattr(self.llm, "available", False):
            return ModuleResult(
                success=True,
                output=truncate(joined, 3000),
                data={"results": results, "sources": [row["url"] for row in results[:3]]},
            )

        summary = await self.llm.complete(
            f"Question: {query}\n\nSource material:\n{joined}\n\n"
            "Answer the question in 3-5 sentences using only the sources. "
            "Mention the single most relevant source domain. If the sources don't answer it, "
            "say so.",
            temperature=0.3,
            max_tokens=450,
        )
        return ModuleResult(
            success=True,
            output=summary.strip() or truncate(joined, 2000),
            data={"sources": [row["url"] for row in results[:3]], "query": query},
        )

    # ---------------------------------------------------------------- scrape
    async def _fetch_text(self, url: str) -> str:
        """Download a page and return its readable text."""
        response = await self._get(url)
        if response is None:
            return ""
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type and "xml" not in content_type:
            if "text" in content_type:
                return clean_text(response.text)[: self.scrape_chars]
            return ""
        return self._html_to_text(response.text)[: self.scrape_chars]

    def _html_to_text(self, markup: str) -> str:
        """Strip a page down to readable prose."""
        try:
            from bs4 import BeautifulSoup

            try:
                soup = BeautifulSoup(markup, "lxml")
            except Exception:
                soup = BeautifulSoup(markup, "html.parser")
            for tag in soup(
                ["script", "style", "noscript", "nav", "footer", "header", "aside", "form",
                 "iframe", "svg"]
            ):
                tag.decompose()
            main = soup.find("article") or soup.find("main") or soup.body or soup
            text = main.get_text("\n", strip=True)
            return clean_text(text)
        except Exception:
            text = re.sub(r"<script[\s\S]*?</script>", " ", markup, flags=re.I)
            text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            return clean_text(html.unescape(text))

    @tool(
        description="Fetch a web page and summarise its contents.",
        params={
            "url": {"type": "string", "description": "Page URL", "required": True},
            "question": {
                "type": "string",
                "description": "Optional question to answer from the page",
                "default": "",
            },
        },
        keywords=["scrape", "read this page", "summarize this url", "what does this page say",
                  "open link and"],
    )
    async def read_page(self, url: str, question: str = "") -> ModuleResult:
        """Scrape ``url`` and summarise it (optionally answering ``question``)."""
        target = (url or "").strip()
        if not target:
            return ModuleResult.fail("No URL given.")
        if not target.startswith(("http://", "https://")):
            target = f"https://{target}"

        text = await self._fetch_text(target)
        if not text:
            return ModuleResult.fail(f"I couldn't read anything useful from {target}.")

        if self.llm is None or not getattr(self.llm, "available", False):
            return ModuleResult(
                success=True, output=truncate(text, 2500), data={"url": target, "raw": True}
            )

        instruction = (
            f"Answer this question from the page: {question}"
            if question
            else "Summarise this page in 4 sentences and list its 3 key points."
        )
        summary = await self.llm.complete(
            f"PAGE CONTENT ({target}):\n{truncate(text, 6000)}\n\n{instruction}",
            temperature=0.3,
            max_tokens=500,
        )
        return ModuleResult(
            success=True,
            output=summary.strip() or truncate(text, 2000),
            data={"url": target, "chars": len(text)},
        )

    # --------------------------------------------------------------- weather
    @tool(
        description="Get the current weather and a short forecast for a location.",
        params={
            "location": {
                "type": "string",
                "description": "City name, or empty for auto-detect",
                "default": "",
            }
        },
        keywords=["weather", "forecast", "temperature", "is it raining", "how hot", "how cold"],
        examples=['weather(location="Amsterdam")'],
    )
    async def weather(self, location: str = "") -> ModuleResult:
        """Fetch weather from wttr.in (free, no key required)."""
        place = (location or "").strip()
        if not place or place.lower() == "auto":
            place = "" if self.default_location.lower() == "auto" else self.default_location

        response = await self._get(f"https://wttr.in/{place}?format=j1")
        if response is None:
            return ModuleResult.fail(
                "Weather service unreachable — wttr.in isn't answering. Check your connection."
            )
        try:
            payload = response.json()
            current = payload["current_condition"][0]
            area = payload.get("nearest_area", [{}])[0]
            city = (area.get("areaName", [{}])[0].get("value") or place or "your location")
            region = area.get("country", [{}])[0].get("value", "")

            metric = self.units != "imperial"
            temp = current["temp_C"] if metric else current["temp_F"]
            feels = current["FeelsLikeC"] if metric else current["FeelsLikeF"]
            unit = "°C" if metric else "°F"
            description = current["weatherDesc"][0]["value"]
            wind_speed = current["windspeedKmph"] if metric else current["windspeedMiles"]
            wind_unit = "km/h" if metric else "mph"

            forecast_lines: List[str] = []
            for day in payload.get("weather", [])[:3]:
                date = day.get("date", "")
                high = day["maxtempC"] if metric else day["maxtempF"]
                low = day["mintempC"] if metric else day["mintempF"]
                desc = day["hourly"][4]["weatherDesc"][0]["value"] if day.get("hourly") else ""
                forecast_lines.append(f"{date}: {low}-{high}{unit}, {desc}")

            summary = (
                f"{city}{', ' + region if region else ''}: {description}, {temp}{unit} "
                f"(feels like {feels}{unit}), humidity {current['humidity']}%, "
                f"wind {wind_speed} {wind_unit}."
            )
            return ModuleResult(
                success=True,
                output=summary + ("\nForecast:\n" + "\n".join(forecast_lines) if forecast_lines else ""),
                speak=summary,
                data={
                    "location": city,
                    "temperature": temp,
                    "description": description,
                    "forecast": forecast_lines,
                },
            )
        except Exception as exc:
            return ModuleResult.fail(f"Could not parse the weather data: {exc}")

    # ------------------------------------------------------------------ news
    @tool(
        description="Get the latest news headlines from free RSS feeds.",
        params={
            "topic": {"type": "string", "description": "Optional topic filter", "default": ""},
            "limit": {"type": "integer", "description": "Number of headlines", "default": 8},
        },
        keywords=["news", "headlines", "what's happening", "current events", "top stories"],
    )
    async def news(self, topic: str = "", limit: int = 8) -> ModuleResult:
        """Aggregate headlines from the configured RSS feeds."""
        feeds = list(self.feeds)
        topic = (topic or "").strip()
        if topic:
            slug = topic.replace(" ", "+")
            feeds.insert(0, f"https://news.google.com/rss/search?q={slug}&hl=en-US&gl=US&ceid=US:en")

        entries: List[Dict[str, str]] = []
        for feed_url in feeds[:4]:
            response = await self._get(feed_url)
            if response is None:
                continue
            entries.extend(self._parse_feed(response.text, feed_url))
            if len(entries) >= int(limit) * 2:
                break

        if not entries:
            return ModuleResult.fail("No news feeds responded. Check your internet connection.")

        if topic:
            needle = topic.lower()
            filtered = [item for item in entries if needle in (item["title"] + item["summary"]).lower()]
            entries = filtered or entries

        entries = entries[: int(limit)]
        lines = [f"{index}. {item['title']} ({item['source']})"
                 for index, item in enumerate(entries, 1)]
        headline_speech = " ".join(f"{item['title']}." for item in entries[:5])
        return ModuleResult(
            success=True,
            output="Latest headlines:\n" + "\n".join(lines),
            speak=f"Here are today's headlines. {headline_speech}",
            data={"headlines": entries},
        )

    def _parse_feed(self, xml_text: str, source_url: str) -> List[Dict[str, str]]:
        """Parse an RSS/Atom document into simple dicts."""
        source = re.sub(r"^https?://(www\.)?", "", source_url).split("/")[0]
        try:
            import feedparser

            parsed = feedparser.parse(xml_text)
            return [
                {
                    "title": clean_text(entry.get("title", "")),
                    "url": entry.get("link", ""),
                    "summary": clean_text(re.sub(r"<[^>]+>", " ", entry.get("summary", "")))[:300],
                    "source": source,
                    "published": str(entry.get("published", "")),
                }
                for entry in parsed.entries[:15]
                if entry.get("title")
            ]
        except Exception:
            items = re.findall(r"<item>([\s\S]*?)</item>", xml_text)[:15]
            rows: List[Dict[str, str]] = []
            for item in items:
                title = re.search(r"<title>(?:<!\[CDATA\[)?([\s\S]*?)(?:\]\]>)?</title>", item)
                link = re.search(r"<link>([\s\S]*?)</link>", item)
                if title:
                    rows.append(
                        {
                            "title": clean_text(html.unescape(title.group(1))),
                            "url": link.group(1).strip() if link else "",
                            "summary": "",
                            "source": source,
                            "published": "",
                        }
                    )
            return rows

    # ------------------------------------------------------------- wikipedia
    @tool(
        description="Get a Wikipedia summary for a topic.",
        params={
            "topic": {"type": "string", "description": "Article topic", "required": True},
            "sentences": {"type": "integer", "description": "Length hint", "default": 5},
        },
        keywords=["wikipedia", "who is", "who was", "what is a", "encyclopedia", "tell me about"],
    )
    async def wikipedia(self, topic: str, sentences: int = 5) -> ModuleResult:
        """Fetch a Wikipedia extract via the open REST API."""
        subject = (topic or "").strip()
        if not subject:
            return ModuleResult.fail("Which topic?")

        slug = subject.replace(" ", "_")
        response = await self._get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
            headers={"Accept": "application/json"},
        )
        if response is not None:
            try:
                payload = response.json()
                extract = clean_text(payload.get("extract", ""))
                if extract:
                    trimmed = " ".join(re.split(r"(?<=[.!?])\s+", extract)[: max(1, int(sentences))])
                    return ModuleResult(
                        success=True,
                        output=f"{payload.get('title', subject)}: {trimmed}",
                        data={
                            "title": payload.get("title", subject),
                            "url": (payload.get("content_urls", {})
                                    .get("desktop", {})
                                    .get("page", "")),
                        },
                    )
            except Exception:
                pass

        # Fall back to the search API for near-miss titles.
        search_response = await self._get(
            "https://en.wikipedia.org/w/api.php"
            f"?action=query&list=search&srsearch={subject.replace(' ', '%20')}"
            "&format=json&srlimit=1"
        )
        if search_response is not None:
            try:
                hits = search_response.json()["query"]["search"]
                if hits:
                    return await self.wikipedia(hits[0]["title"], sentences)
            except Exception:
                pass
        return ModuleResult.fail(f"Wikipedia has nothing solid on '{subject}'.")

    @tool(
        description="Look up a place, business or address using OpenStreetMap.",
        params={"query": {"type": "string", "description": "Place to find", "required": True}},
        keywords=["where is", "address of", "location of", "nearest"],
    )
    async def find_place(self, query: str) -> ModuleResult:
        """Geocode a place name with the free Nominatim API."""
        subject = (query or "").strip()
        if not subject:
            return ModuleResult.fail("Which place?")
        response = await self._get(
            "https://nominatim.openstreetmap.org/search"
            f"?q={subject.replace(' ', '+')}&format=json&limit=3",
            headers={"User-Agent": "JARVIS-local-assistant/1.0"},
        )
        if response is None:
            return ModuleResult.fail("The map service didn't respond.")
        try:
            rows = response.json()
        except Exception:
            rows = []
        if not rows:
            return ModuleResult.fail(f"No place matched '{subject}'.")
        lines = [
            f"{row.get('display_name', '?')} ({row.get('lat')}, {row.get('lon')})"
            for row in rows
        ]
        return ModuleResult(success=True, output="\n".join(lines), data={"places": rows})

    @tool(
        description="Get today's date-relevant summary of a topic from multiple sources.",
        params={"topic": {"type": "string", "description": "Topic", "required": True}},
        keywords=["what's new with", "latest on", "any updates on"],
    )
    async def latest_on(self, topic: str) -> ModuleResult:
        """Combine news and web search for a 'what's new' briefing."""
        news_result = await self.news(topic=topic, limit=4)
        search_result = await self.search(f"{topic} news {datetime.now():%B %Y}", max_results=4)
        pieces: List[str] = []
        if news_result.success:
            pieces.append(news_result.output)
        if search_result.success:
            pieces.append(search_result.output)
        if not pieces:
            return ModuleResult.fail(f"Nothing current on '{topic}'.")
        return ModuleResult(success=True, output="\n\n".join(pieces), data={"topic": topic})


__all__ = ["WebSearch"]

# /core/intent_router.py
"""LLM-based intent classification: which module should handle this?

Two routers in one, and they check each other:

* **Keyword scoring** against :data:`INTENT_KEYWORDS` — instant, deterministic,
  and the only router available when Ollama is not running.
* **The model itself**, given a catalogue of the loaded modules and their own
  example phrasings, asked for strict JSON.

A confident keyword match overrules a hesitant model, which is what keeps
"set a timer for 10 minutes" out of the conversation branch on a bad day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from utils.helpers import extract_json, similar
from utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from core.brain import Brain

logger = get_logger("core.intent_router")


@dataclass
class Intent:
    """Classification result for one user utterance."""

    module: str
    confidence: float = 0.5
    reason: str = ""
    action: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    method: str = "keyword"

    @property
    def is_conversation(self) -> bool:
        """True when no module work is required."""
        return self.module in {"conversation", "chat", "none", ""}


INTENT_KEYWORDS: Dict[str, List[str]] = {
    "system_control": [
        "open ", "launch ", "start app", "close ", "quit ", "kill ", "screenshot",
        "screen shot", "volume", "mute", "unmute", "lock screen", "lock the",
        "cpu", "ram", "memory usage", "ram usage", "using all my memory",
        "using my memory", "disk", "battery", "system stats",
        "lock my", "lock screen", "lock the", "lock this",
        "what time", "what's the time", "current time", "today's date", "what date",
        "shell", "terminal", "run command", "type ", "press ", "click ",
        "hotkey", "shortcut", "clipboard", "processes", "brightness", "sleep the",
    ],
    "web_search": [
        "search for", "google", "look up", "duckduckgo", "on the web", "web search",
        "weather", "forecast", "temperature outside", "news", "headlines",
        "wikipedia", "who is", "what is the latest", "latest on", "scrape",
        "browse", "current price", "stock", "score", "happening in the world",
    ],
    "productivity": [
        "todo", "to-do", "to do list", "task", "add task", "remind", "reminder",
        "timer", "stopwatch", "alarm", "note", "notes", "jot", "briefing",
        "agenda", "schedule", "shopping list", "checklist", "mark done",
        "brief me", "my day",
    ],
    "code_assistant": [
        "write a python", "write code", "write a script", "write a function",
        "code for", "program that", "explain this code", "debug", "refactor",
        "fix this code", "run this code", "execute python", "unit test",
        "regex for", "sql query", "bash script", "algorithm",
    ],
    "file_manager": [
        "find file", "find all", "search files", "locate file", "organize",
        "organise", "clean up folder", "summarize this document", "summarise this document",
        "read the file", "read file", "open the pdf", "pdf", "docx", "csv",
        "spreadsheet", "in my downloads", "on my desktop", "folder", "directory",
        "duplicate files", "disk usage of", "biggest file", "largest file",
        "biggest files", "largest files", "taking up space", "space hogs",
    ],
    "knowledge": [
        "my documents", "my notes folder", "in my files", "according to my",
        "what does my", "search my documents", "index my", "knowledge base",
        "my pdfs say", "from my documents", "ask my documents", "in the contract",
        "in the paper", "reindex",
    ],
    "vision": [
        "what's on my screen", "whats on my screen", "look at my screen", "see my screen",
        "read my screen", "describe this image", "what is in this picture", "look at this",
        "what does this screenshot", "analyze the image", "analyse the image",
        "what do you see", "on my screen", "on the screen", "read the text on",
        "screen say", "screen shows",
    ],
    "communications": [
        "my email", "my inbox", "unread mail", "any new mail", "check mail",
        "send an email", "reply to", "my calendar", "my schedule", "my meetings",
        "next meeting", "what's on my calendar", "events today", "appointments",
    ],
    "models": [
        "what models", "which models", "list models", "installed models",
        "switch to ", "switch model", "change model", "use the model",
        "pull the model", "download the model", "ollama model", "which model are you",
        "what model are you", "best model for", "recommend a model",
    ],
    "self_improve": [
        "plugin", "plugins", "your plugins", "your tools",
        "search github", "on github", "find a repo", "find a library", "integrate that",
        "add a new skill", "install a plugin", "list your plugins", "your own code",
        "your source code", "modify yourself", "improve yourself", "rewrite your",
        "change your code", "fix your own", "upgrade yourself", "run your tests",
        "undo your change", "roll back your", "reload yourself", "what have you changed",
        "extend yourself", "learn a new skill", "write a plugin",
    ],
    "smart_assistant": [
        "meaning of life", "explain", "why does", "how does", "what does",
        "calculate", "convert", "translate", "summarize this text", "summarise this text",
        "write a poem", "write a story", "write me a", "haiku", "limerick",
        "short story", "define ", "definition of", "what does the word",
        "brainstorm", "idea", "advice",
        "compare", "pros and cons", "how many", "solve", "math",
        "% of", "percent of", "square root", "average of",
    ],
}


#: Confidence at which a keyword match outranks the model entirely.
DECISIVE_CONFIDENCE = 0.97

#: Phrases that settle the question on their own. A 3B router model is
#: confidently wrong often enough ("set a timer" → system_control, because it
#: contains the word "time") that these skip the model entirely: it is both
#: more accurate and one less round trip.
#: Words that veto a decisive match: "convert 10 miles to km" is a unit
#: conversion, but "convert this file to pdf" is emphatically not.
DECISIVE_VETOES: Dict[str, Tuple[str, ...]] = {
    "smart_assistant": (
        "file", "document", "pdf", "docx", "csv", "spreadsheet", "folder",
        "image", "picture", "screenshot", "video", "audio",
    ),
}

DECISIVE_PHRASES: Dict[str, Tuple[str, ...]] = {
    "productivity": (
        "set a timer", "set a 10", "start a timer", "set an alarm", "remind me",
        "add a reminder", "to my todo", "to my to-do", "todo list", "to-do list",
        "start a stopwatch", "daily briefing", "take a note", "make a note",
    ),
    "system_control": (
        "what time is it", "what's the time", "what is the time", "the current time",
        "take a screenshot", "lock the screen", "lock my screen", "shut down the computer",
        "what's my cpu", "how much ram", "battery level",
    ),
    "web_search": (
        "search for", "search the web", "google ", "duckduckgo",
        "what's the weather", "what is the weather", "how's the weather",
        "how is the weather", "the weather in", "weather forecast",
        "latest news", "in the news", "look it up online",
    ),
    "file_manager": (
        "find all pdf", "find every pdf", "organize my", "organise my",
        "summarize this document", "summarise this document", "summarize the document",
        "summarise the document", "duplicate files", "largest files",
    ),
    "code_assistant": (
        "write a python", "write me a python", "write a script", "write a program",
        "explain this code", "debug this", "refactor this", "run this code",
    ),
    "smart_assistant": (
        "translate ", "convert ", "how many kilometres", "how many kilometers",
        "what does the word", "brainstorm ",
    ),
}


class IntentRouter:
    """Decides which module handles an utterance."""

    def __init__(self, brain: "Brain") -> None:
        """Attach the router to a brain.

        Args:
            brain: The orchestrator whose modules, model and memory it reads.
        """
        self.brain = brain

    async def classify(self, text: str) -> Intent:
        """Determine which module (if any) should handle ``text``.

        Uses the LLM with a structured prompt, with keyword scoring as both a
        prior and an offline fallback.

        Args:
            text: The user's utterance.

        Returns:
            An :class:`Intent`.
        """
        keyword_intent = self._keyword_intent(text)

        # A decisive phrase is more reliable than a small router model, and
        # skipping the call makes the answer instant.
        if keyword_intent.confidence >= DECISIVE_CONFIDENCE:
            return keyword_intent

        if not self.brain.llm.available:
            return keyword_intent

        module_lines = []
        for name, skill in self.brain.modules.items():
            examples = "; ".join(skill.intent_examples[:3])
            module_lines.append(f"- {name}: {skill.description}"
                                + (f" (e.g. {examples})" if examples else ""))
        catalog = "\n".join(module_lines) or "- (no modules loaded)"

        prompt = (
            "Classify the user's request into exactly one category.\n\n"
            f"Categories:\n{catalog}\n"
            "- conversation: chit-chat, opinions, or anything answerable from your own "
            "knowledge without tools or fresh data.\n"
            "- memory: the user asks you to remember/forget something, or asks what you "
            "remember about them.\n\n"
            "Guidelines:\n"
            "* Anything needing current, real-world or online data -> web_search.\n"
            "* Anything that changes the computer's state -> system_control.\n"
            "* Lists, tasks, reminders, timers, notes -> productivity.\n"
            "* Files and documents on disk -> file_manager.\n"
            "* Writing/explaining/running code -> code_assistant.\n"
            "* Reasoning, maths, conversions, translation, creative writing -> "
            "smart_assistant.\n\n"
            f"Recent conversation:\n{self.brain.memory.short_term.transcript(2) or '(none)'}\n\n"
            f'User request: "{text}"\n\n'
            'Reply with ONLY JSON: {"module": "<category>", "confidence": 0.0-1.0, '
            '"reason": "<8 words max>"}'
        )
        raw = await self.brain.llm.complete(
            prompt,
            temperature=0.0,
            max_tokens=120,
            model=self.brain.llm.router_model,
            json_mode=True,
        )
        parsed = extract_json(raw)
        if isinstance(parsed, dict):
            module = str(parsed.get("module", "")).strip().lower().replace("-", "_")
            valid = set(self.brain.modules) | {"conversation", "memory"}
            if module not in valid:
                module = self._closest_module(module) or keyword_intent.module
            try:
                confidence = float(parsed.get("confidence", 0.6))
            except Exception:
                confidence = 0.6
            # A strong keyword signal overrides a hesitant model.
            if keyword_intent.confidence >= 0.85 and confidence < 0.6:
                return keyword_intent
            return Intent(
                module=module,
                confidence=confidence,
                reason=str(parsed.get("reason", ""))[:80],
                method="llm",
            )
        return keyword_intent

    def _keyword_intent(self, text: str) -> Intent:
        """Score the utterance against the keyword tables.

        Args:
            text: The user's utterance.

        Returns:
            An :class:`Intent` whose confidence reaches
            :data:`DECISIVE_CONFIDENCE` only for phrases that admit no doubt.
        """
        lowered = f" {(text or '').lower().strip()} "

        for module, phrases in DECISIVE_PHRASES.items():
            if module not in self.brain.modules:
                continue
            hit = next((phrase for phrase in phrases if phrase in lowered), "")
            if hit and any(word in lowered for word in DECISIVE_VETOES.get(module, ())):
                continue
            if hit:
                return Intent(module, DECISIVE_CONFIDENCE, f"decisive phrase {hit!r}",
                              method="keyword")
        scores: Dict[str, float] = {}
        for module, keywords in INTENT_KEYWORDS.items():
            if module not in self.brain.modules:
                continue
            score = 0.0
            for keyword in keywords:
                if keyword in lowered:
                    score += 1.0 + len(keyword) / 40.0
            if score:
                scores[module] = score

        if any(phrase in lowered for phrase in (" remember that ", " remember this ",
                                                " forget ", " what do you remember",
                                                " memorise ", " memorize ")):
            return Intent("memory", 0.9, "explicit memory phrasing", method="keyword")

        if not scores:
            return Intent("conversation", 0.4, "no capability keywords", method="keyword")

        module = max(scores, key=lambda key: scores[key])
        best = scores[module]
        confidence = min(0.95, 0.5 + best / 4.0)
        return Intent(module, confidence, f"keyword score {best:.1f}", method="keyword")

    def _closest_module(self, name: str) -> Optional[str]:
        """Fuzzy-match a hallucinated category onto a loaded module."""
        if not name:
            return None
        best, score = None, 0.5
        for candidate in [*self.brain.modules, "conversation", "memory"]:
            value = similar(name.replace("_", " "), candidate.replace("_", " "))
            if value > score:
                best, score = candidate, value
        return best


__all__ = ["INTENT_KEYWORDS", "Intent", "IntentRouter"]

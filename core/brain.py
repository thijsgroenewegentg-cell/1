# /core/brain.py
"""The central orchestrator: LLM connection, intent routing and the ReAct loop.

Pipeline for every user utterance::

    text -> memory context -> intent classification -> module routing
         -> ReAct loop (Reason -> Act -> Observe) -> JARVIS-flavoured answer
         -> memory write-back

The brain degrades gracefully: if Ollama is not running it still routes
commands to modules using keyword matching, so system control, timers, search
and file tools keep working without a model.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from core.config import Config
from core.memory import Memory
from modules.base import BaseModule, ModuleResult
from utils.helpers import (
    detect_os,
    extract_json,
    friendly_time,
    similar,
    strip_markdown,
    truncate,
)
from utils.logger import get_logger
from utils.security import SecurityGuard

logger = get_logger("core.brain")

MAX_REACT_STEPS = 4


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


class OllamaClient:
    """Async client for a local Ollama server.

    Only uses the free, local HTTP API — no keys, no cloud.
    """

    def __init__(self, config: Config) -> None:
        """Args:
        config: The global configuration object.
        """
        self.config = config
        self.host: str = str(config.get("llm.host", "http://localhost:11434")).rstrip("/")
        self.model: str = str(config.get("llm.model", "llama3.2"))
        self.router_model: str = str(config.get("llm.router_model", "") or self.model)
        self.fallbacks: List[str] = list(config.get("llm.fallback_models", []) or [])
        self.timeout: float = float(config.get("llm.timeout", 180))
        self.available: bool = False
        self.models: List[str] = []
        self._client: Optional[Any] = None
        self._warned = False

    # -- connection ---------------------------------------------------------
    async def _http(self) -> Any:
        """Return a lazily created shared ``httpx.AsyncClient``."""
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def initialize(self) -> bool:
        """Probe the Ollama server and resolve which model to use.

        Returns:
            True when a usable model was found.
        """
        self.models = await self.list_models()
        if not self.models:
            self.available = False
            logger.warning(
                "Ollama not reachable at %s — running in degraded (no-LLM) mode. "
                "Start it with: ollama serve",
                self.host,
            )
            return False

        resolved = self._resolve_model(self.model)
        if resolved is None:
            for candidate in self.fallbacks:
                resolved = self._resolve_model(candidate)
                if resolved:
                    logger.warning(
                        "Model '%s' is not installed; falling back to '%s'.",
                        self.model,
                        resolved,
                    )
                    break
        if resolved is None:
            resolved = self.models[0]
            logger.warning(
                "Neither '%s' nor any fallback is installed; using '%s'. "
                "Install the preferred one with: ollama pull %s",
                self.model,
                resolved,
                self.model,
            )
        self.model = resolved

        router = self._resolve_model(self.router_model) or self.model
        self.router_model = router
        self.available = True
        logger.info("LLM ready — model=%s router=%s host=%s", self.model, router, self.host)
        return True

    def _resolve_model(self, name: str) -> Optional[str]:
        """Match a configured model name against installed Ollama tags."""
        if not name:
            return None
        wanted = name.split(":")[0].lower()
        for installed in self.models:
            if installed.lower() == name.lower():
                return installed
        for installed in self.models:
            if installed.split(":")[0].lower() == wanted:
                return installed
        return None

    async def list_models(self) -> List[str]:
        """Return the tags of every locally installed model."""
        try:
            client = await self._http()
            response = await client.get(f"{self.host}/api/tags", timeout=8.0)
            response.raise_for_status()
            payload = response.json()
            return [entry.get("name", "") for entry in payload.get("models", []) if entry]
        except Exception as exc:
            logger.debug("list_models failed: %s", exc)
            return []

    async def health(self) -> Dict[str, Any]:
        """Return a status dict for the ``status`` command."""
        models = await self.list_models()
        return {
            "host": self.host,
            "online": bool(models),
            "model": self.model,
            "router_model": self.router_model,
            "installed": models,
        }

    # -- generation ---------------------------------------------------------
    def _options(self, **overrides: Any) -> Dict[str, Any]:
        """Merge configured sampling options with per-call overrides."""
        options = {
            "temperature": float(self.config.get("llm.temperature", 0.7)),
            "top_p": float(self.config.get("llm.top_p", 0.9)),
            "num_ctx": int(self.config.get("llm.num_ctx", 4096)),
            "num_predict": int(self.config.get("llm.max_tokens", 700)),
        }
        if "temperature" in overrides and overrides["temperature"] is not None:
            options["temperature"] = float(overrides["temperature"])
        if "max_tokens" in overrides and overrides["max_tokens"] is not None:
            options["num_predict"] = int(overrides["max_tokens"])
        if "top_p" in overrides and overrides["top_p"] is not None:
            options["top_p"] = float(overrides["top_p"])
        return options

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        """Send a chat completion request.

        Args:
            messages: OpenAI-style ``[{"role", "content"}]`` list.
            temperature: Sampling temperature override.
            max_tokens: Response length cap.
            model: Model override (defaults to the resolved main model).
            json_mode: Ask Ollama to constrain output to valid JSON.

        Returns:
            The assistant text, or ``""`` when the server is unreachable.
        """
        if not self.available and not await self.initialize():
            return ""

        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.config.get("llm.keep_alive", "10m"),
            "options": self._options(temperature=temperature, max_tokens=max_tokens),
        }
        if json_mode:
            payload["format"] = "json"

        try:
            client = await self._http()
            response = await client.post(f"{self.host}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            return (data.get("message") or {}).get("content", "").strip()
        except Exception as exc:
            if not self._warned:
                logger.warning("LLM request failed: %s", truncate(str(exc), 160))
                self._warned = True
            self.available = False
            return ""

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        json_mode: bool = False,
    ) -> str:
        """Single-turn convenience wrapper around :meth:`chat`."""
        messages: List[Dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            json_mode=json_mode,
        )

    async def stream(
        self, messages: List[Dict[str, str]], temperature: Optional[float] = None
    ) -> AsyncIterator[str]:
        """Yield response tokens as they arrive (used by the CLI)."""
        if not self.available and not await self.initialize():
            return
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": self.config.get("llm.keep_alive", "10m"),
            "options": self._options(temperature=temperature),
        }
        try:
            client = await self._http()
            async with client.stream("POST", f"{self.host}/api/chat", json=payload) as response:
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    piece = (chunk.get("message") or {}).get("content", "")
                    if piece:
                        yield piece
                    if chunk.get("done"):
                        break
        except Exception as exc:
            logger.debug("Streaming failed: %s", exc)
            return

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None


# ---------------------------------------------------------------------------
# Routing types
# ---------------------------------------------------------------------------


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


# Keyword rules used both as an LLM prior and as the offline fallback router.
INTENT_KEYWORDS: Dict[str, List[str]] = {
    "system_control": [
        "open ", "launch ", "start app", "close ", "quit ", "kill ", "screenshot",
        "screen shot", "volume", "mute", "unmute", "lock screen", "lock the",
        "cpu", "ram", "memory usage", "disk", "battery", "system stats",
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
        "duplicate files", "disk usage of",
    ],
    "smart_assistant": [
        "meaning of life", "explain", "why does", "how does", "what does",
        "calculate", "convert", "translate", "summarize this text", "summarise this text",
        "write a poem", "write a story", "brainstorm", "idea", "advice",
        "compare", "pros and cons", "how many", "solve", "math",
    ],
}


# ---------------------------------------------------------------------------
# Brain
# ---------------------------------------------------------------------------


class Brain:
    """JARVIS's cognition: persona, routing, tool use and memory integration."""

    def __init__(self, config: Config) -> None:
        """Args:
        config: The global configuration object.
        """
        self.config = config
        self.llm = OllamaClient(config)
        self.memory = Memory(config)
        self.security = SecurityGuard.from_config(config.section("security"))
        self.modules: Dict[str, BaseModule] = {}
        self.started_at = time.time()
        self.turn_count = 0
        self.last_intent: Optional[Intent] = None
        self.speaker_hook: Optional[Any] = None  # set by main for status updates
        self._busy = asyncio.Lock()

    # ------------------------------------------------------------------ setup
    async def initialize(self) -> None:
        """Boot the LLM connection, memory and every enabled module."""
        await asyncio.gather(self.llm.initialize(), self.memory.initialize())
        await self._load_modules()
        logger.info(
            "Brain online — %d modules, LLM %s",
            len(self.modules),
            "ready" if self.llm.available else "offline (degraded mode)",
        )

    async def _load_modules(self) -> None:
        """Import and instantiate the modules enabled in config.yaml."""
        registry = {
            "system_control": ("modules.system_control", "SystemControl"),
            "web_search": ("modules.web_search", "WebSearch"),
            "productivity": ("modules.productivity", "Productivity"),
            "code_assistant": ("modules.code_assistant", "CodeAssistant"),
            "file_manager": ("modules.file_manager", "FileManager"),
            "smart_assistant": ("modules.smart_assistant", "SmartAssistant"),
        }
        import importlib

        for name, (module_path, class_name) in registry.items():
            if not self.config.get(f"modules.{name}", True):
                logger.info("Module '%s' disabled in config.", name)
                continue
            try:
                imported = importlib.import_module(module_path)
                cls = getattr(imported, class_name)
                instance: BaseModule = cls(self.config, llm=self.llm, security=self.security)
                await instance.setup()
                self.modules[name] = instance
                logger.debug("Loaded module '%s' with %d tools", name, len(instance.tools))
            except Exception as exc:  # noqa: BLE001 - one bad module must not kill JARVIS
                logger.error("Could not load module '%s': %s", name, exc)

    async def shutdown(self) -> None:
        """Persist memory and tear down modules and the HTTP client."""
        for module in self.modules.values():
            try:
                await module.shutdown()
            except Exception:
                pass
        try:
            await self.memory.save()
        except Exception:
            pass
        await self.llm.close()
        logger.info("Brain offline. Uptime %.0fs, %d turns.", time.time() - self.started_at,
                    self.turn_count)

    # --------------------------------------------------------------- persona
    def system_prompt(self, memory_context: str = "") -> str:
        """Build the JARVIS system prompt.

        Args:
            memory_context: Rendered long-term memories to inject.

        Returns:
            The full system prompt string.
        """
        user_name = self.config.get("user.name", "Sir")
        address = self.config.user_address()
        assistant_name = self.config.get("assistant.name", "JARVIS")
        sarcasm = float(self.config.get("assistant.sarcasm", 0.35))
        personality = str(self.config.get("assistant.personality", "witty"))

        tone = {
            "witty": (
                "Dry British wit. Understated, clever, occasionally teasing — never mean. "
                "Think Tony Stark's JARVIS: unflappable, faintly amused by human chaos."
            ),
            "professional": "Crisp, precise and courteous. Minimal flourish.",
            "minimal": "Extremely terse. Answer, then stop.",
        }.get(personality, "Dry British wit, helpful and concise.")

        sarcasm_line = (
            "Sprinkle in the occasional deadpan remark." if sarcasm >= 0.3 else
            "Keep quips rare."
        )

        lines = [
            f"You are {assistant_name}, {user_name}'s personal AI assistant, running entirely "
            "locally on their machine.",
            f"Address them as '{address}'.",
            f"Tone: {tone} {sarcasm_line}",
            "",
            "Rules:",
            "1. Be concise. Two or three sentences unless detail is genuinely required — "
            "your replies are often spoken aloud.",
            "2. Never invent results. If a tool gave you data, use it; if it failed, say so "
            "plainly (with a touch of humour) and suggest the fix.",
            "3. Confirm before anything destructive.",
            "4. Speak naturally: no markdown headers, no bullet spam, no emoji, "
            "no stage directions.",
            "5. If the user asks for code, give the code and a one-line explanation.",
        ]
        if self.config.get("assistant.proactive", True):
            lines.append(
                "6. When genuinely useful, add one short proactive suggestion at the end."
            )

        lines += [
            "",
            f"Context: {friendly_time()}. Host OS: {detect_os()}. "
            f"Capabilities online: {', '.join(self.modules) or 'none'}.",
        ]
        if memory_context:
            lines += ["", memory_context]
        return "\n".join(lines)

    # ------------------------------------------------------------ classifying
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

        if not self.llm.available:
            return keyword_intent

        module_lines = []
        for name, module in self.modules.items():
            examples = "; ".join(module.intent_examples[:3])
            module_lines.append(f"- {name}: {module.description}" + (f" (e.g. {examples})" if examples else ""))
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
            f"Recent conversation:\n{self.memory.short_term.transcript(2) or '(none)'}\n\n"
            f'User request: "{text}"\n\n'
            'Reply with ONLY JSON: {"module": "<category>", "confidence": 0.0-1.0, '
            '"reason": "<8 words max>"}'
        )
        raw = await self.llm.complete(
            prompt,
            temperature=0.0,
            max_tokens=120,
            model=self.llm.router_model,
            json_mode=True,
        )
        parsed = extract_json(raw)
        if isinstance(parsed, dict):
            module = str(parsed.get("module", "")).strip().lower().replace("-", "_")
            valid = set(self.modules) | {"conversation", "memory"}
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

    def _closest_module(self, name: str) -> Optional[str]:
        """Fuzzy-match a hallucinated category onto a loaded module."""
        if not name:
            return None
        best, score = None, 0.5
        for candidate in list(self.modules) + ["conversation", "memory"]:
            value = similar(name.replace("_", " "), candidate.replace("_", " "))
            if value > score:
                best, score = candidate, value
        return best

    def _keyword_intent(self, text: str) -> Intent:
        """Score the utterance against :data:`INTENT_KEYWORDS`."""
        lowered = f" {(text or '').lower().strip()} "
        scores: Dict[str, float] = {}
        for module, keywords in INTENT_KEYWORDS.items():
            if module not in self.modules:
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

    # ------------------------------------------------------------- dispatching
    def tool_registry(self, primary: Optional[str] = None) -> str:
        """Render the tool catalog for the ReAct prompt.

        Args:
            primary: Module whose tools are listed in full.

        Returns:
            A prompt-ready catalog string.
        """
        blocks: List[str] = []
        if primary and primary in self.modules:
            module = self.modules[primary]
            blocks.append(f"## {primary} (primary — prefer these)\n{module.tool_catalog()}")
        for name, module in self.modules.items():
            if name == primary:
                continue
            names = ", ".join(f"{name}.{tool_name}" for tool_name in module.tools)
            blocks.append(f"## {name}\n{names}")
        blocks.append("## memory\n- memory.remember(text) — store a durable fact about the user\n"
                      "- memory.recall(query) — search what you remember")
        return "\n\n".join(blocks)

    async def dispatch(self, reference: str, params: Dict[str, Any]) -> ModuleResult:
        """Execute ``module.tool`` (or a bare tool name) with ``params``.

        Args:
            reference: ``"module.tool"``, ``"tool"`` or ``"module"``.
            params: Tool parameters.

        Returns:
            A :class:`ModuleResult`; never raises.
        """
        reference = (reference or "").strip().strip("()")
        if not reference:
            return ModuleResult.fail("No tool specified.")

        module_name, _, tool_name = reference.partition(".")
        module_name = module_name.strip().lower()
        tool_name = tool_name.strip()

        if module_name == "memory":
            return await self._memory_tool(tool_name, params)

        if module_name in self.modules:
            module = self.modules[module_name]
            if tool_name:
                return await module.call_tool(tool_name, params)
            return await module.execute(str(params.get("query", "")), params)

        # Bare tool name: search every module.
        for name, module in self.modules.items():
            if reference in module.tools:
                return await module.call_tool(reference, params)

        return ModuleResult.fail(
            f"No such tool '{reference}'. Known modules: {', '.join(self.modules)}."
        )

    async def _memory_tool(self, tool_name: str, params: Dict[str, Any]) -> ModuleResult:
        """Handle the brain-level memory tools."""
        text = str(params.get("text") or params.get("query") or params.get("content") or "")
        if tool_name in {"remember", "store", "save"}:
            ok = await self.memory.remember(text, category=str(params.get("category", "fact")))
            return (
                ModuleResult.ok(f"Committed to memory: {truncate(text, 120)}")
                if ok
                else ModuleResult.fail("I could not store that.")
            )
        if tool_name in {"recall", "search", "query"}:
            hits = await self.memory.recall(text, k=int(params.get("k", 5) or 5))
            if not hits:
                return ModuleResult.ok("Nothing relevant in long-term memory.")
            body = "\n".join(f"- ({hit.category}) {hit.text}" for hit in hits)
            return ModuleResult.ok(body, count=len(hits))
        if tool_name in {"forget", "delete"}:
            removed = await self.memory.forget(text)
            return ModuleResult.ok(f"Removed {removed} memory entrie(s) matching '{text}'.")
        return ModuleResult.fail(f"Unknown memory tool '{tool_name}'.")

    # -------------------------------------------------------------- reasoning
    async def process(self, text: str, speak_status: bool = False) -> str:
        """Main entry point: turn a user utterance into JARVIS's reply.

        Args:
            text: What the user said or typed.
            speak_status: Emit progress updates through ``speaker_hook``.

        Returns:
            The assistant's response text (already persona-shaped).
        """
        text = (text or "").strip()
        if not text:
            return "You'll have to actually say something, sir."

        async with self._busy:
            self.turn_count += 1
            start = time.perf_counter()
            try:
                response = await self._process_inner(text, speak_status)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - last line of defence
                logger.exception("Unhandled error while processing input")
                response = (
                    f"Something went sideways in my reasoning: {exc}. "
                    "I've logged it; try rephrasing and I'll behave."
                )

            elapsed = time.perf_counter() - start
            logger.info(
                "Turn %d handled in %.2fs via %s",
                self.turn_count,
                elapsed,
                self.last_intent.module if self.last_intent else "?",
            )
            await self.memory.add_exchange(
                text, response, self.last_intent.module if self.last_intent else ""
            )
            if self.llm.available and self.config.get("memory.auto_extract_facts", True):
                asyncio.create_task(self._background_fact_extraction(text, response))
            return response

    async def _background_fact_extraction(self, user_text: str, response: str) -> None:
        """Mine the exchange for durable facts without blocking the reply."""
        try:
            await self.memory.extract_and_store_facts(user_text, response, self.llm)
        except Exception as exc:
            logger.debug("Fact extraction failed: %s", exc)

    async def _process_inner(self, text: str, speak_status: bool) -> str:
        """Classification + routing + answer generation."""
        memory_context = await self.memory.build_context(text)
        intent = await self.classify(text)
        self.last_intent = intent
        logger.debug(
            "Intent: %s (%.2f, %s) — %s",
            intent.module, intent.confidence, intent.method, intent.reason,
        )

        if intent.module == "memory":
            return await self._handle_memory_intent(text, memory_context)

        if intent.is_conversation or intent.module not in self.modules:
            return await self._converse(text, memory_context)

        if speak_status and self.speaker_hook:
            await self._status(f"Working on it, {self.config.user_address()}.")

        return await self._react(text, intent, memory_context)

    async def _status(self, message: str) -> None:
        """Emit a spoken/printed progress update if a hook is installed."""
        if not self.speaker_hook:
            return
        try:
            result = self.speaker_hook(message)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            pass

    async def _handle_memory_intent(self, text: str, memory_context: str) -> str:
        """Store, recall or forget memories based on natural phrasing."""
        lowered = text.lower()
        if "forget" in lowered:
            keyword = lowered.split("forget", 1)[1].strip(" .,'\"about")
            removed = await self.memory.forget(keyword) if keyword else 0
            return (
                f"Consider it forgotten — {removed} entrie(s) purged."
                if removed
                else "I found nothing matching that to forget, sir."
            )

        if any(phrase in lowered for phrase in ("what do you remember", "what do you know about",
                                                "recall")):
            hits = await self.memory.recall(text, k=6, min_score=0.05)
            if not hits:
                return "Nothing in long-term storage yet, sir. Tell me something worth keeping."
            body = "\n".join(f"• ({hit.category}) {hit.text}" for hit in hits)
            return f"Here's what I have on file:\n{body}"

        fact = text
        for prefix in ("remember that ", "remember this: ", "remember: ", "remember ",
                       "memorise that ", "memorize that "):
            if lowered.startswith(prefix):
                fact = text[len(prefix):]
                break
        stored = await self.memory.remember(fact.strip(), category="fact", importance=0.8,
                                            source="explicit")
        if stored:
            return f"Noted and filed away, {self.config.user_address()}."
        if self.llm.available:
            return await self._converse(text, memory_context)
        return "My long-term memory is offline at the moment, sir."

    async def _converse(self, text: str, memory_context: str) -> str:
        """Plain conversational reply with persona and history."""
        if not self.llm.available:
            return self._offline_reply(text)

        messages = [{"role": "system", "content": self.system_prompt(memory_context)}]
        messages.extend(self.memory.short_term.messages(limit=8))
        messages.append({"role": "user", "content": text})
        reply = await self.llm.chat(messages)
        return reply.strip() or self._offline_reply(text)

    async def _react(self, text: str, intent: Intent, memory_context: str) -> str:
        """Run the Reason → Act → Observe loop, then compose the answer.

        Args:
            text: The user's request.
            intent: The classified intent (its module is the primary toolset).
            memory_context: Long-term memory block for the prompt.

        Returns:
            The final natural-language answer.
        """
        module = self.modules.get(intent.module)
        if module is None:
            return await self._converse(text, memory_context)

        # --- degraded mode: no LLM, drive the module directly ---------------
        if not self.llm.available:
            result = await module.execute(text, {})
            if result.success:
                return result.output or "Done, sir."
            return f"{result.error or 'That did not work.'} (LLM offline — running on reflexes.)"

        transcript: List[str] = []
        observations: List[Tuple[str, ModuleResult]] = []
        catalog = self.tool_registry(intent.module)

        for step in range(1, MAX_REACT_STEPS + 1):
            prompt = self._react_prompt(text, catalog, transcript, step, memory_context)
            raw = await self.llm.complete(
                prompt,
                system=self.system_prompt(),
                temperature=0.1,
                max_tokens=420,
                json_mode=True,
            )
            decision = extract_json(raw)

            if not isinstance(decision, dict):
                logger.debug("ReAct step %d produced no JSON; falling back to direct call.", step)
                result = await module.execute(text, {})
                observations.append((f"{intent.module}.auto", result))
                break

            thought = str(decision.get("thought", "")).strip()
            if thought:
                transcript.append(f"Thought: {truncate(thought, 220)}")
                logger.debug("Thought: %s", truncate(thought, 160))

            answer = decision.get("answer") or decision.get("final_answer")
            action = decision.get("action") or decision.get("tool")

            if action in (None, "", "none", "null") and answer:
                return self._finalize(str(answer))

            if not action:
                result = await module.execute(text, {})
                observations.append((f"{intent.module}.auto", result))
                break

            params = decision.get("params") or decision.get("arguments") or {}
            if not isinstance(params, dict):
                params = {"query": str(params)}

            reference = str(action)
            if "." not in reference:
                reference = f"{intent.module}.{reference}"

            await self._status_for_tool(reference, step)
            result = await self.dispatch(reference, params)
            observations.append((reference, result))
            transcript.append(f"Action: {reference} {json.dumps(params, default=str)[:200]}")
            transcript.append(f"Observation: {result.to_observation(900)}")
            logger.debug("Observation: %s", truncate(result.to_observation(300), 300))

            if result.success and self._is_terminal(reference, result):
                break

        return await self._compose_answer(text, observations, memory_context)

    def _react_prompt(
        self,
        text: str,
        catalog: str,
        transcript: List[str],
        step: int,
        memory_context: str,
    ) -> str:
        """Build the prompt for one ReAct iteration."""
        history = "\n".join(transcript[-8:]) or "(nothing yet)"
        return (
            "You are the reasoning core of JARVIS. Decide the next step.\n\n"
            f"TOOLS:\n{catalog}\n\n"
            + (f"MEMORY:\n{memory_context}\n\n" if memory_context else "")
            + f"USER REQUEST: {text}\n\n"
            f"SCRATCHPAD (step {step} of {MAX_REACT_STEPS}):\n{history}\n\n"
            "Reply with ONLY a JSON object:\n"
            '{"thought": "one short sentence of reasoning", '
            '"action": "module.tool or null", "params": {}, '
            '"answer": "final answer if no tool is needed, else null"}\n\n'
            "Rules: call at most one tool per step. Use a tool when you need real data or "
            "must change something on the machine. If the scratchpad already contains the "
            "information needed, set action to null and give the answer. Never invent "
            "observations."
        )

    async def _status_for_tool(self, reference: str, step: int) -> None:
        """Give the user a spoken heads-up for slower tools."""
        slow = ("search", "scrape", "summarize", "news", "weather", "organize", "run_")
        if step == 1 and any(token in reference for token in slow):
            await self._status(random.choice([
                "One moment.",
                "Working on it.",
                "Give me a second, sir.",
            ]))

    @staticmethod
    def _is_terminal(reference: str, result: ModuleResult) -> bool:
        """Heuristic: does this tool result already satisfy the request?"""
        if result.needs_followup:
            return False
        terminal_prefixes = (
            "system_control.", "productivity.", "file_manager.organize",
            "code_assistant.save", "code_assistant.run",
        )
        return reference.startswith(terminal_prefixes)

    async def _compose_answer(
        self,
        text: str,
        observations: List[Tuple[str, ModuleResult]],
        memory_context: str,
    ) -> str:
        """Turn raw tool observations into a JARVIS-flavoured reply."""
        if not observations:
            return await self._converse(text, memory_context)

        successes = [item for item in observations if item[1].success]
        if not successes:
            failure = observations[-1][1]
            return self._humorous_failure(failure.error or failure.output)

        evidence = "\n\n".join(
            f"[{reference}]\n{truncate(result.output or result.error, 1600)}"
            for reference, result in observations
        )

        # Short, already-natural outputs can be spoken as-is.
        last_reference, last_result = successes[-1]
        if last_result.speak:
            return last_result.speak

        prompt = (
            f"The user asked: {text}\n\n"
            f"Tool results:\n{evidence}\n\n"
            "Write JARVIS's reply using ONLY the information above. Be concise and natural "
            "(this may be read aloud). Do not mention tool names, JSON or internal steps. "
            "If a result is a list, summarise the highlights rather than dumping everything. "
            "If the tools failed, say so honestly with a light touch."
        )
        reply = await self.llm.complete(
            prompt, system=self.system_prompt(memory_context), temperature=0.5, max_tokens=500
        )
        if reply.strip():
            return self._finalize(reply)

        # LLM went quiet — return the raw tool output rather than nothing.
        return truncate(last_result.output or "Done, sir.", 1200)

    @staticmethod
    def _finalize(text: str) -> str:
        """Strip stray formatting artefacts from a model answer."""
        cleaned = (text or "").strip().strip('"')
        for prefix in ("JARVIS:", "Jarvis:", "Assistant:", "Answer:", "Final Answer:"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
        return cleaned or "Done, sir."

    def _humorous_failure(self, error: str) -> str:
        """Report an error gracefully, with a little personality."""
        address = self.config.user_address()
        openers = [
            f"That didn't go to plan, {address}.",
            f"Well, {address}, I tried.",
            f"Minor indignity, {address}:",
        ]
        return f"{random.choice(openers)} {truncate(error or 'Unknown failure', 300)}"

    def _offline_reply(self, text: str) -> str:
        """Canned reply when no LLM is reachable."""
        return (
            "My language model is offline, sir — Ollama isn't answering on "
            f"{self.llm.host}. Start it with 'ollama serve' (and 'ollama pull "
            f"{self.config.get('llm.model')}'), and I'll be my eloquent self again. "
            "Direct commands like 'system stats', 'set a timer for 5 minutes' or "
            "'take a screenshot' still work."
        )

    # ----------------------------------------------------------------- extras
    async def greeting(self) -> str:
        """Compose the start-up greeting."""
        address = self.config.user_address()
        hour = datetime.now().hour
        part = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
        if not self.llm.available:
            return (
                f"{part}, {address}. Systems partially online — no language model detected, "
                "so I'm running on reflexes alone."
            )
        base = f"{part}, {address}. All systems online."
        try:
            spice = await self.llm.complete(
                f"In one short sentence (max 18 words), greet {address} as JARVIS at start-up. "
                f"It is {friendly_time()}. Be dry and witty. No emoji, no quotes.",
                system=self.system_prompt(),
                temperature=0.9,
                max_tokens=60,
            )
            if spice.strip():
                return self._finalize(spice)
        except Exception:
            pass
        return base

    async def status_report(self) -> Dict[str, Any]:
        """Collect a full status snapshot for the CLI ``status`` command."""
        memory_stats = await self.memory.stats()
        return {
            "llm": await self.llm.health(),
            "memory": memory_stats,
            "modules": {
                name: len(module.tools) for name, module in self.modules.items()
            },
            "turns": self.turn_count,
            "uptime_seconds": int(time.time() - self.started_at),
            "os": detect_os(),
            "security": {
                "confirm_dangerous": self.security.confirm_dangerous,
                "allow_shell": self.security.allow_shell,
            },
        }

    def speakable(self, text: str) -> str:
        """Strip markdown so the TTS engine reads clean prose."""
        return strip_markdown(text)


__all__ = ["Brain", "OllamaClient", "Intent", "INTENT_KEYWORDS"]

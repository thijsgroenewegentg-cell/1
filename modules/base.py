# /modules/base.py
"""Shared plumbing for every JARVIS capability module.

A module is a small class that:

* declares tools with the :func:`tool` decorator,
* exposes ``async def execute(command: str, args: dict) -> ModuleResult``,
* never raises — failures come back as ``ModuleResult(success=False, ...)``.

The brain discovers tools automatically, so adding a capability is just adding
a decorated method.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from utils.helpers import extract_json, similar, truncate
from utils.logger import get_logger

logger = get_logger("modules.base")

# Filler words that appear in front of nearly every spoken command.
_COMMAND_PREFIXES = (
    "jarvis", "hey jarvis", "ok jarvis", "please", "could you", "can you", "would you",
    "i want you to", "i need you to", "for me", "go ahead and", "now",
)


def strip_command_prefix(command: str) -> str:
    """Remove polite filler from the front of a spoken command.

    Args:
        command: Raw transcript or typed request.

    Returns:
        The command with leading filler words removed.
    """
    text = (command or "").strip()
    changed = True
    while changed:
        changed = False
        lowered = text.lower()
        for prefix in _COMMAND_PREFIXES:
            if lowered.startswith(prefix + " "):
                text = text[len(prefix) + 1 :].lstrip(" ,")
                changed = True
                break
            if lowered == prefix:
                return ""
    return text.strip()


# ---------------------------------------------------------------------------
# Tool declaration
# ---------------------------------------------------------------------------


@dataclass
class ToolSpec:
    """Metadata describing one callable capability."""

    name: str
    description: str
    params: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    dangerous: bool = False
    keywords: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)

    def signature(self) -> str:
        """Human/LLM readable one-line signature."""
        if not self.params:
            return f"{self.name}()"
        rendered = ", ".join(
            f"{key}: {meta.get('type', 'string')}"
            + ("" if meta.get("required") else f" = {meta.get('default')!r}")
            for key, meta in self.params.items()
        )
        return f"{self.name}({rendered})"

    def describe(self) -> str:
        """Multi-line description used inside LLM prompts."""
        lines = [f"- {self.signature()} — {self.description}"]
        for key, meta in self.params.items():
            hint = meta.get("description", "")
            if hint:
                lines.append(f"    · {key}: {hint}")
        if self.examples:
            lines.append(f"    · e.g. {self.examples[0]}")
        return "\n".join(lines)

    def to_schema(self) -> Dict[str, Any]:
        """JSON-schema-ish dict (handy for OpenAI-style function calling)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    key: {
                        "type": meta.get("type", "string"),
                        "description": meta.get("description", ""),
                    }
                    for key, meta in self.params.items()
                },
                "required": [
                    key for key, meta in self.params.items() if meta.get("required")
                ],
            },
        }


def tool(
    name: Optional[str] = None,
    description: str = "",
    params: Optional[Dict[str, Dict[str, Any]]] = None,
    dangerous: bool = False,
    keywords: Optional[List[str]] = None,
    examples: Optional[List[str]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator marking a method as an LLM-callable tool.

    Args:
        name: Tool name (defaults to the method name).
        description: What the tool does — shown to the LLM.
        params: ``{param: {"type", "description", "required", "default"}}``.
        dangerous: Route through the security guard before running.
        keywords: Extra words used by the offline keyword router.
        examples: Example invocations shown to the LLM.

    Returns:
        The decorated function, tagged with a :class:`ToolSpec`.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        spec = ToolSpec(
            name=name or func.__name__,
            description=description or (func.__doc__ or "").strip().split("\n")[0],
            params=params or {},
            dangerous=dangerous,
            keywords=[word.lower() for word in (keywords or [])],
            examples=examples or [],
        )
        setattr(func, "_jarvis_tool", spec)
        return func

    return decorator


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ModuleResult:
    """Uniform return value for every tool and module."""

    success: bool = True
    output: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    speak: str = ""
    needs_followup: bool = False
    followup: Optional[Dict[str, Any]] = None

    def offering(
        self, tool: str, params: Optional[Dict[str, Any]] = None, prompt: str = ""
    ) -> "ModuleResult":
        """Attach a "shall I?" action the user can confirm with a simple yes.

        Args:
            tool: ``module.tool`` reference to run on confirmation.
            params: Parameters for that tool.
            prompt: The question that was asked.

        Returns:
            ``self``, so this can be chained onto a result.
        """
        self.followup = {"tool": tool, "params": params or {}, "prompt": prompt}
        self.needs_followup = True
        return self

    @classmethod
    def ok(cls, output: str, **data: Any) -> "ModuleResult":
        """Build a successful result."""
        return cls(success=True, output=output, data=data)

    @classmethod
    def fail(cls, error: str, **data: Any) -> "ModuleResult":
        """Build a failed result."""
        return cls(success=False, output=error, error=error, data=data)

    def spoken(self) -> str:
        """Text that should be read aloud."""
        return self.speak or self.output

    def to_observation(self, limit: int = 1800) -> str:
        """Compact string handed back to the LLM during the ReAct loop."""
        status = "OK" if self.success else "ERROR"
        body = self.output or self.error or "(no output)"
        extra = ""
        if self.data:
            try:
                payload = json.dumps(self.data, default=str)
                if len(payload) < 700:
                    extra = f"\ndata: {payload}"
            except Exception:
                extra = ""
        return f"[{status}] {truncate(body, limit)}{extra}"

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return self.to_observation(200)


# ---------------------------------------------------------------------------
# Base module
# ---------------------------------------------------------------------------


class BaseModule:
    """Base class providing tool discovery, routing and safe execution."""

    name: str = "base"
    description: str = "Base module"
    intent_examples: List[str] = []

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Args:
        config: The :class:`core.config.Config` instance.
        llm: Object exposing ``async complete(prompt, **kw) -> str`` (optional).
        security: A :class:`utils.security.SecurityGuard` (optional).
        """
        self.config = config
        self.llm = llm
        if security is None:
            try:
                from utils.security import SecurityGuard

                security = SecurityGuard.from_config(config.section("security"))
            except Exception:  # pragma: no cover - defensive
                security = None
        self.security = security
        self.log = get_logger(f"modules.{self.name}")
        self._tools: Dict[str, ToolSpec] = {}
        self._callables: Dict[str, Callable[..., Any]] = {}
        self._discover_tools()

    # -- discovery ----------------------------------------------------------
    def _discover_tools(self) -> None:
        """Scan the instance for ``@tool`` decorated methods."""
        for attribute in dir(self):
            if attribute.startswith("__"):
                continue
            try:
                candidate = getattr(self, attribute)
            except Exception:
                continue
            spec = getattr(candidate, "_jarvis_tool", None)
            if isinstance(spec, ToolSpec):
                self._tools[spec.name] = spec
                self._callables[spec.name] = candidate

    @property
    def tools(self) -> Dict[str, ToolSpec]:
        """All tools this module exposes, keyed by name."""
        return self._tools

    def tool_catalog(self) -> str:
        """Render the tool list for inclusion in an LLM prompt."""
        return "\n".join(spec.describe() for spec in self._tools.values())

    def schemas(self) -> List[Dict[str, Any]]:
        """OpenAI-style function schemas for every tool."""
        return [spec.to_schema() for spec in self._tools.values()]

    # -- lifecycle ----------------------------------------------------------
    async def setup(self) -> None:
        """Optional async initialisation hook (override as needed)."""
        return None

    async def shutdown(self) -> None:
        """Optional async teardown hook (override as needed)."""
        return None

    # -- execution ----------------------------------------------------------
    async def call_tool(self, name: str, params: Optional[Dict[str, Any]] = None) -> ModuleResult:
        """Invoke a tool by name with keyword parameters.

        Args:
            name: Tool name.
            params: Parameters (coerced and filtered against the spec).

        Returns:
            A :class:`ModuleResult`; never raises.
        """
        params = dict(params or {})
        func = self._callables.get(name)
        spec = self._tools.get(name)
        if func is None or spec is None:
            close = self._closest_tool(name)
            if close:
                func, spec = self._callables[close], self._tools[close]
                self.log.debug("Tool %r not found, using closest match %r", name, close)
            else:
                return ModuleResult.fail(
                    f"Unknown tool '{name}' in module '{self.name}'. "
                    f"Available: {', '.join(self._tools) or 'none'}"
                )

        cleaned = self._coerce_params(spec, params)

        if spec.dangerous and self.security is not None:
            description = f"{self.name}.{spec.name} with {cleaned or 'no arguments'}"
            approved = await self.security.confirm(
                f"{description}\n  This action is flagged as sensitive. Proceed?"
            )
            if not approved:
                return ModuleResult.fail("Action cancelled — you did not confirm.")

        try:
            if inspect.iscoroutinefunction(func):
                result = await func(**cleaned)
            else:
                result = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: func(**cleaned)
                )
        except TypeError as exc:
            return ModuleResult.fail(f"Bad arguments for {spec.name}: {exc}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - modules must never crash JARVIS
            self.log.exception("Tool %s.%s failed", self.name, spec.name)
            return ModuleResult.fail(f"{spec.name} failed: {exc}")

        if isinstance(result, ModuleResult):
            return result
        if isinstance(result, dict):
            return ModuleResult.ok(str(result.get("output", result)), **result)
        return ModuleResult.ok(str(result))

    def _closest_tool(self, name: str) -> Optional[str]:
        """Fuzzy-match a hallucinated tool name onto a real one."""
        if not name:
            return None
        target = name.lower().replace(" ", "_")
        for candidate in self._tools:
            if candidate.lower() == target:
                return candidate
        best, best_score = None, 0.45
        for candidate in self._tools:
            score = similar(target.replace("_", " "), candidate.replace("_", " "))
            if score > best_score:
                best, best_score = candidate, score
        return best

    @staticmethod
    def _coerce_params(spec: ToolSpec, params: Dict[str, Any]) -> Dict[str, Any]:
        """Filter unknown keys, apply defaults and coerce simple types."""
        cleaned: Dict[str, Any] = {}
        for key, meta in spec.params.items():
            if key in params and params[key] is not None:
                value = params[key]
                kind = meta.get("type", "string")
                try:
                    if kind == "integer":
                        value = int(float(str(value)))
                    elif kind == "number":
                        value = float(str(value))
                    elif kind == "boolean":
                        if isinstance(value, str):
                            value = value.strip().lower() in {"true", "yes", "1", "on"}
                        else:
                            value = bool(value)
                    elif kind == "array" and isinstance(value, str):
                        parsed = extract_json(value)
                        value = parsed if isinstance(parsed, list) else [value]
                    elif kind == "string" and not isinstance(value, str):
                        value = str(value)
                except Exception:
                    value = params[key]
                cleaned[key] = value
            elif "default" in meta:
                cleaned[key] = meta["default"]
            elif meta.get("required"):
                cleaned[key] = "" if meta.get("type", "string") == "string" else None
        return cleaned

    async def execute(self, command: str, args: Optional[Dict[str, Any]] = None) -> ModuleResult:
        """Standard module entry point used by the brain.

        Picks the right tool for ``command`` (explicit ``args['action']`` wins,
        then the LLM, then keyword matching) and runs it.

        Args:
            command: The user's natural-language request.
            args: Optional hints, e.g. ``{"action": "open_app", "params": {...}}``.

        Returns:
            A :class:`ModuleResult`.
        """
        args = dict(args or {})
        if not self._tools:
            return ModuleResult.fail(f"Module '{self.name}' exposes no tools.")

        action = args.get("action") or args.get("tool")
        params = args.get("params") if isinstance(args.get("params"), dict) else None
        if params is None:
            params = {
                key: value
                for key, value in args.items()
                if key not in {"action", "tool", "params", "intent", "reason"}
            }

        if action:
            return await self.call_tool(str(action), params)

        chosen = await self.pick_tool(command, params)
        if chosen is None:
            return ModuleResult.fail(
                f"I could not work out which {self.name} action you wanted."
            )
        tool_name, tool_params = chosen
        merged = {**tool_params, **{k: v for k, v in params.items() if v not in (None, "")}}
        return await self.call_tool(tool_name, merged)

    async def pick_tool(
        self, command: str, hints: Optional[Dict[str, Any]] = None
    ) -> Optional[tuple[str, Dict[str, Any]]]:
        """Choose a tool + parameters for a natural language command.

        Tries the LLM first (structured JSON) and falls back to keyword scoring
        so the module keeps working with no model running.
        """
        if self.llm is not None and getattr(self.llm, "available", False):
            picked = await self._llm_pick(command, hints)
            if picked:
                return picked
        offline = self.offline_router(command)
        if offline:
            return offline
        return self._keyword_pick(command)

    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Module-specific rule-based routing used when no LLM is available.

        Override in subclasses to extract parameters from raw speech. Returning
        ``None`` defers to the generic keyword router.

        Args:
            command: The user's natural-language request.

        Returns:
            ``(tool_name, params)`` or ``None``.
        """
        return None

    async def _llm_pick(
        self, command: str, hints: Optional[Dict[str, Any]] = None
    ) -> Optional[tuple[str, Dict[str, Any]]]:
        """Ask the LLM to select a tool and fill in its parameters."""
        prompt = (
            f"You are the dispatcher for the '{self.name}' module.\n"
            f"Module purpose: {self.description}\n\n"
            f"Available tools:\n{self.tool_catalog()}\n\n"
            f"User request: {command}\n"
            + (f"Extra context: {json.dumps(hints, default=str)}\n" if hints else "")
            + "\nRespond with ONLY this JSON object and nothing else:\n"
            '{"tool": "<tool name>", "params": {<parameters>}}'
        )
        try:
            raw = await self.llm.complete(prompt, temperature=0.0, max_tokens=300)
        except Exception as exc:
            self.log.debug("LLM tool pick failed: %s", exc)
            return None
        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            return None
        name = str(parsed.get("tool") or parsed.get("name") or "").strip()
        if not name:
            return None
        resolved = name if name in self._tools else (self._closest_tool(name) or "")
        if not resolved:
            return None
        params = parsed.get("params") or parsed.get("arguments") or {}
        return resolved, params if isinstance(params, dict) else {}

    def _keyword_pick(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Offline fallback: score tools by keyword and description overlap."""
        text = (command or "").lower()
        best_name, best_score = None, 0.0
        for name, spec in self._tools.items():
            score = 0.0
            for keyword in spec.keywords:
                if keyword in text:
                    score += 2.0 + len(keyword) / 20.0
            readable = name.replace("_", " ")
            if readable in text:
                score += 2.5
            score += similar(text, f"{readable} {spec.description}") * 1.5
            if score > best_score:
                best_name, best_score = name, score
        if best_name is None or best_score < 0.35:
            return None
        return best_name, self._default_params(best_name, command)

    def _default_params(self, tool_name: str, command: str) -> Dict[str, Any]:
        """Fill obvious free-text parameters from the raw command."""
        spec = self._tools.get(tool_name)
        if not spec:
            return {}
        free_text_keys = {
            "query", "text", "command", "description", "prompt", "content", "task",
            "expression", "topic", "question", "brief", "term", "items", "duration",
            "pattern", "name",
        }
        params: Dict[str, Any] = {}
        cleaned = strip_command_prefix(command)
        for key, meta in spec.params.items():
            if meta.get("required") and meta.get("type", "string") == "string":
                if key in free_text_keys:
                    params[key] = cleaned
                    break
        return params


__all__ = ["BaseModule", "ModuleResult", "ToolSpec", "tool", "strip_command_prefix"]

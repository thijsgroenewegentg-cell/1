# /modules/macros.py
"""Macros: teach JARVIS fixed "when I say X, do Y" commands.

These are the opposite of the free-form assistant: a macro is a trigger
phrase tied to a canned reply and/or a fixed sequence of tool steps. It is
stored in plain JSON (``assistant.macros_file``) and, once armed, runs
before any model is asked — instant, reliable, works offline.

Management tools (add / list / remove) live here so the model can create
them from plain speech ("when I say goodnight, tell me to sleep well and
lock the screen"); the actual execution happens in :class:`core.brain.Brain`
so a macro can drive *any* module's tools.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import truncate


def _noop_normalize(value: str) -> str:
    """Fallback normaliser used only when core.macros cannot be imported."""
    return (value or "").strip().lower()


try:  # pragma: no cover - cosmetic import guard
    from core.macros import MacroStore, normalize
except Exception:  # pragma: no cover - import cycle guard
    MacroStore = None  # type: ignore[assignment,misc]
    normalize = _noop_normalize  # type: ignore[assignment]


class Macros(BaseModule):
    """Create, list and remove fixed trigger-phrase commands."""

    name = "macros"
    description = (
        "Macros are fixed 'when I say X, do Y' commands you teach JARVIS: a "
        "trigger phrase with a canned reply and/or tool steps. Use when the "
        "user wants something repeated to happen exactly the same way every "
        "time, without asking the model."
    )
    intent_examples: ClassVar[List[str]] = [
        "when i say goodnight, lock the screen",
        "create a macro called movie time that opens netflix",
        "what macros do I have",
        "remove the goodnight macro",
        "teach you a custom command",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Resolve the shared macro file and open the store.

        Args:
            config: The global configuration object.
            llm: Optional LLM client.
            security: Optional security guard.
        """
        super().__init__(config, llm=llm, security=security)
        store_cls = MacroStore
        if store_cls is None:  # pragma: no cover - cycle guard fallback
            from core.macros import MacroStore as store_cls  # type: ignore[assignment]
        self.store = store_cls(config.resolve(
            config.get("assistant.macros_file", "data/macros.json")
        ))

    # --------------------------------------------------------- offline router
    def offline_router(self, command: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Route macro management without a model.

        Listing and removal are deterministic; creating still needs the model
        because the definition is a JSON script of tool steps.

        Args:
            command: The raw utterance.

        Returns:
            ``(tool_name, params)`` or ``None`` to defer to keyword scoring.
        """
        text = strip_command_prefix(command)
        lowered = text.lower()
        if any(phrase in lowered for phrase in (
            "what macros", "list macros", "my macros", "show macros",
            "list commands", "show me the macros", "what commands do i have",
        )):
            return "list_macros", {}
        removal = re.search(
            r"\b(?:remove|delete|forget|unarm|drop|kill)\s+(?:the\s+|my\s+|that\s+)?"
            r"([\w -]+?)\s+macro\b",
            lowered,
        )
        if removal:
            trigger = removal.group(1).strip()
            if trigger:
                return "remove_macro", {"trigger": trigger}
        return None

    # ----------------------------------------------------------------- tools
    @tool(
        description=(
            "Create or replace a fixed 'when I say X, do Y' macro. "
            "'trigger' is the exact phrase (punctuation and 'please' are "
            "ignored when matching). 'definition' is a JSON object: "
            "{\"say\": \"canned reply\", \"steps\": [{\"tool\": "
            "\"module.tool\", \"params\": {...}}, {\"say\": \"a line\"}]}. "
            "Both are optional but at least one is required. Steps run in "
            "order and stop on the first failure."
        ),
        params={
            "trigger": {"type": "string", "description": "The phrase that fires the macro",
                        "required": True},
            "definition": {"type": "string",
                           "description": "JSON object: {say, steps}",
                           "required": True},
        },
        keywords=["when i say", "create a macro", "make a macro", "add a macro",
                  "teach you a command", "custom command", "set up a macro",
                  "when i tell you", "whenever i say"],
        examples=["when i say goodnight, lock the screen and say sweet dreams"],
    )
    async def add_macro(self, trigger: str, definition: str) -> ModuleResult:
        """Validate and store a macro from a JSON definition string.

        Args:
            trigger: The spoken phrase that fires the macro.
            definition: JSON with optional ``say`` and ``steps``.

        Returns:
            A :class:`ModuleResult` confirming what was stored.
        """
        trigger = (trigger or "").strip()
        try:
            payload = json.loads((definition or "").strip() or "{}")
            if not isinstance(payload, dict):
                raise ValueError("definition must be a JSON object")
        except Exception as exc:
            return ModuleResult.fail(
                f"The macro definition isn't valid JSON: {truncate(str(exc), 160)}"
            )
        say = str(payload.get("say", "") or "")
        steps = payload.get("steps", [])
        if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
            return ModuleResult.fail(
                "'steps' must be a JSON list of objects, each with 'tool' "
                "and optionally 'params' or 'say'."
            )
        try:
            entry = self.store.add(trigger, say=say, steps=steps)
        except ValueError as exc:
            return ModuleResult.fail(str(exc))
        count = len(entry["steps"])
        summary = (
            f"Armed, sir. When you say '{entry['trigger']}' I'll "
            + (f"say: {truncate(entry['say'], 80)} and " if entry["say"] else "")
            + f"run {count} step{'s' if count != 1 else ''}."
        )
        return ModuleResult(
            success=True,
            output=summary,
            speak=summary,
            data={"macro": entry},
        )

    @tool(
        description="List every armed macro and what it does.",
        params={},
        keywords=["what macros", "list macros", "my macros", "show macros",
                  "custom commands", "list commands"],
    )
    async def list_macros(self) -> ModuleResult:
        """Return a readable catalogue of the armed macros.

        Returns:
            A :class:`ModuleResult` naming each trigger and its script.
        """
        items = self.store.all()
        if not items:
            return ModuleResult(
                success=True,
                output="No macros armed yet. Say 'when I say X, do Y' to teach me one.",
                speak="No macros yet, sir.",
                data={"macros": []},
            )
        lines = []
        for item in items:
            trigger = item.get("trigger", "")
            uses = int(item.get("uses", 0))
            says = f" → \"{truncate(item.get('say', ''), 90)}\"" if item.get("say") else ""
            steps = "; ".join(
                s.get("tool", "say a line") for s in item.get("steps", [])
            )
            line = f"• \"{trigger}\"{says}"
            if steps:
                line += f"  [{steps}]"
            if uses:
                line += f"  (used {uses}×)"
            lines.append(line)
        body = f"{len(items)} macro(s) armed:\n" + "\n".join(lines)
        return ModuleResult(
            success=True,
            output=body,
            speak=f"{len(items)} macros armed.",
            data={"macros": items},
        )

    @tool(
        description="Delete a macro by its trigger phrase.",
        params={"trigger": {"type": "string", "description": "The phrase that fires it",
                            "required": True}},
        keywords=["remove the macro", "delete the macro", "forget that macro",
                  "remove macro", "delete macro", "unarm"],
        dangerous=True,
    )
    async def remove_macro(self, trigger: str) -> ModuleResult:
        """Remove the macro with this trigger.

        Args:
            trigger: The trigger phrase of the macro to forget.

        Returns:
            A :class:`ModuleResult` confirming the removal.
        """
        if self.store.remove(trigger):
            return ModuleResult.ok(f"Unarmed '{trigger}' — I'll forget that one.")
        return ModuleResult.fail(f"No macro matches '{trigger}' to remove.")


__all__ = ["Macros"]

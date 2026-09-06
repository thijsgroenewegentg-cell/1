# /core/planner.py
"""The ReAct loop: Reason, Act, Observe, repeat — then answer.

Given a classified intent, the planner shows the model only the tools of the
relevant module, asks it for one JSON step at a time, runs the tool it picks,
feeds the observation back into a scratchpad, and stops as soon as the answer
is in hand (or after :data:`MAX_REACT_STEPS`). Without a model it degrades to
calling the module's own deterministic router, so timers and screenshots keep
working.
"""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple

from core.intent_router import Intent
from modules.base import ModuleResult
from utils.helpers import extract_json, truncate
from utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from core.brain import Brain

logger = get_logger("core.planner")

#: How many Reason/Act cycles before the planner must answer with what it has.
MAX_REACT_STEPS = 4

#: Callback invoked with each token of a streamed reply.
TokenCallback = Callable[[str], Any]


class Planner:
    """Multi-step task execution against one module's toolset."""

    def __init__(self, brain: "Brain") -> None:
        """Attach the planner to a brain.

        Args:
            brain: The orchestrator that owns the modules and the model.
        """
        self.brain = brain

    async def run(
        self,
        text: str,
        intent: Intent,
        memory_context: str,
        on_token: Optional[TokenCallback] = None,
    ) -> str:
        """Run the Reason → Act → Observe loop, then compose the answer.

        Args:
            text: The user's request.
            intent: The classified intent (its module is the primary toolset).
            memory_context: Long-term memory block for the prompt.
            on_token: Optional streaming callback for the final answer.

        Returns:
            The final natural-language answer.
        """
        module = self.brain.modules.get(intent.module)
        if module is None:
            return await self.brain._converse(text, memory_context, on_token)

        # --- degraded mode: no LLM, drive the module directly ---------------
        if not self.brain.llm.available:
            result = await module.execute(text, {})
            if result.success:
                return result.output or "Done, sir."
            return f"{result.error or 'That did not work.'} (LLM offline — running on reflexes.)"

        transcript: List[str] = []
        observations: List[Tuple[str, ModuleResult]] = []
        catalog = self.brain.tool_registry(intent.module)

        for step in range(1, MAX_REACT_STEPS + 1):
            if self.brain._cancel.is_set():
                break
            prompt = self._react_prompt(text, catalog, transcript, step, memory_context)
            raw = await self.brain.llm.complete(
                prompt,
                system=self.brain.system_prompt(),
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
                return self.brain._finalize(str(answer))

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
            result = await self.brain.dispatch(reference, params)
            if result.untrusted:
                self.brain._tainted_by.add(reference)
                if result.injection:
                    self.brain._injection_notes.append(result.injection)
            observations.append((reference, result))
            transcript.append(f"Action: {reference} {json.dumps(params, default=str)[:200]}")
            transcript.append(f"Observation: {result.to_observation(900)}")
            logger.debug("Observation: %s", truncate(result.to_observation(300), 300))

            if result.success and self._is_terminal(reference, result):
                break

        return await self.brain._compose_answer(text, observations, memory_context, on_token)

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
            await self.brain._status(random.choice([
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


__all__ = ["MAX_REACT_STEPS", "Planner", "TokenCallback"]

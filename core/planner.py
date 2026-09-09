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
import re
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from core import toolcraft
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
        self.anaphora_turn = False

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
        # An anaphora intent ("again", "that file") is the brain re-pointing a
        # vague phrase at the module that handled the previous turn. The user
        # is not guessing a target — the target is last turn's — so the
        # confirm-your-guess gate must not nag here.
        self.anaphora_turn = bool(intent.method == "anaphora")

        # --- degraded mode: no LLM, drive the module directly ---------------
        # Routed calls go through brain.dispatch so they are recorded like any
        # other tool (context store, macro repeat tracking, result events);
        # only unrouteable text falls back to the module's plain executor.
        if not self.brain.llm.available:
            routed = getattr(module, "offline_router", None)
            reference = ""
            params: Dict[str, Any] = {}
            try:
                if callable(routed):
                    item = routed(text)
                    if item:
                        reference = str(item[0])
                        if len(item) > 1 and isinstance(item[1], dict):
                            params = dict(item[1])
            except Exception:
                reference = ""
            if reference:
                result = await self.brain.dispatch(
                    f"{module.name}.{reference}", params
                )
            else:
                result = await module.execute(text, {})
            if result.success:
                return result.output or "Done, sir."
            return f"{result.error or 'That did not work.'} (LLM offline — running on reflexes.)"

        # --- explicit "edit your code" needs no negotiation -----------------
        # The whole point of the module is that JARVIS rewrites himself, and a
        # small model asked to "plan the next step" will happily answer in
        # prose instead of calling the edit tool. When the user is *ordering*
        # an edit, run it directly: parse the target file out of the request
        # and let edit_own_code do the LLM rewrite, backup, tests and reload.
        if intent.module == "self_improve":
            direct = self._self_edit_request(text)
            if direct is not None:
                if not direct.get("path"):
                    # No file named. Asking for one beats attempting an edit of
                    # the project root (an empty path resolved to the whole
                    # directory, which Windows refuses to read as a file), so
                    # list the candidates instead of running a doomed tool.
                    listing = await self.brain.dispatch("self_improve.code_map", {})
                    body = truncate(listing.output, 1800) if listing.success else ""
                    ask = "Point me at the file, sir — name it and I will cut."
                    return f"{ask}\n\n{body}" if body else ask
                reference = "self_improve.edit_own_code"
                await self._status_for_tool(reference, 1)
                result = await self.brain.dispatch(reference, direct)
                if result.success:
                    return result.speak or result.output or "Done, sir."
                return result.error or result.output or "That did not work."

        transcript: List[str] = []
        observations: List[Tuple[str, ModuleResult]] = []
        catalog = self.brain.tool_registry(intent.module)

        # Fast/deep tiering: the first attempt runs on the main model. When a
        # decision cannot even be parsed, or a tool already failed, the next
        # attempt moves to ``llm.deep_model`` — the big model is spent only
        # when the cheap one already stumbled.
        model_override: Optional[str] = None
        escalated = False
        deep_model = str(self.brain.llm.deep_model or "").strip()

        def escalate() -> None:
            nonlocal model_override, escalated
            if deep_model and not escalated:
                model_override = deep_model
                escalated = True
                logger.debug("Escalating ReAct planning to the deep model (%s).", deep_model)

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
                model=model_override,
            )
            decision = extract_json(raw)

            # An unreadable decision on the main model earns one retry on the
            # deep model before we give up and fall back to a direct call.
            if not isinstance(decision, dict) and not escalated:
                escalate()
                if model_override:
                    logger.debug(
                        "ReAct step %d produced no JSON on the main model; "
                        "retrying on %s.", step, model_override,
                    )
                    raw = await self.brain.llm.complete(
                        prompt,
                        system=self.brain.system_prompt(),
                        temperature=0.1,
                        max_tokens=420,
                        json_mode=True,
                        model=model_override,
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
            # Go/no-go on the first tool when the plan looks like a guess.
            # The model can pick a plausible-but-wrong target ("city.blend"
            # when the user said "the donut scene"), which is exactly the
            # "he did something else than I asked" complaint. A quick confirm
            # catches it before anything runs.
            if not await self._confirm_plan(text, reference, params, step):
                note = f"{reference} with {params or 'no arguments'}".replace("'", "")
                return (f"Hold on — before I run anything I wanted to check the plan: {note}. "
                        "Tell me what to change and I'll go.")
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
            # The tool failed: give the deep model one chance to pick a better
            # next step instead of composing a defeat reply immediately.
            if not result.success:
                escalate()

        return await self.brain._compose_answer(text, observations, memory_context, on_token)

    @staticmethod
    def _self_edit_request(text: str) -> Optional[Dict[str, Any]]:
        """Extract an explicit self-edit order from the utterance, if there is one.

        Matched only after the intent has already been classified as
        ``self_improve``, so the phrases here are read in that context — "edit
        it" is JARVIS's own code being discussed, not a document on disk.

        Args:
            text: The user's request.

        Returns:
            ``edit_own_code`` parameters, or ``None`` when this is not an
            explicit order to rewrite his own code.
        """
        lowered = (text or "").lower()
        ordered = any(marker in lowered for marker in (
            "edit your", "rewrite your", "modify your", "change your code",
            "change your own", "fix your own", "fix your code",
            "improve your own", "improve yourself", "upgrade yourself",
            "rewrite yourself", "add a tool to yourself",
            "make your code", "make yourself", "update yourself",
        ))
        # Short follow-ups resolve through the conversation: "edit it",
        # "change it", "go ahead". The classifier only lands here when the
        # recent exchange was about JARVIS's own source.
        pointed = any(marker in lowered for marker in (
            "edit it", "edit that", "change it", "change that", "modify it",
            "fix it", "update it", "do it", "go ahead", "yes do it",
        ))
        if not (ordered or pointed):
            return None
        if not pointed and any(negation in lowered for negation in (
            "don't", "dont ", "do not", "never", "shouldn't", "wouldn't")):
            return None
        match = re.search(r"[A-Za-z_][\w./-]*\.py", text or "")
        return {"path": match.group(0) if match else "", "instruction": text or ""}

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
        recent = self.brain._context_hint()
        recent_block = f"RECENT ACTIVITY:\n{recent}\n\n" if recent else ""
        # Few-shot teaching: show the model how this user's kind of request
        # maps onto real calls for the active module (see core/toolcraft).
        worked = toolcraft.worked_examples(
            self.brain.last_intent.module if self.brain.last_intent else "",
            exclude_text=text,
        )
        worked_block = ""
        if worked:
            lines = ["WORKED EXAMPLES (study the mapping — same shape for your call):"]
            lines += [
                f'- USER: "{phrase}"\n  CALL: {call}'
                for phrase, call in worked
            ]
            worked_block = "\n".join(lines) + "\n\n"
        return (
            "You are the reasoning core of JARVIS. Decide the next step.\n\n"
            f"TOOLS:\n{catalog}\n\n"
            + worked_block
            + (f"MEMORY:\n{memory_context}\n\n" if memory_context else "")
            + recent_block
            + f"USER REQUEST: {text}\n\n"
            f"SCRATCHPAD (step {step} of {MAX_REACT_STEPS}):\n{history}\n\n"
            "Reply with ONLY a JSON object:\n"
            '{"thought": "one short sentence of reasoning", '
            '"action": "module.tool or null", "params": {}, '
            '"answer": "final answer if no tool is needed, else null"}\n\n'
            "Answer format: action must be a module.tool listed in TOOLS; "
            "params must name ONLY that tool's parameters. If the answer is "
            "already in hand or no tool would improve it, set action to null "
            "and answer directly — do not call a tool for its own sake.\n"
            + toolcraft.golden_block()
            + "\nRe-read the USER REQUEST before deciding: only call a tool "
            "that moves you toward what was literally asked. If the request "
            "is vague, names no file/app/parameter, or cannot be satisfied "
            "with the tools above, do NOT guess — set action to null and ask "
            "one short question for the missing detail."
        )

    async def _confirm_plan(
        self, text: str, reference: str, params: Dict[str, Any], step: int
    ) -> bool:
        """Ask before running a tool whose target the user never named.

        The heuristic is deliberately narrow so it does not nag on every turn:
        only the *first* tool of a turn is considered, the request must have
        been vague enough to allow a wrong guess (it names no file, no .blend,
        no app), the tool must carry a file-like parameter, and confirmations
        must be switched on. When all hold, the user is asked to approve the
        concrete plan — catching "render city.blend" when they meant the donut.

        Args:
            text: The user's request.
            reference: ``module.tool`` about to run.
            params: The parameters chosen for it.
            step: The ReAct step (only step 1 is worth interrupting).

        Returns:
            True when the tool may run (or nothing needs asking).
        """
        if step != 1:
            return True
        if getattr(self, "anaphora_turn", False):
            # "again, but slower" already names its target implicitly — last
            # turn's. Confirming would be nagging.
            return True
        if not self.brain.config.get("assistant.confirm_plan", True):
            return True
        security = getattr(self.brain, "security", None)
        if security is None or not getattr(security, "confirm_dangerous", True):
            return True
        # The user already named the concrete target — no guess involved.
        lowered = (text or "").lower()
        words = set(re.findall(r"[a-z0-9_.]+", lowered))
        file_keys = ("path", "file", "blend", "blend_file", "app", "url",
                     "repo", "script", "name", "target")
        concrete: Dict[str, str] = {}
        for key, value in (params or {}).items():
            if not isinstance(value, str) or not value.strip():
                continue
            stripped = value.strip()
            if key in file_keys or (len(stripped) >= 4 and "." in stripped):
                concrete[key] = stripped
        if not concrete:
            return True
        # A target mentioned verbatim in the request is not a guess.
        if any(self._target_mentioned(token, words) for token in concrete.values()):
            return True
        summary = ", ".join(f"{key}={value}" for key, value in concrete.items())
        try:
            approved = await security.confirm(
                f"Run {reference} with {summary}? You didn't name that file — "
                "just checking before I touch it."
            )
        except Exception:
            approved = False
        return approved

    @staticmethod
    def _target_mentioned(token: str, words: set) -> bool:
        """Whether the user's words contain the concrete target."""
        token = token.strip().lower()
        if not token:
            return True
        return any(part and part in words for part in re.split(r"[/\\_.]", token))

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

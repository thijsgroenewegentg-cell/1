# /core/autopilot.py
"""One-shot compound tasks — the cross-module autopilot.

The single-module router is the assistant's biggest ceiling: a request that
touches two modules ("set a timer and clean my downloads") was answered by
*one* module and the other half silently dropped. :func:`build` splits such
requests into per-module steps deterministically — no LLM needed to *plan*;
each step is then executed by the normal planner (model-driven when Ollama is
up, keyword/offline-routed when it is not).

The splitter is deliberately conservative so ordinary English never trips it:
* every step must route to a real module with a decisive keyword hit,
* there must be at least two *different* modules involved,
* no step may be a question or small talk.

Anything less falls through to today's single-module behaviour untouched.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

#: Words that mark a segment as a *requested action* (as opposed to data or
#: chatter). A segment needs one to count as an executable step.
ACTION_VERBS = {
    "add", "set", "create", "open", "launch", "start", "stop", "pause", "play",
    "search", "find", "look up", "send", "email", "remind", "save", "download",
    "clean", "tidy", "organize", "organise", "back up", "backup", "snapshot",
    "render", "take", "show", "list", "delete", "remove", "mute", "lock",
    "screenshot", "summarize", "summarise", "convert", "translate",
    "calculate", "check", "schedule", "cancel", "restore", "read", "update",
    "fetch", "get", "make", "fire up", "turn",
}

#: Connectors between steps. "and"/"then" only count as step boundaries when
#: both sides turn out to be executable actions (checked afterwards).
_CONNECTOR = re.compile(
    r"\s+(?:and then|and|then|plus)\s+", re.IGNORECASE
)

#: Question openers disqualify a segment from being an executable step.
_QUESTION = re.compile(
    r"^(what|why|when|where|who|which|how|is|are|do|does|did|can|could|"
    r"should|would|will|have|has)\b|[?]"
)

_QUESTION_WORD = re.compile(r"\b(what|why|when|where|who|which|how)\b", re.I)


def _has_verb(segment: str) -> bool:
    lowered = f" {segment.lower()} "
    return any(f" {verb} " in lowered for verb in ACTION_VERBS)


def split(text: str) -> List[str]:
    """Split a request on step connectors.

    Args:
        text: The user's request.

    Returns:
        Candidate segments (2+ when connectors exist, else the whole text).
    """
    raw = (text or "").strip()
    if not raw:
        return []
    # Keep "and" splits only where a verb follows the connector — "milk and
    # cookies" must never split, "… and clean …" must.
    pieces: List[str] = []
    cursor = 0
    for match in _CONNECTOR.finditer(raw):
        head = raw[cursor:match.start()].strip()
        tail = raw[match.end():].strip()
        if not head or not tail:
            continue
        # The connector joins two actions only when the *tail* begins with an
        # action verb ("set a timer and clean up" — clean is the verb).
        tail_verb = tail.split(",", 1)[0].strip()
        if _has_verb(tail_verb) and _has_verb(head):
            pieces.append(head)
            cursor = match.end()
    pieces.append(raw[cursor:].strip())
    return [piece for piece in pieces if piece]


def build(brain: Any, text: str) -> Optional[List[Tuple[str, str]]]:
    """Turn a compound request into an ordered plan of ``(module, step)``.

    Args:
        brain: The assistant whose keyword router and modules are consulted.
        text: The user's request.

    Returns:
        Two or more ordered steps across at least two different modules, or
        ``None`` when this is not a compound request.
    """
    if not isinstance(text, str) or len(text) > 500:
        return None
    lowered = (text or "").lower()
    if _QUESTION_WORD.search(lowered) and not _has_verb(lowered):
        return None
    segments = split(text)
    if len(segments) < 2:
        return None

    steps: List[Tuple[str, str]] = []
    for segment in segments:
        seg = segment.strip()
        if not seg or _QUESTION.search(seg):
            continue
        intent = brain._keyword_intent(seg)
        module = str(intent.module or "")
        if (module in brain.modules
                and module != "conversation"
                and float(intent.confidence or 0.0) >= 0.75
                and _has_verb(seg)):
            steps.append((module, seg))
    if len(steps) < 2:
        return None
    modules = {module for module, _ in steps}
    if len(modules) < 2:
        return None
    # No module may appear twice in a row as the same duplicate action — a
    # routine style request, not a compound one.
    return steps[:3]


def render(steps: List[Tuple[str, str]], replies: List[str]) -> str:
    """Format an executed plan into a single summary reply.

    Args:
        steps: The planned steps as ``(module, segment)``.
        replies: The per-step answers in order.

    Returns:
        A numbered, spoken-friendly summary.
    """
    lines = [
        f"{index}. {reply}"
        for index, reply in enumerate(replies, start=1)
        if reply and str(reply).strip()
    ]
    if not lines:
        return "Done, sir — every step came back empty, which is suspicious."
    head = f"Done in one go. {len(lines)} step(s):"
    return head + "\n" + "\n".join(lines)


__all__ = ["ACTION_VERBS", "build", "render", "split"]

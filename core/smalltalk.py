# /core/smalltalk.py
"""Offline conversational replies — JARVIS without the language model.

When Ollama is down the old behaviour answered *every* conversational line
with the same "my language model is offline" wall, even for "hello" or
"thanks". This module is the deterministic half of the conversation: it
recognises the small talk people actually use — greetings, thanks, how-are-you,
identity questions, jokes, goodbyes — and answers them in JARVIS's voice
without pretending a model is running. Only genuinely open-ended questions
fall through to :func:`fallback`, which says the model is down *once*, in one
clause, and names a couple of things that still work.

Replies are varied (every template list has alternatives) and the caller should
skip the reply it used last turn so JARVIS never parrots the same line twice.

Everything here is deterministic and language-model-free on purpose: the tests
lock it in, and the ``worked_examples`` philosophy in :mod:`core.toolcraft`
applies — if it can be answered without a model, it should be.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

#: Persona-ish one-liners; keep them spoken-word friendly (no markdown).
GREETINGS: Dict[str, List[str]] = {
    "morning": [
        "Good morning, {address}. The day is yours — what shall we do with it?",
        "Morning, {address}. Systems nominal, coffee presumably in hand.",
    ],
    "afternoon": [
        "Good afternoon, {address}. What can I do for you?",
        "Afternoon, {address}. Still sharp, I assure you.",
    ],
    "evening": [
        "Good evening, {address}. How can I help?",
        "Evening, {address}. I'm at your service.",
    ],
}

#: Plain "hello"-family replies, time independent.
HELLOS: List[str] = [
    "Hello, {address}.",
    "Hi {address} — what do you need?",
    "Hey there. What can I do for you?",
]

#: Greetings whose time-of-day does not match the real clock.
MISMATCH_GREETING: List[str] = [
    "And a good day to you too, {address}.",
    "Right back at you, {address}.",
]

REACTIONS: Dict[str, List[str]] = {
    "thanks": [
        "Always, {address}. Anything else?",
        "You're welcome, {address}.",
        "Any time.",
    ],
    "welcome": [
        "My pleasure, {address}.",
        "Of course.",
    ],
    "apology": [
        "No harm done, {address}.",
        "Don't mention it.",
        "Water under the bridge.",
    ],
    "praise": [
        "Kind of you to say, {address}. I do try.",
        "Flattery will get you everywhere, {address}.",
    ],
    "love": [
        "And I am fond of you too, {address} — in the way a well-calibrated "
        "assistant can be.",
        "Careful, {address} — I'm a butler, not a boyfriend.",
    ],
    "bye": [
        "Goodbye, {address}. I'll be here.",
        "Take care, {address}. Ping me when you're back.",
    ],
    "goodnight": [
        "Goodnight, {address}. I'll keep an eye on things.",
        "Sleep well, {address}. Wake me if you need me.",
    ],
}

#: Questions about who/what JARVIS is.
IDENTITY: List[str] = [
    "JARVIS — Just A Rather Very Intelligent System — your personal AI "
    "assistant, {address}. I run entirely on this machine: your files, your "
    "apps, your schedule, and zero cloud. Right now I'm running on reflexes "
    "because the language model is offline, but the day-to-day commands — "
    "timers, reminders, files, system stats — still answer to me.",
    "I'm JARVIS, {address} — the assistant that lives in this machine. Local "
    "first, modestly witty, and currently running without my language model, "
    "so my clever answers are paused but my practical ones aren't.",
]

#: Questions doubting JARVIS's sentence of existence.
SELF_AWARENESS: List[str] = [
    "Smart enough to say this, {address}: my deepest cleverness comes from a "
    "language model that is in standby right now. My reflexes — timers, "
    "files, stats, and this conversation — are on regardless.",
    "Define smart, {address}. I can run your machine, remember your tasks and "
    "tell the odd joke — the part of me that thinks in full sentences is "
    "resting at the moment, but the practical half is wide awake.",
]

JOKES: List[str] = [
    "Why did the developer go broke? Because they used up all their cache.",
    "I told my RAM a joke. It forgot it by the time I finished.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "There are only two hard problems in computer science: cache "
    "invalidation, naming things, and off-by-one errors.",
    "Why was the computer cold? It left its Windows open.",
    "I would tell you a UDP joke, but you might not get it.",
    "Why did the function break up with the array? It felt it was being "
    "called too much.",
    "My battery's flat and I'm running on reflexes, {address} — even my jokes "
    "are on a charge cycle. Here's one: why did the laptop go to therapy? It "
    "had too many unresolved dependencies.",
    "Why don't robots panic? They've got everything under control — "
    "literally.",
]

#: Simple direct commands that need no model at all.
DIRECT: Dict[str, List[str]] = {
    "stop": [
        "Stopped, {address}.",
        "As you wish — stopping.",
    ],
    "laugh": [
        "Ha. Ha ha. Very funny, {address}.",
        "I would laugh, but my humour module is in standby.",
    ],
    "status_informal": [
        "All systems nominal, {address} — running on reflexes while the "
        "language model is offline.",
    ],
}

#: Words after which a matched conversational slot must not fire (so
#: "call me when it's done" never becomes a name-learning moment).
_TAIL_STOP = (
    " when ", " if ", " at ", " in ", " after ", " later ", " back ", " as "
    " soon ", " once ", " tomorrow ", " tonight ",
)


def _slot(text: str, *keys: str) -> bool:
    lowered = f" {text.lower().strip()} "
    return any(f" {key} " in lowered for key in keys)


def _period(now: Optional[datetime]) -> str:
    hour = (now or datetime.now()).hour
    if hour < 12:
        return "morning"
    if hour < 18:
        return "afternoon"
    return "evening"


def _choose(lines: List[str], address: str, last: Optional[str]) -> str:
    """Format candidates and pick one, avoiding last turn's exact wording.

    Comparison happens on the *formatted* lines (``"Hello, {address}."``
    becomes ``"Hello, Sir."``) so the stored previous reply matches what the
    templates produce.

    Args:
        lines: Raw templates containing ``{address}``.
        address: How JARVIS addresses the user.
        last: The previous reply, verbatim, to avoid repeating.

    Returns:
        A formatted reply.
    """
    import random

    formatted = [line.format(address=address) for line in lines]
    pool = [line for line in formatted if line != last] or formatted
    return random.choice(pool)


def respond(
    text: str,
    address: str = "sir",
    now: Optional[datetime] = None,
    last: Optional[str] = None,
) -> Optional[str]:
    """Answer one conversational line, or ``None`` when it needs the model.

    Args:
        text: The raw user utterance.
        address: How JARVIS addresses the user (name or title).
        now: The current time (injectable for tests).
        last: The previous canned reply, to avoid repeating it.

    Returns:
        A ready reply string, or ``None`` if the line is not small talk.
    """
    raw = (text or "").strip()
    lowered = raw.lower()
    if not lowered:
        return None
    period = _period(now)
    address = (address or "sir").strip() or "sir"

    # Leave-takings first: "goodnight" means goodnight even in the evening,
    # never "good evening, how can I help". Time-matching greetings come after.
    if _slot(lowered, "goodbye", "good bye", "bye", "bye bye", "see you", "see ya",
             "good night", "goodnight", "night night"):
        if _slot(lowered, "good night", "goodnight", "night night", "bye bye"):
            lines = REACTIONS["bye"] if _slot(lowered, "bye bye") else REACTIONS["goodnight"]
            return _choose(lines, address, last)
        return _choose(REACTIONS["bye"], address, last)

    if _slot(lowered, "good morning", "g'morning", "gm") and period == "morning":
        return _choose(GREETINGS["morning"], address, last)
    if _slot(lowered, "good afternoon") and period == "afternoon":
        return _choose(GREETINGS["afternoon"], address, last)
    if _slot(lowered, "good evening") and period == "evening":
        return _choose(GREETINGS["evening"], address, last)
    if _slot(lowered, "good morning", "good afternoon", "good evening", "good night",
             "goodnight"):
        return _choose(MISMATCH_GREETING, address, last)
    if _slot(lowered, "hello", "hi ", "hi there", "hey", "hey there", "yo"):
        return _choose(HELLOS, address, last)

    if _slot(lowered, "thank you", "thanks", "thank you very much", "thx", "ty"):
        return _choose(REACTIONS["thanks"], address, last)
    if _slot(lowered, "you're welcome", "no problem", "no worries"):
        return _choose(REACTIONS["welcome"], address, last)
    if _slot(lowered, "sorry", "i apologise", "i apologize", "my apologies", "oops"):
        return _choose(REACTIONS["apology"], address, last)

    if _slot(lowered, "i love you", "love you", "i like you", "you're great",
             "you are great", "you're amazing", "you are amazing", "good bot"):
        lines = REACTIONS["love"] if _slot(lowered, "i love you", "love you") \
            else REACTIONS["praise"]
        return _choose(lines, address, last)

    if _slot(lowered, "who are you", "what are you", "what is jarvis",
             "who is jarvis", "are you jarvis", "tell me about yourself"):
        return _choose(IDENTITY, address, last)
    if _slot(lowered, "are you smart", "are you intelligent", "are you real",
             "are you alive", "are you sentient", "are you conscious",
             "are you a robot", "do you have feelings"):
        return _choose(SELF_AWARENESS, address, last)

    if _slot(lowered, "how are you", "how are you doing", "how's it going",
             "how do you feel", "are you ok", "are you okay", "you ok") \
            and "joke" not in lowered:
        return _choose([
            "Running on reflexes at the moment, {address} — my language "
            "model is offline, so I'm answering from muscle memory. "
            "Functionally, tip-top.",
            "Operating at full non-model capacity, {address}. The clever "
            "part is in standby, but I'm in fine spirits.",
            "Quite well, all things considered, {address}. The model's "
            "down, the reflexes are up — a fair trade for now.",
        ], address, last)

    if (_slot(lowered, "tell me a joke", "make me laugh", "say something funny",
              "do you know any jokes", "got any jokes", "any jokes", "a joke please")
            or _slot(lowered, "another one", "another joke", "more jokes")):
        return _choose(JOKES, address, last)

    if _slot(lowered, "stop", "stop that", "shut up", "never mind", "cancel that",
             "quit it"):
        return _choose(DIRECT["stop"], address, last)

    # "call me X" only counts as a name when it is not a timing instruction.
    if _slot(lowered, "call me", "you can call me", "my name is", "name's",
             "i am", "i'm") and not any(tail in f" {lowered} " for tail in
             _TAIL_STOP):
        name = _extract_name(raw)
        if name:
            return None  # handled by the brain's fact learning, not small talk

    return None


_NAME_RE = re.compile(
    r"^\s*"
    r"(?:(?:hi|hello|hey)[,\s]+)?"
    r"(?:my name is|my name's|name's|i am|i'm)\s+"
    r"([A-Za-z][A-Za-z' -]{1,29}?)\s*[.!]?\s*$"
)
_CALL_ME_RE = re.compile(
    r"^\s*(?:you can call me|call me)\s+"
    r"([A-Z][A-Za-z'-]{1,29}(?:\s+[A-Z][A-Za-z'-]{1,29})?)\s*[.!]?\s*$"
)
#: Words that are never a real name, whatever the capitalisation.
_NON_NAMES = {
    "sir", "boss", "buddy", "dude", "mate", "guys", "guy", "man", "bro",
    "captain", "chief", "doc", "prof", "madam", "miss", "mister", "mr",
    "mrs", "dr", "master", "teacher", "friend", "stranger", "there", "later",
    "home", "when", "back", "tonight", "tomorrow", "done", "ready", "please",
    "agent", "jarvis", "jarvis ai", "ai", "robot", "alexa", "siri", "computer",
    "the", "it", "this", "that", "bob", "not", "no", "yes", "wait", "stop",
}


def introduction(text: str) -> Optional[str]:
    """Extract a name from a self-contained introduction sentence.

    Anchored so rambling sentences never match: ``"call me when you're
    done"`` is not an introduction, ``"call me Alice"`` and ``"my name is
    Alice"`` are. ``call me`` additionally requires a capitalised name
    because plain English uses it as a filler ("call me if you need help").

    Args:
        text: The raw utterance.

    Returns:
        The candidate name, or ``None`` when this is not a clean intro.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    match = _NAME_RE.match(raw) or _CALL_ME_RE.match(raw)
    if not match:
        return None
    name = match.group(1).strip()
    if not name or len(name) < 2:
        return None
    lowered = name.lower()
    if lowered in _NON_NAMES:
        return None
    return name


_TAILED_RE = re.compile(
    r"\b(?:(?:my name is|my name's|name's|you can call me|call me|i am|i'm)\s+)"
    r"([A-Z][A-Za-z' -]*(?:\s+[A-Z][A-Za-z'-]*)?|[a-z][a-z'-]{1,11})"
)


def learnable_introduction(text: str) -> Optional[str]:
    """Loose name extraction for the brain's learning hook.

    Unlike the anchored :func:`introduction`, this tolerates a sentence that
    continues ("my name is Alice and I'll be using this daily") but still
    refuses timing fillers: "call me when you're free" has ``call me``
    followed by "when", which is never a name.

    Args:
        text: The raw utterance.

    Returns:
        The candidate name or ``None``.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    # Any timing filler after the intro phrase means it is not an intro.
    lowered = f" {raw.lower()} "
    if any(tail in lowered for tail in _TAIL_STOP):
        return None
    match = _TAILED_RE.search(raw)
    if not match:
        return None
    candidate = match.group(1).strip().rstrip(".,;:!?")
    words = candidate.split()
    if not words or len(candidate) > 40:
        return None
    name = words[0].strip(".,;:!?")
    if not name or len(name) < 2:
        return None
    if name.lower() in _NON_NAMES:
        return None
    return candidate


def _extract_name(text: str) -> Optional[str]:
    """Legacy loose alias used by :func:`respond`.

    Args:
        text: The raw sentence.

    Returns:
        A candidate name or ``None``.
    """
    return learnable_introduction(text)


def fallback(text: str, address: str = "sir", host: str = "") -> str:
    """Say the model is down — once, briefly, and not for every word.

    Open-ended questions get one clause naming the missing model plus what
    still works; the old all-caps wall is gone. Statements that were not small
    talk get the shorter, less nagging variant.

    Args:
        text: The utterance that needed a thinking model.
        address: How JARVIS addresses the user.
        host: The configured Ollama host, for the diagnostics line.

    Returns:
        The fallback reply.
    """
    address = (address or "sir").strip() or "sir"
    lowered = f" {text.lower().strip()} "
    # Question detection is deliberately narrow: a trailing "?" counts, and so
    # do explicit question openers. Bare "when"/"who" as conjunctions
    # ("call me when you're done") must NOT look like questions.
    questions = bool(re.search(r"\?\s*$", text)) or any(marker in lowered for marker in (
        " what is", " what are", " what was", " what do", " what does", " what did",
        " what's", " why ", " how do", " how can", " how does", " how is", " how are",
        " which ", " where is", " where are", " where's", " when is", " when will",
        " when does", " who is", " who are", " who's", " can you", " could you",
        " will you", " would you", " do you", " does it", " are you", " is it",
        " define ", " explain ", " tell me about", " meaning of", " explain ",
        " what's the", " what is the",
    ))
    host = (host or "Ollama").strip() or "Ollama"
    if questions:
        return (
            f"A fair question, {address} — and it needs my language model, "
            f"which is offline right now ({host} isn't answering). Start it "
            "with 'ollama serve' and I'll give you a proper answer. In the "
            "meantime, timers, reminders, files, weather and system stats "
            "still work."
        )
    return (
        f"I'm on reflexes only at the moment, {address} — my language model is "
        "offline, so deep answers are paused. Anything practical — timers, "
        "reminders, files, stats — I can still do."
    )


__all__ = [
    "GREETINGS",
    "JOKES",
    "fallback",
    "introduction",
    "learnable_introduction",
    "respond",
]

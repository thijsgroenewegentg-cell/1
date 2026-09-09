# /core/corrections.py
"""Turn the user's corrections into durable standing rules.

JARVIS used to handle "no, the other file" for the moment and then forget it
the next turn. This module recognises *standing* corrections — statements of
the shape "don't use X", "use X instead", "I prefer X", "never do X", "I
don't like X", "I meant X" — and turns them into one-line rules the brain
stores in the durable profile and injects into every future system prompt.
One-off chatter ("don't worry about it") is filtered out before it can
become a rule.

The parser is intentionally template-based and model-free: a correction it
cannot recognise confidently is simply ignored rather than guessed.
"""

from __future__ import annotations

import re
from typing import Optional

#: Social noise that looks like an instruction but must never be stored.
_SOCIAL_NOISE = (
    "don't worry", "dont worry", "do not worry", "no problem", "no worries",
    "no need", "never mind", "nevermind", "don't mention", "dont mention",
    "don't bother", "dont bother", "no thanks", "not now", "that's fine",
    "that's ok", "that's okay", "it's fine", "its fine", "no comment",
    "sorry", "my apologies",
)

#: Patterns, each producing a rule template ``{subject}``. First match wins.
_PATTERNS = (
    # "don't use miles" / "never use the word dude"
    (re.compile(r"\b(?:don'?t|do not|never|stop)\s+use\s+(.+?)\s*[.!]?$", re.I),
     "Don't use {0}."),
    # "use miles instead" / "use km instead of miles"
    (re.compile(r"\buse\s+(.+?)\s+instead\b", re.I),
     "Use {0} instead."),
    # "I prefer miles" / "I'd prefer celsius"
    (re.compile(r"\b(?:i'?d\s+prefer|i\s+prefer)\s+(.+?)\s*[.!]?$", re.I),
     "Prefer {0}."),
    # "never schedule on weekends" / "don't schedule on weekends"
    (re.compile(r"\b(?:never|don'?t|do not)\s+([a-z]+)\s+on\s+(.+?)\s*[.!]?$", re.I),
     "Never {0} on {1}."),
    # "I don't like surprises" / "I don't like it loud"
    (re.compile(r"\bi\s+don'?t\s+like\s+(.+?)\s*[.!]?$", re.I),
     "Avoid {0}."),
    # "I meant the other file" / "actually, I meant Paris"
    (re.compile(r"\bi\s+meant\s+(.+?)\s*[.!]?$", re.I),
     "Remember: {0}."),
    # "call it X" — a naming preference, e.g. "call it the bridge renderer"
    (re.compile(r"\bcall\s+it\s+([a-z][\w .-]*?)\s*[.!]?$", re.I),
     "Call it {0}."),
)

#: Words that make a captured subject too vague to be a useful rule.
_VAGUE = {"it", "that", "that one", "this", "this one", "them", "those",
          "stuff", "things", "thing", "the other one", "the wrong one"}


def parse(text: Optional[str]) -> Optional[str]:
    """Recognise one standing correction and normalise it into a rule.

    Args:
        text: The user's utterance.

    Returns:
        A short rule sentence, or ``None`` when the utterance is not a
        confident standing correction.
    """
    if not text:
        return None
    lowered = (text or "").strip().lower()
    if any(noise in lowered for noise in _SOCIAL_NOISE):
        return None
    if "?" in text:
        return None
    for pattern, template in _PATTERNS:
        match = pattern.search(text.strip())
        if not match:
            continue
        subject = match.group(1).strip().strip(".,;:!?")
        if len(match.groups()) > 1:
            second = match.group(2).strip().strip(".,;:!?")
            rule = template.format(subject, second)
        else:
            rule = template.format(subject)
        if subject.lower() in _VAGUE or len(subject) < 2 or len(rule) > 120:
            continue
        # Capitalise the first letter so the rule reads well in a prompt.
        return rule[:1].upper() + rule[1:]
    return None


__all__ = ["parse"]

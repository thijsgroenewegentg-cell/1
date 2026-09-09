# /core/healer.py
"""Self-healing retries — turn logged failures into corrected second tries.

When a tool fails ("open the file report.pdf" but it moved) JARVIS records
the failure — and can now act on it:

* ``try that again`` replays the newest failed request through the normal
  planner once the cause is fixed;
* when the failed request pointed at a file/folder that no longer exists,
  :func:`candidates` proposes the closest real matches so JARVIS can offer a
  corrected variant instead of failing the same way twice.

Pure local heuristics; no model, no network.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Optional

from core import failures
from utils.logger import get_logger

logger = get_logger("core.healer")

#: Words that reveal a file/folder was the subject of the request.
_PATH_WORDS = ("open", "read", "show", "play", "delete", "remove", "move",
               "convert", "send", "attach", "clean", "organise", "organize",
               "backup", "back up", "print", "copy", "edit", "run",
               "openen", "lees", "lees voor", "speel", "verwijder", "wis",
               "verplaats", "kopieer", "opruimen", "open")


def latest(config: Any) -> Optional[dict]:
    """The most recent failure record, if any."""
    records = failures.recent(config, limit=1)
    return records[0] if records else None


def referenced_path(text: str) -> Optional[Path]:
    """The file/folder a failed request was about, when it named one.

    Args:
        text: The user's original request.

    Returns:
        The path as typed (may be relative), or ``None``.
    """
    lowered = f" {str(text or '').lower()} "
    if not any(f" {word} " in lowered or lowered.startswith(f"{word} ")
               for word in _PATH_WORDS):
        return None
    for candidate in re.findall(
        r"(?:~|\.\.?/|/|(?:[A-Za-z]:[\\/]))"
        r"[\w .\-äöüéèß/@()'\"{}[\]%+#~]+",
        str(text or ""),
    ):
        cleaned = candidate.strip().strip("'\"")
        if len(cleaned) > 2:
            return Path(cleaned).expanduser()
    # No path-like token: fall back to a quoted name ("open 'report.pdf'").
    quoted = re.search(r"['\"]([^'\"]{2,80})['\"]", str(text or ""))
    if quoted:
        return Path(quoted.group(1).strip()).expanduser()
    return None


def candidates(config: Any, failure: dict, max_results: int = 3) -> List[str]:
    """Similar files/folders near the path a failed request named.

    Args:
        config: Configuration (unused, kept for parity with the other stores).
        failure: A failure record.
        max_results: How many matches to return.

    Returns:
        Suggested corrected paths, newest-ish order, or ``[]`` when nothing
        useful exists near the named path.
    """
    request = str(failure.get("text", ""))
    path = referenced_path(request)
    if path is None:
        return []
    folder = path.parent if path.parent and str(path.parent) != "." else None
    stem = path.stem.lower()
    if folder is None or not folder.exists():
        return []
    matches: List[str] = []
    try:
        for sibling in sorted(folder.iterdir()):
            lower = sibling.name.lower()
            if stem and (lower.startswith(stem[:6]) or stem in lower):
                matches.append(str(sibling))
            if len(matches) >= max_results:
                break
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("Healer candidate scan failed: %s", exc)
    return matches


def advice(config: Any, failure: dict, language: str = "en") -> Optional[str]:
    """One human suggestion for what to try next after a failure.

    Args:
        config: Configuration.
        failure: A failure record.
        language: ``"nl"`` or anything else (English).

    Returns:
        A ready suggestion line, or ``None`` when there is nothing obvious.
    """
    dutch = language == "nl"
    similar = candidates(config, failure)
    error = str(failure.get("error", ""))[:120]
    request = str(failure.get("text", ""))[:90]
    if similar:
        listing = "\n".join(f"  • {match}" for match in similar[:3])
        if dutch:
            return (
                f"De vorige poging ({request!r}) faalde met: {error}. "
                "Ik vond bestanden die erop lijken:\n"
                f"{listing}\nZeg 'probeer opnieuw' nadat je het juiste pad "
                "hebt gegeven, of herhaal je vraag met een van deze namen."
            )
        return (
            f"The last attempt ({request!r}) failed with: {error}. I found "
            "things that look similar:\n"
            f"{listing}\nSay 'try that again' after giving the right path, "
            "or repeat your request with one of these names."
        )
    if dutch:
        return (
            f"Zeg 'probeer opnieuw' zodra je de oorzaak hebt verholpen; de "
            f"laatste poging ({request!r}) faalde met: {error}."
        )
    return (
        f"Say 'try that again' once you have fixed the cause; the last "
        f"attempt ({request!r}) failed with: {error}."
    )


__all__ = ["advice", "candidates", "latest", "referenced_path"]

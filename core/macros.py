# /core/macros.py
"""Persistent voice macros: "when I say X, do Y".

A macro is a trigger phrase with a fixed script — a canned reply and/or a
list of tool steps. Running one never touches the LLM, so macros are
instant, deterministic and work even when Ollama is down. That is the point
of them: the things you say every day ("goodnight", "movie time") should
not wait on a model to figure out what you meant.

Storage is a plain JSON file (``assistant.macros_file``) so it is easy to
inspect, back up and edit by hand. The :mod:`modules.macros` module exposes
add/list/remove tools, and :class:`core.brain.Brain` checks the trigger
table before any intent classification.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Words that can pad the front of a spoken trigger without changing it.
_FILLER = (
    "hey jarvis", "ok jarvis", "jarvis", "please", "hey", "okay",
    "ok", "yo jarvis",
)


def normalize(text: str) -> str:
    """Lower-case, strip punctuation and filler so triggers match speech.

    Punctuation is dropped *before* the filler words are peeled off, so
    "hey jarvis, goodnight please!" becomes ``"goodnight"`` exactly like the
    armed trigger "goodnight" does.
    """
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    changed = True
    while changed:
        changed = False
        for filler in _FILLER:
            if cleaned == filler:
                cleaned = ""
                changed = True
                continue
            if cleaned.startswith(f"{filler} "):
                cleaned = cleaned[len(filler):].strip()
                changed = True
            elif cleaned.endswith(f" {filler}"):
                cleaned = cleaned[: -len(filler)].strip()
                changed = True
    cleaned = re.sub(r"^(please|can you)\s+", "", cleaned).strip()
    return cleaned


class MacroStore:
    """Load and save the macro table.

    Args:
        path: Where the JSON file lives.
    """

    def __init__(self, path: Path) -> None:
        """Load the macro table.

        Args:
            path: Where the JSON file lives.
        """
        self.path = Path(path)
        self._data: Dict[str, Any] = self._load()
        self._mtime: Optional[float] = None
        try:
            self._mtime = self.path.stat().st_mtime
        except Exception:
            self._mtime = None

    def _load(self) -> Dict[str, Any]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text("utf-8", errors="replace"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {"macros": []}

    def _refresh(self) -> None:
        """Re-read the file when someone else (another store) rewrote it.

        The brain and the macros module keep their own :class:`MacroStore`
        instances over the same file, so a trigger added through a tool must
        be visible to the brain's matcher without a restart.
        """
        try:
            stamp = self.path.stat().st_mtime
        except Exception:
            return
        if stamp != self._mtime:
            self._data = self._load()
            self._mtime = stamp

    def save(self) -> None:
        """Persist to disk, tolerating an unwritable location."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, indent=2, default=str), "utf-8"
            )
        except Exception:
            pass

    # --------------------------------------------------------------- access
    def all(self) -> List[Dict[str, Any]]:
        """Every macro, most recently created first."""
        self._refresh()
        items = list(self._data.get("macros", []) or [])
        items.sort(key=lambda item: str(item.get("created", "")), reverse=True)
        return items

    def find(self, trigger: str) -> Optional[Dict[str, Any]]:
        """Return the macro whose trigger normalises to ``trigger``."""
        self._refresh()
        wanted = normalize(trigger)
        for item in self._data.get("macros", []) or []:
            if normalize(str(item.get("trigger", ""))) == wanted:
                return item
        return None

    def match(self, text: str) -> Optional[Dict[str, Any]]:
        """Match a user utterance against the triggers."""
        self._refresh()
        spoken = normalize(text)
        if not spoken:
            return None
        return self.find(spoken)

    # ------------------------------------------------------------ mutation
    def add(
        self, trigger: str, say: str = "", steps: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Create or replace a macro, returning the stored entry."""
        trigger = (trigger or "").strip()
        if not trigger:
            raise ValueError("A macro needs a trigger phrase.")
        if not say.strip() and not steps:
            raise ValueError("A macro needs something to say or do.")
        entry = {
            "trigger": trigger,
            "say": (say or "").strip(),
            "steps": [dict(step) for step in (steps or []) if isinstance(step, dict)],
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "uses": 0,
        }
        macros = self._data.setdefault("macros", [])
        macros[:] = [item for item in macros
                     if normalize(str(item.get("trigger", ""))) != normalize(trigger)]
        macros.append(entry)
        self.save()
        return entry

    def remove(self, trigger: str) -> bool:
        """Delete the macro with this trigger; True when one was removed."""
        wanted = normalize(trigger)
        macros = self._data.setdefault("macros", [])
        kept = [item for item in macros
                if normalize(str(item.get("trigger", ""))) != wanted]
        removed = len(kept) != len(macros)
        if removed:
            self._data["macros"] = kept
            self.save()
        return removed

    def count_use(self, trigger: str) -> None:
        """Bump the use counter after a successful run."""
        entry = self.find(trigger)
        if entry is None:
            return
        entry["uses"] = int(entry.get("uses", 0)) + 1
        entry["last_run"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.save()


__all__ = ["MacroStore", "normalize"]

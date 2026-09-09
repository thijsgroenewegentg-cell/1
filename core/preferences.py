# /core/preferences.py
"""Durable habits JARVIS learns from completed interactions.

Every successful tool call is fed through :meth:`Preferences.observe`.
JARVIS never *asks* for a preference — he notices when the same request
keeps coming back with the same shape, and records it as a routine. The
routine is then shown to the model in the system prompt, so next time the
request is phrased loosely ("render it like before") the assistant already
knows what "like before" means.

This is deliberately separate from the vector memory: those are *facts the
user told him*, stored as embeddings. These are *behaviour the user
demonstrated*, stored as plain JSON that survives restarts and is easy to
inspect and delete.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

#: How many identical requests turn a streak into a learned routine.
ROUTINE_AFTER = 2

#: Params that usually express a *preference*, not a one-off detail. Values
#: of any other kind (paths, ids, free text) are noise for routine detection.
PREFERENCE_KEYS = {
    "animation", "engine", "format", "resolution_percent", "samples",
    "style", "level", "count", "unit", "sort_by", "limit", "language",
    "mute", "volume",
}

#: Human phrasing for the keys above, used in the learned-habits summary.
KEY_WORDS = {
    "animation": "the full animation",
    "engine": "engine",
    "format": "format",
    "resolution_percent": "preview resolution",
    "samples": "sample count",
    "style": "style",
    "level": "detail level",
    "count": "count",
    "unit": "unit",
    "sort_by": "ordering",
    "limit": "result limit",
    "language": "language",
    "mute": "muting",
    "volume": "volume",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Preferences:
    """A small JSON store of usage counts and repeated-request routines."""

    def __init__(self, path: Path) -> None:
        """Open (or lazily create) the store at ``path``.

        Args:
            path: Where the JSON file lives.
        """
        self.path = Path(path)
        self._data: Dict[str, Any] = self._load()

    # ------------------------------------------------------------- storage
    def _load(self) -> Dict[str, Any]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text("utf-8", errors="replace"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {"tool_counts": {}, "streaks": {}, "routines": {}, "profile": {}}

    def save(self) -> None:
        """Persist to disk, tolerating an unwritable location."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(self._data, indent=2, default=str), "utf-8"
            )
        except Exception:
            pass

    # ------------------------------------------------------- learned profile
    def learn_user_name(self, name: str) -> None:
        """Remember the user's name durably (survives restarts).

        Args:
            name: The name the user gave when introducing themselves.
        """
        name = (name or "").strip()
        if not name:
            return
        profile = self._data.setdefault("profile", {})
        if profile.get("user_name") == name:
            return
        profile["user_name"] = name
        profile["name_learned_at"] = _now()
        self.save()

    def user_name(self) -> str:
        """The name JARVIS has learned, or ``""`` when none was given yet.

        Returns:
            The stored user name.
        """
        return str(self._data.setdefault("profile", {}).get("user_name", "") or "")

    #: How many standing corrections are kept before the oldest is dropped.
    MAX_CORRECTIONS = 16

    def learn_correction(self, rule: str) -> bool:
        """Store one standing correction, deduplicated and capped.

        Args:
            rule: The normalised one-line rule (see :mod:`core.corrections`).

        Returns:
            True when the rule was newly added, False when it was a duplicate.
        """
        rule = (rule or "").strip()
        if not rule:
            return False
        profile = self._data.setdefault("profile", {})
        entries = profile.setdefault("corrections", [])
        for entry in entries:
            if str(entry.get("rule", "")).strip().lower() == rule.lower():
                return False
        entries.append({"rule": rule, "at": _now()})
        if len(entries) > self.MAX_CORRECTIONS:
            del entries[:-self.MAX_CORRECTIONS]
        self.save()
        return True

    def corrections(self, limit: int = MAX_CORRECTIONS) -> List[str]:
        """The stored standing corrections, newest first.

        Args:
            limit: How many to return.

        Returns:
            One-line rules as plain strings.
        """
        entries = list(self._data.setdefault("profile", {}).get("corrections", []))
        entries.sort(key=lambda entry: str(entry.get("at", "")), reverse=True)
        return [str(entry.get("rule", "")) for entry in entries[:limit]]

    # ------------------------------------------------------------ learning
    @staticmethod
    def _preference_params(params: Dict[str, Any]) -> Dict[str, Any]:
        """Keep only the params that plausibly encode a durable preference."""
        kept: Dict[str, Any] = {}
        for key, value in (params or {}).items():
            if key not in PREFERENCE_KEYS:
                continue
            if value in (None, "", 0, False):
                continue
            kept[key] = value
        return kept

    def observe(self, reference: str, params: Dict[str, Any]) -> None:
        """Record one successful tool call of ``reference`` with ``params``.

        Usage is counted per tool, and identical preference-shaped requests
        that keep recurring are promoted to a routine.

        Args:
            reference: The dotted tool name, e.g. ``blender.render``.
            params: The parameters the call ran with.
        """
        counts = self._data.setdefault("tool_counts", {})
        counts[reference] = int(counts.get(reference, 0)) + 1

        signature = self._preference_params(params)
        if not signature:
            return
        streaks = self._data.setdefault("streaks", {})
        previous = streaks.get(reference)
        if previous and previous.get("params") == signature:
            streak_count = int(previous.get("count", 1)) + 1
        else:
            streak_count = 1
        streaks[reference] = {"params": signature, "count": streak_count}

        if streak_count >= ROUTINE_AFTER:
            routines = self._data.setdefault("routines", {})
            entry = routines.get(reference) or {"params": signature, "times": 0}
            entry["params"] = signature
            entry["times"] = int(entry.get("times", 0)) + 1
            entry["last"] = _now()
            routines[reference] = entry
        self.save()

    # -------------------------------------------------------------- reading
    def tool_counts(self) -> Dict[str, int]:
        """How many successful calls each tool has had."""
        return dict(self._data.get("tool_counts", {}) or {})

    def routines(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Learned routines as ``(reference, entry)`` pairs, most repeated first."""
        raw = self._data.get("routines", {}) or {}
        items = [(str(ref), dict(entry)) for ref, entry in raw.items()]
        items.sort(key=lambda pair: int(pair[1].get("times", 0)), reverse=True)
        return items

    def _phrase(self, reference: str, params: Dict[str, Any]) -> str:
        """Turn one routine into a natural sentence about the user."""
        tool = reference.split(".", 1)[-1].replace("_", " ")
        bits: List[str] = []
        for key, value in params.items():
            word = KEY_WORDS.get(key, key.replace("_", " "))
            if key == "resolution_percent":
                bits.append(f"{int(value)}% preview resolution")
            elif key == "animation" and value:
                bits.append("the full animation")
            elif key == "engine":
                bits.append(f"the {value} engine")
            elif key == "format":
                bits.append(f"{value} format")
            elif isinstance(value, bool):
                bits.append(f"{word} {'on' if value else 'off'}")
            else:
                bits.append(f"{word} {value}")
        detail = ", ".join(bits) if bits else "the same settings"
        return f"For {tool}, you usually ask for {detail}."

    def summary(self, limit: int = 4) -> str:
        """A short block for the system prompt, or empty when nothing learned."""
        lines: List[str] = []
        for reference, entry in self.routines()[:limit]:
            times = int(entry.get("times", 0))
            times_word = "time" if times == 1 else "times"
            suffix = f" (seen {times} {times_word})" if times > 1 else ""
            lines.append(
                f"- {self._phrase(reference, entry.get('params', {}))}{suffix}"
            )
        return "\n".join(lines)


__all__ = ["ROUTINE_AFTER", "Preferences"]

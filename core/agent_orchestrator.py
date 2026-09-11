"""Bounded orchestration primitives for MARK.

This module is intentionally a planner and contract builder, not an executor.
It gives the live assistant a deterministic preflight for complex requests,
preview/dry-run support, and a small recovery vocabulary while leaving every
real action behind the existing tool registry and confirmation policy.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.i18n import effective_language, normalize_language

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "api_keys.json"
_CONFIG_LOCK = threading.RLock()

_DOMAIN_MARKERS = {
    "blender": ("blender", "3d", "scene", "render", "camera", "material", "object"),
    "voice": ("voice", "speak", "say", "listen", "microphone", "audio", "spraak", "microfoon"),
    "file": ("file", "document", "pdf", "folder", "bestand", "document", "map"),
    "code": ("code", "script", "program", "debug", "repository", "build", "python", "javascript"),
    "desktop": ("open", "launch", "click", "press", "window", "app", "openen", "venster"),
    "research": ("search", "news", "research", "current", "lookup", "zoek", "nieuws"),
    "media": ("spotify", "music", "video", "play", "pause", "muziek", "afspelen"),
}
_MUTATION_MARKERS = (
    "create", "make", "change", "edit", "delete", "remove", "write", "save", "send", "open",
    "start", "stop", "render", "generate", "download", "install", "set", "add", "move",
    "maak", "wijzig", "verwijder", "schrijf", "opslaan", "verstuur", "open", "start", "render",
    "genereer", "download", "installeer", "stel", "voeg", "verplaats",
)


def _load_config() -> dict:
    with _CONFIG_LOCK:
        try:
            value = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}


def _patch_config(**fields: Any) -> None:
    with _CONFIG_LOCK:
        data = _load_config()
        data.update(fields)
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_dry_run() -> bool:
    return bool(_load_config().get("dry_run", False))


def set_dry_run(enabled: bool) -> bool:
    value = bool(enabled)
    _patch_config(dry_run=value)
    return value


@dataclass(frozen=True)
class RequestProfile:
    goal: str
    language: str
    domains: tuple[str, ...] = ()
    complexity: int = 1
    estimated_steps: int = 1
    requires_plan: bool = False
    mutating: bool = False
    suggested_steps: tuple[str, ...] = ()
    confidence: float = 0.5

    def as_text(self) -> str:
        domains = ", ".join(self.domains) or "general"
        plan = "yes" if self.requires_plan else "no"
        return (
            f"REQUEST PREFLIGHT\nlanguage={self.language}; domains={domains}; complexity={self.complexity}/5; "
            f"estimated_steps={self.estimated_steps}; plan={plan}; mutating={str(self.mutating).lower()}"
        )


def _domains(text: str) -> tuple[str, ...]:
    lower = f" {str(text or '').lower()} "
    found = [name for name, markers in _DOMAIN_MARKERS.items() if any(marker in lower for marker in markers)]
    return tuple(found[:5])


def _suggestions(domains: tuple[str, ...], mutating: bool, steps: int) -> tuple[str, ...]:
    if "blender" in domains:
        base = ["Confirm Blender MCP connection and inspect the current scene", "Apply one bounded Blender change", "Verify the scene or viewport result"]
    elif "file" in domains or "code" in domains:
        base = ["Inspect the input and constraints", "Apply the requested bounded change", "Run the relevant verification and report artifacts"]
    elif "desktop" in domains:
        base = ["Inspect the current desktop state", "Perform the allowlisted UI action", "Verify the requested application state"]
    elif "research" in domains:
        base = ["Gather current sources", "Compare and summarize the relevant facts", "Cite uncertainty and next steps"]
    else:
        base = ["Clarify the goal and current state", "Perform one bounded action at a time", "Verify the outcome and report recovery if needed"]
    if not mutating:
        base = [base[0], base[-1]]
    return tuple(base[:max(2, min(steps, 6))])


def analyze_request(text: str, configured_language: str = "auto") -> RequestProfile:
    goal = re.sub(r"\s+", " ", str(text or "")).strip()[:500]
    lower = goal.lower()
    domains = _domains(goal)
    conjunctions = len(re.findall(r"\b(and|then|after|also|while|daarna|en|ook|terwijl)\b", lower))
    numbered = len(re.findall(r"(?:^|\s)\d+[.)]", lower))
    estimated = max(1, min(8, 1 + conjunctions + numbered + len(domains) // 2))
    complexity = max(1, min(5, estimated + (1 if len(goal) > 180 else 0) + (1 if len(domains) >= 2 else 0)))
    mutating = any(marker in lower for marker in _MUTATION_MARKERS)
    language = effective_language(goal, configured_language)
    requires_plan = complexity >= 3 or estimated >= 3
    suggestions = _suggestions(domains, mutating, estimated)
    confidence = min(0.98, 0.55 + (0.1 if domains else 0) + (0.08 if language != "en" else 0))
    return RequestProfile(
        goal=goal,
        language=language,
        domains=domains,
        complexity=complexity,
        estimated_steps=estimated,
        requires_plan=requires_plan,
        mutating=mutating,
        suggested_steps=suggestions,
        confidence=confidence,
    )


def build_preview(tool: str, arguments: dict | None, profile: RequestProfile | None = None) -> str:
    """Return a safe preview; it never calls a tool or reads arbitrary files."""
    args = arguments if isinstance(arguments, dict) else {}
    target = args.get("path") or args.get("file_path") or args.get("object_name") or args.get("app_name") or "the requested target"
    action = args.get("action") or "run"
    language = profile.language if profile else "en"
    try:
        from core.approval_policy import assess_tool
        decision = assess_tool(str(tool), args)
        risk = decision.risk
        reversible = "yes" if decision.reversible else "no"
        confirmation = "yes" if decision.requires_confirmation else "no"
    except Exception:
        risk, reversible, confirmation = "unknown", "unknown", "yes"
    target_text = str(target)[:120]
    if language == "nl":
        return (
            f"VOORBEELD — geen wijziging uitgevoerd. Tool='{tool}'; actie='{action}'; doel='{target_text}'. "
            f"Risico={risk}; omkeerbaar={reversible}; bevestiging vereist={confirmation}. "
            "Controleer de bedoeling en schakel dry-run uit om door te gaan."
        )
    return (
        f"PREVIEW — no change was made. Tool='{tool}'; action='{action}'; target='{target_text}'. "
        f"Risk={risk}; reversible={reversible}; confirmation required={confirmation}. "
        "Review the intent and disable dry-run to continue."
    )


class AgentOrchestrator:
    """Thread-safe request context used by the main conversation loop."""

    def __init__(self):
        self._lock = threading.RLock()
        self._current: RequestProfile | None = None
        self._events: list[dict[str, Any]] = []

    @property
    def current(self) -> RequestProfile | None:
        with self._lock:
            return self._current

    def begin(self, text: str, configured_language: str = "auto") -> RequestProfile:
        profile = analyze_request(text, configured_language)
        with self._lock:
            self._current = profile
            self._events.append({"kind": "preflight", "goal": profile.goal, "language": profile.language, "complexity": profile.complexity})
            self._events = self._events[-40:]
        return profile

    def tool_started(self, name: str, arguments: dict | None = None) -> None:
        with self._lock:
            self._events.append({"kind": "tool_started", "tool": str(name)[:100], "action": str((arguments or {}).get("action", "run"))[:80]})
            self._events = self._events[-40:]

    def tool_finished(self, name: str, result: str, ok: bool) -> None:
        with self._lock:
            self._events.append({"kind": "tool_finished", "tool": str(name)[:100], "ok": bool(ok), "result": str(result or "")[:240]})
            self._events = self._events[-40:]

    def render(self) -> str:
        with self._lock:
            profile = self._current
            events = list(self._events[-12:])
        if not profile:
            return "No request preflight is active."
        lines = [profile.as_text(), "SUGGESTED LOOP: " + " → ".join(profile.suggested_steps)]
        for event in events:
            lines.append(f"{event.get('kind')}: {event.get('tool') or event.get('goal', '')} " + ("ok" if event.get("ok") else ""))
        return "\n".join(lines)


# One process-wide context keeps the inspectable agent_control action aligned
# with the live conversation loop instead of showing a second, stale planner.
_LIVE_ORCHESTRATOR = AgentOrchestrator()


def get_orchestrator() -> AgentOrchestrator:
    return _LIVE_ORCHESTRATOR

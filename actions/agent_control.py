"""Inspect MARK's orchestration state and control safe preview mode."""
from __future__ import annotations

from core.agent_orchestrator import (
    analyze_request,
    build_preview,
    get_dry_run,
    get_orchestrator,
    set_dry_run,
)
from memory.config_manager import get_language
from core.i18n import effective_language

_ORCHESTRATOR = get_orchestrator()


def run(parameters: dict, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    if action in {"status", "preflight"}:
        result = _ORCHESTRATOR.render()
        result += f"\nDRY_RUN={'on' if get_dry_run() else 'off'}"
    elif action == "analyze":
        profile = analyze_request(str(params.get("goal", "")), get_language())
        result = profile.as_text() + "\nSUGGESTED STEPS\n- " + "\n- ".join(profile.suggested_steps)
    elif action == "preview":
        profile = analyze_request(str(params.get("goal", "")), get_language())
        result = build_preview(str(params.get("tool", "planned action")), params.get("arguments"), profile)
    elif action in {"dry_run", "set_dry_run"}:
        raw = params.get("enabled", True)
        enabled = raw if isinstance(raw, bool) else str(raw).lower() in {"1", "true", "yes", "on", "aan"}
        applied = set_dry_run(enabled)
        if effective_language("", get_language()) == "nl":
            result = f"Droogloopmodus {'ingeschakeld' if applied else 'uitgeschakeld'}. Zolang deze modus actief is, worden er geen wijzigende acties uitgevoerd."
        else:
            result = f"Dry-run mode {'enabled' if applied else 'disabled'}. No mutating action is executed while dry-run mode is enabled."
    else:
        result = "Use agent_control action status, analyze, preview or dry_run."
    if player:
        try:
            player.show_content("AGENT CONTROL", result)
            player.write_log(f"[Agent] {action}")
        except Exception:
            pass
    return result


TOOL = {
    "name": "agent_control",
    "description": (
        "Inspect MARK's deterministic request preflight, preview a proposed action, "
        "or enable safe dry-run mode. Dry-run mode reports mutating actions without executing them."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | analyze | preview | dry_run"},
            "goal": {"type": "STRING", "description": "User goal to analyze or preview"},
            "tool": {"type": "STRING", "description": "Tool that would be called"},
            "arguments": {"type": "OBJECT", "description": "Bounded tool arguments to preview"},
            "enabled": {"type": "BOOLEAN", "description": "Enable or disable dry-run mode"},
        },
        "required": ["action"],
    },
    "handler": run,
}

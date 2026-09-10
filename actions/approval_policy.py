"""Inspect or deliberately change MARK's confirmation profile."""
from __future__ import annotations

from core import confirm as confirm_gate
from core.approval_policy import PROFILES, assess_tool, canonical_profile, describe_policy, get_profile, save_profile


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    if action == "status":
        result = describe_policy()
    elif action == "explain":
        decision = assess_tool(str(params.get("tool", "")), params.get("arguments") if isinstance(params.get("arguments"), dict) else {})
        result = decision.as_text()
    elif action == "set_profile":
        profile = canonical_profile(str(params.get("profile", "")))
        if profile not in PROFILES:
            return "Approval profile must be always_confirm, confirm_once_per_task or safe_read_only."
        if profile == get_profile():
            result = f"Approval profile is already {profile}."
        elif confirm_gate.pending_title():
            result = "There is already a confirmation waiting on screen. Answer it first."
        else:
            result = confirm_gate.request(
                "Change approval profile",
                f"Switch MARK's approval profile to {profile}?",
                "Strict confirms every mutation. Balanced retains MARK's existing tool-specific gates; destructive and external actions remain confirmation-gated in both profiles.",
                lambda: f"Approval profile saved as {save_profile(profile)}.",
            )
    else:
        result = "Use approval_policy action status, explain or set_profile."
    if player:
        try:
            player.show_content("APPROVAL POLICY", result)
            player.write_log(f"[Approval policy] {action}")
        except Exception:
            pass
    return result


TOOL = {
    "name": "approval_policy",
    "description": "Inspect MARK's safety profile or request a human-confirmed switch between balanced and strict confirmation behavior. This never enables arbitrary code or shell access.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | explain | set_profile"},
            "profile": {"type": "STRING", "description": "always_confirm | confirm_once_per_task | safe_read_only"},
            "tool": {"type": "STRING", "description": "Tool name to classify"},
            "arguments": {"type": "OBJECT", "description": "Arguments to classify"},
        },
        "required": ["action"],
    },
    "handler": run,
}

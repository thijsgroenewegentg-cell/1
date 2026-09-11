"""Risk classification and configurable approval profiles for MARK.

Profiles are a policy layer above the existing tool-specific confirmation
callbacks. They can require more confirmation, but never grant shell, Python or
unrestricted MCP permissions and never bypass a tool's hard safety checks.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "api_keys.json"
PROFILES = {"always_confirm", "confirm_once_per_task", "safe_read_only"}
_PROFILE_ALIASES = {
    "balanced": "safe_read_only",
    "strict": "always_confirm",
    "confirm_once": "confirm_once_per_task",
    "confirm_once_per_task": "confirm_once_per_task",
    "always": "always_confirm",
    "always_confirm": "always_confirm",
    "safe_read_only": "safe_read_only",
}
_DEFAULT_PROFILE = "safe_read_only"
_READ_ONLY_TOOLS = {
    "system_status", "screen_process", "close_camera", "recall_memory", "memory_control",
    "undo", "task_runtime", "approval_policy", "recovery", "proactive", "web_search", "git_helper",
    "project_helper", "list_tools", "status", "list_objects", "inspect_object", "scene_summary",
    "visual_review", "verify", "plan", "workflow_plan", "connection_status",
}
_DESTRUCTIVE_WORDS = {
    "delete", "remove", "destroy", "shutdown", "wipe", "format", "send", "publish",
    "install", "execute", "terminal", "shell", "reset", "revoke", "clear",
}
_MUTATING_WORDS = {
    "add", "apply", "build", "complete", "copy", "create", "download", "edit", "generate",
    "move", "organize", "rename", "render", "replay", "restore", "run", "save", "set",
    "skip", "type", "update", "upload", "write", "start", "forget", "dismiss",
    "clear_history", "clear_sessions", "set_profile",
}
_task_lock = threading.RLock()
_task_id = ""
_task_approved = False


@dataclass(frozen=True)
class PolicyDecision:
    tool: str
    action: str
    risk: str
    requires_confirmation: bool
    reversible: bool
    reason: str

    def as_text(self) -> str:
        gate = "confirmation required" if self.requires_confirmation else "no confirmation required"
        return f"{self.tool}/{self.action or 'run'}: {self.risk}; {gate}. {self.reason}"


def _config() -> dict:
    try:
        value = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def canonical_profile(profile: str) -> str:
    value = str(profile or "").lower().strip().replace("-", "_")
    return _PROFILE_ALIASES.get(value, "")


def get_profile() -> str:
    value = canonical_profile(_config().get("approval_profile", _DEFAULT_PROFILE))
    return value or _DEFAULT_PROFILE


def save_profile(profile: str) -> str:
    value = canonical_profile(profile)
    if value not in PROFILES:
        raise ValueError("Approval profile must be always_confirm, confirm_once_per_task or safe_read_only.")
    try:
        from memory.config_manager import _patch_config
        _patch_config(approval_profile=value)
    except Exception:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = _config()
        data["approval_profile"] = value
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return value


def begin_task(task_id: str) -> None:
    global _task_id, _task_approved
    with _task_lock:
        _task_id = str(task_id or "")
        _task_approved = False


def grant_task_approval() -> None:
    global _task_approved
    with _task_lock:
        _task_approved = True


def task_approval_active() -> bool:
    with _task_lock:
        return _task_approved


def _tokens(tool: str, action: str, args: dict) -> set[str]:
    raw = " ".join([str(tool), str(action), " ".join(str(k) for k in (args or {}))]).lower()
    return {part for part in re.split(r"[^a-z0-9]+", raw) if part}


def assess_tool(tool: str, args: dict | None = None) -> PolicyDecision:
    args = dict(args or {})
    name = str(tool or "").strip().lower()
    action = str(args.get("action", "")).strip().lower().replace("-", "_")
    tokens = _tokens(name, action, args)
    hard = bool(tokens & _DESTRUCTIVE_WORDS) or name in {"send_message", "email_client", "browser_control", "computer_control", "computer_settings"}
    read_only = ((name in _READ_ONLY_TOOLS and action not in _MUTATING_WORDS)
                 or action in {"status", "connection_status", "list_tools", "list", "inspect", "inspect_object", "info", "search", "show", "plan", "workflow_plan", "scene_summary", "visual_review", "verify", "list_objects", "timeline", "failures", "operations", "task", "preferences", "influence"})
    if read_only and not hard:
        risk, reversible = "read_only", True
    elif hard:
        risk, reversible = "destructive_or_external", False
    else:
        mutating = bool(tokens & _MUTATING_WORDS) or name in {
            "blender_control", "comfyui_image", "file_controller", "file_processor", "code_helper",
            "workflow_recorder", "task_planner", "manage_monitor", "proactive",
        }
        if not mutating:
            risk, reversible = "read_only", True
        else:
            risk, reversible = "reversible_mutation", True

    mcp_name = str(args.get("mcp_tool", "")).strip().lower()
    mcp_read_only = name == "blender_control" and action == "mcp_call" and (
        mcp_name.startswith(("get_", "list_", "inspect_", "search_", "find_", "describe_", "check_"))
        or any(word in mcp_name for word in ("screenshot", "viewport", "scene_info", "object_info"))
    )
    if mcp_read_only and not hard:
        risk, reversible = "read_only", True

    dynamic_blender = name.startswith("blender_mcp_")
    dynamic_name = name[len("blender_mcp_"):] if dynamic_blender else ""
    dynamic_read_only = dynamic_blender and (
        dynamic_name.startswith(("get_", "list_", "inspect_", "search_", "find_", "describe_", "check_"))
        or any(word in dynamic_name for word in ("screenshot", "viewport", "scene_info", "object_info"))
    )
    if dynamic_blender:
        read_only = dynamic_read_only and not hard
        if not dynamic_read_only and not hard:
            risk, reversible = "reversible_mutation", True

    profile = get_profile()
    with _task_lock:
        approved = _task_approved
    if profile == "always_confirm":
        requires = True
        reason = "Always-confirm profile requires a visible human approval for this call."
    elif profile == "confirm_once_per_task":
        requires = (risk != "read_only") and not approved
        reason = "The first mutation in this task needs approval; hard external/destructive tool gates remain authoritative." if requires else "This task already has a human approval; hard safety gates still apply."
    else:  # safe_read_only
        requires = risk != "read_only"
        reason = "Read-only inspection is safe to run; state-changing or external work remains confirmation-gated."
    if risk == "destructive_or_external":
        requires = True
        reason = "Destructive or external operations always require visible human approval."
    return PolicyDecision(name, action, risk, requires, reversible, reason)


def describe_policy() -> str:
    return (
        f"Approval profile: {get_profile()}. Profiles: always_confirm (every call), "
        "confirm_once_per_task (one approval can authorize safe mutations for the current task), "
        "safe_read_only (read-only inspection is immediate; mutations remain gated). "
        "Destructive/external actions always require on-screen confirmation. No profile permits arbitrary shell, Python or unrestricted MCP execution."
    )

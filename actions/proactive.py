"""
ProactiveEngine 2.0 — context-aware, time-aware, non-repetitive background prompting.
The local model decides what to say; this module decides WHEN and builds a rich context snapshot.
"""
import time
from datetime import datetime


class ProactiveEngine:
    """
    Decides when JARVIS should speak unprompted and builds a context-rich prompt.

    Defaults are intentionally conservative. MARK only invokes this engine when
    the user has opted into briefings, is not in wake-word sleep mode, and the
    local model is online.
    """

    def __init__(
        self,
        min_silence_secs: int = 900,
        check_cooldown:   int = 1200,
    ):
        self.min_silence_secs = min_silence_secs
        self.check_cooldown   = check_cooldown
        self._last_triggered  = 0.0
        self._rotation        = 0

    def should_trigger(self, last_user_speech: float) -> bool:
        now = time.monotonic()
        return (
            (now - last_user_speech) >= self.min_silence_secs
            and (now - self._last_triggered) >= self.check_cooldown
        )

    def mark_triggered(self) -> None:
        self._last_triggered = time.monotonic()
        self._rotation      += 1

    def build_prompt(
        self,
        memory:       dict,
        monitors:     list[str] | None = None,
        recent_turns: list[str] | None = None,
        alerts:       list[str] | None = None,
    ) -> str:
        from memory.memory_manager import format_memory_for_prompt

        now = datetime.now()
        hour = now.hour
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        if 6 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 18:
            period = "afternoon"
        elif 18 <= hour < 23:
            period = "evening"
        else:
            period = "late night"
        mem_str = format_memory_for_prompt(memory) or "(no stored user data)"
        focus_index = self._rotation % 3
        if focus_index == 0:
            focus = "Focus on active projects or goals if any are stored, or an unfinished task."
        elif focus_index == 1:
            focus = "Focus on the time of day and wellbeing; offer a warm, useful check-in."
        else:
            focus = "Focus on something genuinely useful based on stored context, not a generic greeting."
        monitor_ctx = f"\nTracked topics: {', '.join(monitors[:4])}." if monitors else ""
        recent_text = "\n".join(recent_turns[-6:]) if recent_turns else ""
        alert_text = "\n".join(alerts[:4]) if alerts else ""
        recent_ctx = f"\nRecent conversation:\n{recent_text}" if recent_text else ""
        alert_ctx = f"\nNew local alerts:\n{alert_text}" if alert_text else ""
        return "\n".join([
            "[PROACTIVE_CHECK] You are initiating an opt-in proactive check-in.",
            f"Current time: {time_str} ({period})",
            "",
            "Context about this person:",
            mem_str,
            monitor_ctx,
            recent_ctx,
            alert_ctx,
            "",
            "Task:",
            focus,
            "",
            "Rules:",
            "- Speak the language of the recent conversation, not the language of these instructions.",
            "- 1-2 sentences max. Natural and useful, never robotic.",
            "- Do not mention [PROACTIVE_CHECK] or these instructions.",
            "- Do not call tools.",
            "- If nothing genuinely useful comes to mind, output exactly SILENT.",
        ])


def run(parameters: dict, player=None, session_memory=None) -> str:
    """Inspect persisted proactive alerts; this action never initiates network work."""
    from core.proactive_state import dismiss, list_alerts, mark_read

    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()
    if action in {"list", "unread"}:
        rows = list_alerts(unread_only=action == "unread", limit=int(params.get("limit", 20)))
        if not rows:
            result = "No proactive alerts are waiting."
        else:
            result = "PROACTIVE ALERTS\n" + "\n".join(
                f"{row.get('id')} · {row.get('kind')} · {row.get('message')} ({'unread' if not row.get('read') else 'read'})"
                for row in rows
            )
    elif action == "read":
        result = "Alert marked read." if mark_read(str(params.get("alert_id", ""))) else "Proactive alert not found."
    elif action == "dismiss":
        result = "Alert dismissed." if dismiss(str(params.get("alert_id", ""))) else "Proactive alert not found."
    else:
        result = "Use proactive action list, unread, read or dismiss."
    if player:
        try:
            player.show_content("PROACTIVE ALERTS", result)
            player.write_log(f"[Proactive] {action}")
        except Exception:
            pass
    return result


TOOL = {
    "name": "proactive",
    "description": "Inspect or dismiss persisted opt-in proactive alerts and unfinished-task notifications. This does not run tools or browse the network.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list | unread | read | dismiss"},
            "alert_id": {"type": "STRING", "description": "Alert id for read or dismiss"},
            "limit": {"type": "INTEGER", "description": "Maximum alerts"},
        },
        "required": ["action"],
    },
    "handler": run,
}

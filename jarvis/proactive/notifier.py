"""
Notifier - JARVIS notifies Sir proactively
Desktop notifications, voice, and log
"""

import os
from pathlib import Path
from datetime import datetime
from typing import Optional


class Notifier:
    def __init__(self):
        self.notifications = []
        self._has_plyer = False
        try:
            from plyer import notification
            self._has_plyer = True
        except:
            pass
    
    def notify(self, title: str, message: str, level: str = "info", speak: bool = False, timeout: int = 10):
        """
        Notify via desktop notification + log + optional voice
        level: info, warning, success, error
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "title": title,
            "message": message,
            "level": level
        }
        self.notifications.append(entry)
        if len(self.notifications) > 100:
            self.notifications = self.notifications[-100:]
        
        print(f"🔔 [{level.upper()}] {title}: {message}")
        
        # Desktop notification
        if self._has_plyer:
            try:
                from plyer import notification
                notification.notify(
                    title=f"JARVIS: {title}",
                    message=message[:200],
                    app_icon=None,
                    timeout=timeout
                )
            except Exception as e:
                print(f"Plyer notify failed: {e}")
        else:
            # Fallback: try notify-send on Linux
            try:
                if os.name == 'posix':
                    os.system(f'notify-send "JARVIS: {title}" "{message[:200]}" 2>/dev/null &')
            except:
                pass
        
        # Voice
        if speak:
            try:
                from ..voice import get_tts
                tts = get_tts()
                tts.speak(f"{title}. {message}", blocking=False)
            except:
                pass
    
    def notify_briefing(self, briefing_text: str):
        self.notify("Morning Briefing", briefing_text, level="info", speak=False, timeout=15)
    
    def notify_git(self, message: str):
        self.notify("Git Watcher", message, level="info", timeout=10)
    
    def notify_proactive(self, message: str):
        self.notify("Proactive Suggestion", message, level="info", timeout=10)
    
    def get_recent(self, limit: int = 10):
        return self.notifications[-limit:]

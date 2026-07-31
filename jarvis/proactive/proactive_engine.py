"""
Proactive Engine - JARVIS acts first, doesn't wait
Morning briefing, evening summary, git watcher, routine-based suggestions

This is what makes JARVIS feel alive, Sir.
"""

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from ..config import config
from .scheduler import ProactiveScheduler
from .briefing import BriefingGenerator
from .git_watcher import GitWatcher
from .notifier import Notifier


class ProactiveEngine:
    def __init__(self, brain=None):
        self.brain = brain
        self._ensure_brain()
        
        self.scheduler = ProactiveScheduler()
        self.briefing = BriefingGenerator(brain=self.brain)
        self.notifier = Notifier()
        self.git_watcher = GitWatcher(on_change=self._on_git_change)
        
        self.is_active = False
        
        # Configurable times
        self.morning_hour = int(config.MEMORY_FILE.parent.parent.joinpath(".env").read_text().split("MORNING_BRIEF_HOUR=")[1].split("\n")[0]) if (config.MEMORY_FILE.parent.parent / ".env").exists() and "MORNING_BRIEF_HOUR=" in (config.MEMORY_FILE.parent.parent / ".env").read_text() else 8
        self.morning_hour = 8  # default 8:30
        self.morning_minute = 30
        self.evening_hour = 18
        self.evening_minute = 0
        
        # Try env
        import os
        self.morning_hour = int(os.getenv("MORNING_BRIEF_HOUR", "8"))
        self.morning_minute = int(os.getenv("MORNING_BRIEF_MINUTE", "30"))
        self.evening_hour = int(os.getenv("EVENING_BRIEF_HOUR", "18"))
        
        print(f"⏰ ProactiveEngine init: morning {self.morning_hour:02d}:{self.morning_minute:02d}, evening {self.evening_hour:02d}:{self.evening_minute:02d}")
    
    def _ensure_brain(self):
        if not self.brain:
            try:
                from ..brain import JarvisBrain
                self.brain = JarvisBrain()
            except:
                pass
    
    def _on_git_change(self, event_type: str, data: Dict):
        """Called when git watcher detects change"""
        if event_type == "new_commit":
            msg = f"New commit {data.get('new','')[:8]} detected, Sir. Nice work."
            self.notifier.notify_git(msg)
        elif event_type == "dirty":
            files = data.get("files", 0)
            if files > 5:  # only notify if many files changed
                msg = f"{files} files changed in workspace, Sir. Dirty working tree."
                self.notifier.notify_git(msg)
    
    def _do_morning_briefing(self):
        print("🌅 Generating morning briefing, Sir...")
        try:
            briefing = self.briefing.generate_morning_briefing()
            self.notifier.notify_briefing(briefing)
            
            # Also save to file for UI to show
            briefing_path = config.MEMORY_FILE.parent / "last_briefing.json"
            import json
            briefing_path.write_text(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "type": "morning",
                "text": briefing
            }, indent=2))
            
            print(f"🌅 Morning briefing done, Sir: {briefing[:100]}...")
        except Exception as e:
            print(f"Morning briefing failed: {e}")
            import traceback
            traceback.print_exc()
    
    def _do_evening_summary(self):
        print("🌙 Generating evening summary, Sir...")
        try:
            summary = self.briefing.generate_evening_summary()
            self.notifier.notify("Evening Summary", summary, level="info", timeout=15)
            
            briefing_path = config.MEMORY_FILE.parent / "last_briefing.json"
            import json
            # Append or overwrite? Keep both morning and evening
            data = {}
            if briefing_path.exists():
                try:
                    existing = json.loads(briefing_path.read_text())
                    if isinstance(existing, dict):
                        data = existing
                except:
                    pass
            
            # Save evening
            evening_path = config.MEMORY_FILE.parent / "last_evening.json"
            evening_path.write_text(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "type": "evening",
                "text": summary
            }, indent=2))
            
            print(f"🌙 Evening summary done: {summary[:100]}...")
        except Exception as e:
            print(f"Evening summary failed: {e}")
    
    def _do_routine_check(self):
        """Check routines and generate proactive suggestion"""
        try:
            from ..learning import UserProfile
            up = UserProfile()
            profile = up.get()
            routines = profile.get("routines", [])
            
            now = datetime.now()
            hour = now.hour
            
            # Simple: if it's common hour for user to ask something, suggest
            common_hours = profile.get("interaction_stats", {}).get("common_hours", {})
            # Find most common hour
            if common_hours:
                most_common = max(common_hours.items(), key=lambda x: x[1])
                common_hour = int(most_common[0])
                # If now is close to common hour and not already notified today
                if abs(hour - common_hour) <= 1:
                    # Check if we already suggested today
                    # For simplicity, just generate suggestion
                    suggestion = self.briefing.generate_proactive_suggestion(
                        trigger=f"User usually active around {common_hour}:00, now {hour}:00",
                        context=f"Routines: {routines[:2]}, common_hours: {common_hours}"
                    )
                    if suggestion:
                        self.notifier.notify_proactive(suggestion)
            
            # Check goals for accountability - Proactive 2.0
            try:
                from .goals import GoalsTracker
                gt = GoalsTracker()
                accountability = gt.generate_accountability_message()
                if accountability:
                    self.notifier.notify_proactive(accountability)
            except Exception as e:
                print(f"Goals accountability check failed: {e}")
        
        except Exception as e:
            print(f"Routine check failed: {e}")
    
    def _do_git_check(self):
        """Periodic git check for dirty state or long time without commit"""
        try:
            status = self.git_watcher.check_now()
            if status.get("is_dirty") and status.get("changed_files", 0) > 10:
                # If many files dirty for long time, suggest commit
                self.notifier.notify_proactive(f"{status['changed_files']} files dirty, Sir. Consider committing? Git status shows changes.")
            
            # Check goals overdue - proactive accountability
            try:
                from .goals import GoalsTracker
                gt = GoalsTracker()
                check = gt.check_goals()
                if check["overdue"]:
                    overdue_goals = check["overdue"][:2]
                    msg = f"Overdue goals, Sir: {', '.join([g['goal'][:60] for g in overdue_goals])}. {len(check['overdue'])} total overdue."
                    self.notifier.notify_proactive(msg)
            except Exception as e:
                print(f"Goals overdue check failed: {e}")
        
        except Exception as e:
            print(f"Git check failed: {e}")
    
    def start(self):
        if self.is_active:
            print("Proactive engine already active, Sir.")
            return
        
        # Schedule jobs
        self.scheduler.add_daily_job("morning_briefing", self.morning_hour, self.morning_minute, self._do_morning_briefing)
        self.scheduler.add_daily_job("evening_summary", self.evening_hour, self.evening_minute, self._do_evening_summary)
        self.scheduler.add_interval_job("routine_check", 60, self._do_routine_check)  # every 60 min
        self.scheduler.add_interval_job("git_check", 30, self._do_git_check)  # every 30 min
        
        self.scheduler.start()
        self.git_watcher.start()
        
        self.is_active = True
        print("🚀 Proactive Engine started, Sir. I'll brief you mornings, watch git, and suggest proactively. Like real JARVIS.")
        
        # Optional: immediate briefing if it's morning and no briefing today
        try:
            briefing_path = config.MEMORY_FILE.parent / "last_briefing.json"
            should_brief_now = False
            if not briefing_path.exists():
                should_brief_now = True
            else:
                import json
                try:
                    data = json.loads(briefing_path.read_text())
                    last_time = datetime.fromisoformat(data.get("timestamp",""))
                    # If last briefing was yesterday or earlier, and it's after morning time
                    now = datetime.now()
                    if last_time.date() < now.date() and now.hour >= self.morning_hour:
                        should_brief_now = True
                except:
                    should_brief_now = True
            
            if should_brief_now:
                print("🌅 No briefing today yet, generating now, Sir...")
                threading.Thread(target=self._do_morning_briefing, daemon=True).start()
        except Exception as e:
            print(f"Immediate briefing check failed: {e}")
    
    def stop(self):
        if not self.is_active:
            return
        self.scheduler.stop()
        self.git_watcher.stop()
        self.is_active = False
        print("✓ Proactive engine stopped")
    
    def trigger_briefing_now(self, type: str = "morning") -> str:
        if type == "morning":
            self._do_morning_briefing()
            return "Morning briefing triggered, Sir."
        elif type == "evening":
            self._do_evening_summary()
            return "Evening summary triggered, Sir."
        else:
            return f"Unknown briefing type: {type}"
    
    def get_status(self) -> Dict:
        import json
        briefing_text = None
        evening_text = None
        
        try:
            bp = config.MEMORY_FILE.parent / "last_briefing.json"
            if bp.exists():
                data = json.loads(bp.read_text())
                briefing_text = data.get("text","")[:500]
        except:
            pass
        
        try:
            ep = config.MEMORY_FILE.parent / "last_evening.json"
            if ep.exists():
                data = json.loads(ep.read_text())
                evening_text = data.get("text","")[:500]
        except:
            pass
        
        return {
            "active": self.is_active,
            "morning_time": f"{self.morning_hour:02d}:{self.morning_minute:02d}",
            "evening_time": f"{self.evening_hour:02d}:{self.evening_minute:02d}",
            "jobs": self.scheduler.list_jobs(),
            "git_watcher_active": self.git_watcher.is_watching,
            "git_status": self.git_watcher.check_now(),
            "last_briefing": briefing_text,
            "last_evening": evening_text,
            "recent_notifications": self.notifier.get_recent(5)
        }


# Singleton
_proactive_engine = None

def get_proactive_engine(brain=None) -> ProactiveEngine:
    global _proactive_engine
    if _proactive_engine is None:
        _proactive_engine = ProactiveEngine(brain=brain)
    return _proactive_engine

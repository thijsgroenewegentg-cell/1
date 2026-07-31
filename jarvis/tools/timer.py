import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from ..config import config

def set_timer(duration: int, unit: str = "seconds", label: str = "Timer") -> str:
    """Set a simple timer that just returns confirmation - actual async in app layer"""
    try:
        multiplier = {"seconds": 1, "minutes": 60, "hours": 3600}
        seconds = duration * multiplier.get(unit, 1)
        
        # Save to file for app to potentially handle
        timer_file = config.MEMORY_FILE.parent / "timers.json"
        timers = []
        if timer_file.exists():
            try:
                timers = json.loads(timer_file.read_text())
            except:
                timers = []
        
        timer_data = {
            "label": label,
            "duration": duration,
            "unit": unit,
            "seconds": seconds,
            "set_at": datetime.now().isoformat(),
            "trigger_at": (datetime.now() + timedelta(seconds=seconds)).isoformat()
        }
        timers.append(timer_data)
        timer_file.write_text(json.dumps(timers, indent=2))
        
        return f"Timer set for {duration} {unit}, Sir. Label: '{label}'. I'll remind you at {timer_data['trigger_at']}."
    except Exception as e:
        return f"Failed to set timer: {e}"

def set_reminder(message: str, time: str) -> str:
    try:
        reminders_file = config.MEMORY_FILE.parent / "reminders.json"
        reminders = []
        if reminders_file.exists():
            try:
                reminders = json.loads(reminders_file.read_text())
            except:
                reminders = []
        
        reminder_data = {
            "message": message,
            "time": time,
            "created_at": datetime.now().isoformat()
        }
        reminders.append(reminder_data)
        reminders_file.write_text(json.dumps(reminders, indent=2))
        
        return f"Reminder noted, Sir: '{message}' for {time}. I won't forget. Unlike some people."
    except Exception as e:
        return f"Failed to set reminder: {e}"

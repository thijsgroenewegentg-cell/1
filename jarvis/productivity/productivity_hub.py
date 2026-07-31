"""
Productivity Hub - Unified productivity: calendars + emails + goals
Sync local calendars, parse upcoming events, read/send emails securely via IMAP/SMTP

100% FREE, local, secure, no third-party APIs except your own email provider
"""

from typing import Dict, List
from datetime import datetime

from .calendar_hub import CalendarHub
from .email_hub import EmailHub


class ProductivityHub:
    def __init__(self):
        self.calendar = CalendarHub()
        self.email = EmailHub()
        
        # Try to auto-sync calendars on init
        try:
            self.calendar.sync_calendars()
        except Exception as e:
            print(f"Calendar auto-sync failed: {e}")
    
    def get_morning_briefing_context(self) -> str:
        """Get context for morning briefing: calendar + email + goals"""
        parts = []
        
        # Calendar today
        try:
            today_events = self.calendar.get_today_events()
            if today_events:
                parts.append(f"Today's calendar ({len(today_events)} events):\n" + self.calendar.format_events(today_events))
            else:
                parts.append("Today's calendar: No events, Sir. Free day.")
        except Exception as e:
            parts.append(f"Calendar: Error {e}")
        
        # Tomorrow preview
        try:
            tomorrow = self.calendar.get_tomorrow_events()
            if tomorrow:
                parts.append(f"\nTomorrow ({len(tomorrow)} events):\n" + self.calendar.format_events(tomorrow[:3]))
        except:
            pass
        
        # Email overview (without fetching all emails, just count if configured)
        try:
            if self.email.is_configured:
                inbox = self.email.fetch_inbox(limit=3)
                if inbox and not inbox[0].get("error"):
                    parts.append(f"\nInbox: {len(inbox)} recent emails, latest from {inbox[0].get('from','unknown')}: {inbox[0].get('subject','')[:80]}")
                else:
                    parts.append(f"\nEmail: Configured but {inbox[0].get('error','no inbox')[:100] if inbox else 'no emails'}")
            else:
                parts.append("\nEmail: Not configured (set EMAIL_IMAP_* in .env to enable)")
        except Exception as e:
            parts.append(f"\nEmail: Error {e}")
        
        # Goals summary
        try:
            from ..proactive.goals import GoalsTracker
            gt = GoalsTracker()
            summary = gt.get_summary_for_briefing()
            parts.append(f"\nGoals: {summary}")
            
            accountability = gt.generate_accountability_message()
            if accountability:
                parts.append(f"\nAccountability: {accountability}")
        except:
            pass
        
        return "\n".join(parts)
    
    def get_productivity_overview(self) -> Dict:
        """Get overview of productivity hub"""
        cal_overview = {}
        email_overview = {}
        goals_overview = {}
        
        try:
            cal_overview = self.calendar.get_overview()
        except Exception as e:
            cal_overview = {"error": str(e)}
        
        try:
            email_overview = self.email.get_overview()
        except Exception as e:
            email_overview = {"error": str(e)}
        
        try:
            from ..proactive.goals import GoalsTracker
            gt = GoalsTracker()
            goals_check = gt.check_goals()
            goals_overview = {
                "total": goals_check["total"],
                "active": goals_check["active"],
                "overdue": len(goals_check["overdue"]),
                "due_soon": len(goals_check["due_soon"]),
                "completed": len(goals_check["completed"])
            }
        except Exception as e:
            goals_overview = {"error": str(e)}
        
        return {
            "calendar": cal_overview,
            "email": email_overview,
            "goals": goals_overview,
            "timestamp": datetime.now().isoformat()
        }

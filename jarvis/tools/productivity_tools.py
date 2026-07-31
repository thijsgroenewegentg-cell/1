"""
Productivity Hub Tools - Calendar + Email via IMAP/SMTP, 100% FREE local
"""

from ..config import config

# Lazy singletons
_calendar_hub = None
_email_hub = None
_productivity_hub = None

def _get_calendar():
    global _calendar_hub
    if _calendar_hub is None:
        try:
            from ..productivity import CalendarHub
            _calendar_hub = CalendarHub()
        except Exception as e:
            print(f"CalendarHub not available: {e}")
    return _calendar_hub

def _get_email():
    global _email_hub
    if _email_hub is None:
        try:
            from ..productivity import EmailHub
            _email_hub = EmailHub()
        except Exception as e:
            print(f"EmailHub not available: {e}")
    return _email_hub

def _get_productivity():
    global _productivity_hub
    if _productivity_hub is None:
        try:
            from ..productivity import ProductivityHub
            _productivity_hub = ProductivityHub()
        except Exception as e:
            print(f"ProductivityHub not available: {e}")
    return _productivity_hub


# Calendar Tools

def get_calendar_events(days: int = 7, limit: int = 10) -> str:
    try:
        cal = _get_calendar()
        if not cal:
            return "Calendar not available, Sir."
        
        events = cal.get_upcoming_events(days=days, limit=limit)
        
        if not events:
            return f"No upcoming events in next {days} days, Sir. Free schedule!"
        
        formatted = cal.format_events(events)
        return f"Upcoming events in next {days} days ({len(events)}), Sir:\n{formatted}"
    except Exception as e:
        return f"Get calendar events failed: {e}"


def get_today_events() -> str:
    try:
        cal = _get_calendar()
        if not cal:
            return "Calendar not available"
        
        events = cal.get_today_events()
        
        if not events:
            return "No events today, Sir. Free day!"
        
        formatted = cal.format_events(events)
        return f"Today's events ({len(events)}), Sir:\n{formatted}"
    except Exception as e:
        return f"Today events failed: {e}"


def get_tomorrow_events() -> str:
    try:
        cal = _get_calendar()
        if not cal:
            return "Calendar not available"
        
        events = cal.get_tomorrow_events()
        
        if not events:
            return "No events tomorrow, Sir."
        
        formatted = cal.format_events(events)
        return f"Tomorrow's events ({len(events)}), Sir:\n{formatted}"
    except Exception as e:
        return f"Tomorrow events failed: {e}"


def sync_calendars() -> str:
    try:
        cal = _get_calendar()
        if not cal:
            return "Calendar not available"
        
        result = cal.sync_calendars()
        return f"Calendar sync, Sir: {result['files_parsed']}/{result['files_found']} ICS files parsed, {result['total_events']} total events. Last sync {result['last_sync']}"
    except Exception as e:
        return f"Sync calendars failed: {e}"


def get_calendar_overview() -> str:
    try:
        prod = _get_productivity()
        if not prod:
            return "Productivity hub not available"
        
        overview = prod.get_productivity_overview()
        cal = overview.get("calendar", {})
        
        return f"""Calendar Overview, Sir:
Total events: {cal.get('total_events',0)}
Today: {cal.get('today_count',0)} | Tomorrow: {cal.get('tomorrow_count',0)} | Week: {cal.get('week_count',0)}
Last sync: {cal.get('last_sync','never')}
Files found: {cal.get('files_found',0)}
Dirs: {', '.join(cal.get('calendar_dirs',[])[:2])}

Add ICS files to workspace/calendar/ or data/calendar/ to sync local calendars, Sir. 100% free, local, no API keys.
"""
    except Exception as e:
        return f"Calendar overview failed: {e}"


# Email Tools

def fetch_emails(limit: int = 5, folder: str = "INBOX") -> str:
    try:
        email_hub = _get_email()
        if not email_hub:
            return "Email hub not available"
        
        if not email_hub.is_configured:
            return email_hub.get_overview()["instructions"]
        
        emails = email_hub.fetch_inbox(limit=limit, folder=folder)
        
        if not emails:
            return f"No emails in {folder}, Sir."
        
        if emails and emails[0].get("error"):
            return f"Fetch emails failed, Sir: {emails[0]['error']}"
        
        output = [f"Latest {len(emails)} emails from {folder}, Sir:\n"]
        for i, em in enumerate(emails, 1):
            date = em.get("date","")[:16]
            output.append(f"{i}. [{em.get('id')}] {date} - From: {em.get('from','')[:40]} | Subject: {em.get('subject','')[:60]}")
            output.append(f"   Snippet: {em.get('snippet','')[:100]}...")
        
        return "\n".join(output)[:6000]
    except Exception as e:
        return f"Fetch emails failed: {e}"


def search_emails(query: str, limit: int = 5, folder: str = "INBOX") -> str:
    try:
        email_hub = _get_email()
        if not email_hub:
            return "Email hub not available"
        
        if not email_hub.is_configured:
            return email_hub.get_overview()["instructions"]
        
        results = email_hub.search_emails(query=query, limit=limit, folder=folder)
        
        if not results:
            return f"No emails found for '{query}', Sir."
        
        if results and results[0].get("error"):
            return f"Search failed: {results[0]['error']}"
        if results and results[0].get("info"):
            return results[0]["info"]
        
        output = [f"Search results for '{query}' ({len(results)}), Sir:\n"]
        for i, em in enumerate(results, 1):
            output.append(f"{i}. [{em.get('id')}] From: {em.get('from','')[:40]} | Subject: {em.get('subject','')[:60]} | Date: {em.get('date','')[:16]}")
        
        return "\n".join(output)[:6000]
    except Exception as e:
        return f"Search emails failed: {e}"


def read_email(email_id: str, folder: str = "INBOX") -> str:
    try:
        email_hub = _get_email()
        if not email_hub:
            return "Email hub not available"
        
        if not email_hub.is_configured:
            return email_hub.get_overview()["instructions"]
        
        email_data = email_hub.read_email(email_id=email_id, folder=folder)
        
        if email_data.get("error"):
            return f"Read email {email_id} failed: {email_data['error']}"
        
        output = f"""Email {email_id}, Sir:
From: {email_data.get('from','')}
To: {email_data.get('to','')}
Date: {email_data.get('date','')}
Subject: {email_data.get('subject','')}

Body:
{email_data.get('body','')[:4000]}
"""
        return output[:6000]
    except Exception as e:
        return f"Read email {email_id} failed: {e}"


def send_email(to: str, subject: str, body: str, cc: str = None) -> str:
    try:
        email_hub = _get_email()
        if not email_hub:
            return "Email hub not available"
        
        if not email_hub.is_configured:
            # Check SMTP too
            if not email_hub.smtp_host:
                return email_hub.get_overview()["instructions"]
        
        result = email_hub.send_email(to=to, subject=subject, body=body, cc=cc)
        return result
    except Exception as e:
        return f"Send email failed: {e}"


def get_email_overview() -> str:
    try:
        email_hub = _get_email()
        if not email_hub:
            return "Email hub not available"
        
        overview = email_hub.get_overview()
        
        return f"""Email Overview, Sir:
Configured: {overview.get('configured')}
IMAP: {overview.get('imap_host')} | SMTP: {overview.get('smtp_host')}
User: {overview.get('user')}

{overview.get('instructions','')}

To enable 100% free local email (no API keys except your own app password):
1. Gmail: Enable IMAP, create app password at myaccount.google.com/apppasswords
2. .env: EMAIL_IMAP_HOST=imap.gmail.com, EMAIL_IMAP_USER=you@gmail.com, EMAIL_IMAP_PASS=app_password
3. EMAIL_SMTP_HOST=smtp.gmail.com, EMAIL_SMTP_PORT=587, same user/pass
4. Outlook: outlook.office365.com / smtp.office365.com

All free, secure via SSL/TLS, local only, Sir.
"""
    except Exception as e:
        return f"Email overview failed: {e}"


def get_productivity_overview() -> str:
    try:
        prod = _get_productivity()
        if not prod:
            return "Productivity hub not available"
        
        overview = prod.get_productivity_overview()
        
        cal = overview.get("calendar",{})
        email = overview.get("email",{})
        goals = overview.get("goals",{})
        
        return f"""Productivity Hub Overview, Sir:

📅 Calendar:
  Total events: {cal.get('total_events',0)} | Today: {cal.get('today_count',0)} | Week: {cal.get('week_count',0)}
  Files: {cal.get('files_found',0)} | Dirs: {len(cal.get('calendar_dirs',[]))}

📧 Email:
  Configured: {email.get('configured')} | IMAP: {email.get('imap_host')} | User: {email.get('user','not set')}

🎯 Goals:
  Total: {goals.get('total',0)} | Active: {goals.get('active',0)} | Overdue: {goals.get('overdue',0)} | Due soon: {goals.get('due_soon',0)}

Morning briefing context:
{prod.get_morning_briefing_context()[:1000]}

100% free, local, no third-party APIs, Sir.
"""
    except Exception as e:
        return f"Productivity overview failed: {e}"

"""
Productivity Hub - Sync local calendars, parse upcoming events, read/send emails via IMAP/SMTP
100% FREE, local, secure, no API keys needed (except your own email credentials)
"""

from .calendar_hub import CalendarHub
from .email_hub import EmailHub
from .productivity_hub import ProductivityHub

__all__ = ["CalendarHub", "EmailHub", "ProductivityHub"]

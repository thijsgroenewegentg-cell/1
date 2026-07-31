"""
Email Hub - Read/send emails securely via IMAP and SMTP
100% FREE, local, secure, no API keys except your own email credentials (app passwords)

Supports:
- IMAP: fetch inbox, search, read emails securely (SSL)
- SMTP: send emails securely (SSL/TLS)
- Works with Gmail, Outlook, Yahoo, any IMAP/SMTP provider
- Secure credential handling via .env (never logs passwords)
- 100% free, no third-party APIs

Security:
- Uses SSL/TLS
- Credentials from .env only, never logged
- App passwords recommended (not main password)
- Local only, emails never leave your machine except via your own SMTP
"""

import os
import re
import ssl
import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from ..config import config


def _decode_str(s):
    """Decode email header string"""
    try:
        if isinstance(s, bytes):
            s = s.decode('utf-8', errors='ignore')
        
        decoded_parts = decode_header(s)
        result = ""
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                try:
                    result += part.decode(encoding or 'utf-8', errors='ignore')
                except:
                    result += part.decode('utf-8', errors='ignore')
            else:
                result += part
        return result
    except:
        return str(s)


class EmailHub:
    def __init__(self):
        # Load credentials from .env - secure, not logged
        self.imap_host = os.getenv("EMAIL_IMAP_HOST", "")
        self.imap_user = os.getenv("EMAIL_IMAP_USER", "")
        self.imap_pass = os.getenv("EMAIL_IMAP_PASS", "")
        self.imap_port = int(os.getenv("EMAIL_IMAP_PORT", "993"))
        
        self.smtp_host = os.getenv("EMAIL_SMTP_HOST", "")
        self.smtp_user = os.getenv("EMAIL_SMTP_USER", "") or self.imap_user
        self.smtp_pass = os.getenv("EMAIL_SMTP_PASS", "") or self.imap_pass
        self.smtp_port = int(os.getenv("EMAIL_SMTP_PORT", "587"))
        
        # Auto-detect Gmail etc
        if not self.imap_host and "gmail" in self.imap_user.lower():
            self.imap_host = "imap.gmail.com"
            self.smtp_host = "smtp.gmail.com"
            self.smtp_port = 587
        
        if not self.imap_host and "outlook" in self.imap_user.lower() or "hotmail" in self.imap_user.lower():
            self.imap_host = "outlook.office365.com"
            self.smtp_host = "smtp.office365.com"
        
        self.is_configured = bool(self.imap_host and self.imap_user and self.imap_pass)
    
    def _connect_imap(self):
        """Connect to IMAP with SSL"""
        if not self.is_configured:
            raise Exception("Email not configured, Sir. Set EMAIL_IMAP_HOST, EMAIL_IMAP_USER, EMAIL_IMAP_PASS in .env. Use app password, not main password. For Gmail: imap.gmail.com, app password from myaccount.google.com/apppasswords")
        
        try:
            # SSL context
            context = ssl.create_default_context()
            mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=context)
            mail.login(self.imap_user, self.imap_pass)
            return mail
        except Exception as e:
            raise Exception(f"IMAP connection failed to {self.imap_host}: {e}. Check host, user, app password, and that IMAP is enabled in email settings.")
    
    def _parse_email(self, email_id: bytes, msg_data) -> Dict:
        """Parse email message"""
        try:
            # msg_data is tuple
            if isinstance(msg_data, tuple) and len(msg_data) > 1:
                raw_email = msg_data[1]
            else:
                raw_email = msg_data
            
            if isinstance(raw_email, list):
                raw_email = raw_email[0] if raw_email else b""
                if isinstance(raw_email, tuple):
                    raw_email = raw_email[1]
            
            msg = email.message_from_bytes(raw_email)
            
            # Extract fields
            subject = _decode_str(msg.get("Subject", "No Subject"))
            from_addr = _decode_str(msg.get("From", "Unknown"))
            to_addr = _decode_str(msg.get("To", ""))
            date_str = msg.get("Date", "")
            
            # Parse date
            try:
                date_tuple = email.utils.parsedate_tz(date_str)
                if date_tuple:
                    date_obj = datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
                else:
                    date_obj = datetime.now()
            except:
                date_obj = datetime.now()
            
            # Extract body
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))
                    
                    # Skip attachments
                    if "attachment" in content_disposition:
                        continue
                    
                    if content_type == "text/plain":
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                charset = part.get_content_charset() or 'utf-8'
                                body = payload.decode(charset, errors='ignore')
                                break
                        except:
                            continue
                    
                    # Fallback to html if no plain
                    if not body and content_type == "text/html":
                        try:
                            payload = part.get_payload(decode=True)
                            if payload:
                                charset = part.get_content_charset() or 'utf-8'
                                html = payload.decode(charset, errors='ignore')
                                # Strip html tags simple
                                body = re.sub(r'<[^>]+>', '', html)
                                body = body[:2000]
                        except:
                            continue
            else:
                # Not multipart
                try:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        charset = msg.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='ignore')
                except:
                    body = str(msg.get_payload())[:2000]
            
            # Clean body
            body = body.strip()[:3000] if body else "(No body)"
            
            return {
                "id": email_id.decode() if isinstance(email_id, bytes) else str(email_id),
                "subject": subject[:200],
                "from": from_addr[:200],
                "to": to_addr[:200],
                "date": date_obj.isoformat(),
                "date_obj": date_obj,
                "body": body,
                "snippet": body[:200] + ("..." if len(body) > 200 else "")
            }
        except Exception as e:
            return {
                "id": str(email_id),
                "subject": f"Parse failed: {e}",
                "from": "Unknown",
                "to": "",
                "date": datetime.now().isoformat(),
                "body": f"Failed to parse email: {e}",
                "snippet": f"Failed: {e}"
            }
    
    def fetch_inbox(self, limit: int = 10, folder: str = "INBOX") -> List[Dict]:
        """Fetch latest emails from inbox"""
        if not self.is_configured:
            return [{"error": "Email not configured. Set EMAIL_IMAP_HOST, USER, PASS in .env. For Gmail use app password from myaccount.google.com/apppasswords, IMAP enabled."}]
        
        try:
            mail = self._connect_imap()
            mail.select(folder)
            
            # Search all emails
            status, messages = mail.search(None, "ALL")
            if status != "OK":
                mail.logout()
                return [{"error": f"IMAP search failed: {status}"}]
            
            email_ids = messages[0].split()
            # Get latest N
            latest_ids = email_ids[-limit:] if len(email_ids) > limit else email_ids
            latest_ids = list(reversed(latest_ids))  # newest first
            
            emails = []
            for eid in latest_ids:
                try:
                    status, msg_data = mail.fetch(eid, "(RFC822)")
                    if status == "OK":
                        parsed = self._parse_email(eid, msg_data[0])
                        # Remove date_obj for JSON serialization
                        parsed.pop("date_obj", None)
                        emails.append(parsed)
                except Exception as e:
                    emails.append({"id": eid.decode(), "subject": f"Fetch failed: {e}", "from": "Error", "body": str(e)})
            
            mail.logout()
            return emails
        
        except Exception as e:
            return [{"error": f"Fetch inbox failed: {e}. Check IMAP host {self.imap_host}, user, app password, and IMAP enabled in email settings."}]
    
    def search_emails(self, query: str, limit: int = 10, folder: str = "INBOX") -> List[Dict]:
        """Search emails by query (subject, from, body)"""
        if not self.is_configured:
            return [{"error": "Email not configured"}]
        
        try:
            mail = self._connect_imap()
            mail.select(folder)
            
            # Try IMAP SEARCH with TEXT (searches body and headers)
            # For Gmail, we can use: TEXT "query"
            safe_query = query.replace('"', '').replace('\\', '')[:100]
            
            try:
                # Try Gmail-style search
                status, messages = mail.search(None, f'TEXT "{safe_query}"')
                if status != "OK" or not messages[0]:
                    # Fallback to search all and filter locally
                    status, messages = mail.search(None, "ALL")
            except:
                status, messages = mail.search(None, "ALL")
            
            if status != "OK":
                mail.logout()
                return [{"error": f"Search failed: {status}"}]
            
            email_ids = messages[0].split()
            # For large mailboxes, only check last 100
            check_ids = email_ids[-100:] if len(email_ids) > 100 else email_ids
            check_ids = list(reversed(check_ids))
            
            matched = []
            query_lower = query.lower()
            
            for eid in check_ids:
                if len(matched) >= limit:
                    break
                try:
                    status, msg_data = mail.fetch(eid, "(RFC822)")
                    if status == "OK":
                        parsed = self._parse_email(eid, msg_data[0])
                        # Check if query matches subject, from, or body
                        if (query_lower in parsed.get("subject","").lower() or 
                            query_lower in parsed.get("from","").lower() or 
                            query_lower in parsed.get("body","").lower()):
                            parsed.pop("date_obj", None)
                            matched.append(parsed)
                except:
                    continue
            
            mail.logout()
            
            if not matched:
                return [{"info": f"No emails found for '{query}' in last 100 emails, Sir."}]
            
            return matched
        
        except Exception as e:
            return [{"error": f"Search emails failed: {e}"}]
    
    def read_email(self, email_id: str, folder: str = "INBOX") -> Dict:
        """Read single email by ID"""
        if not self.is_configured:
            return {"error": "Email not configured"}
        
        try:
            mail = self._connect_imap()
            mail.select(folder)
            
            # Email ID might be number
            eid = email_id.encode() if isinstance(email_id, str) else email_id
            
            status, msg_data = mail.fetch(eid, "(RFC822)")
            mail.logout()
            
            if status != "OK":
                return {"error": f"Failed to fetch email {email_id}: {status}"}
            
            parsed = self._parse_email(eid, msg_data[0])
            parsed.pop("date_obj", None)
            return parsed
        
        except Exception as e:
            return {"error": f"Read email {email_id} failed: {e}"}
    
    def send_email(self, to: str, subject: str, body: str, cc: str = None) -> str:
        """Send email securely via SMTP SSL/TLS"""
        if not self.smtp_host or not self.smtp_user or not self.smtp_pass:
            return "Email SMTP not configured, Sir. Set EMAIL_SMTP_HOST, USER, PASS in .env. For Gmail: smtp.gmail.com:587, app password. For Outlook: smtp.office365.com:587"
        
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.smtp_user
            msg['To'] = to
            msg['Subject'] = subject
            
            if cc:
                msg['Cc'] = cc
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Connect and send
            # Try TLS first (port 587), then SSL (465)
            if self.smtp_port == 465:
                # SSL
                context = ssl.create_default_context()
                server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context, timeout=15)
            else:
                # TLS
                server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15)
                server.ehlo()
                context = ssl.create_default_context()
                server.starttls(context=context)
                server.ehlo()
            
            server.login(self.smtp_user, self.smtp_pass)
            
            recipients = [to]
            if cc:
                recipients.extend([c.strip() for c in cc.split(",") if c.strip()])
            
            server.sendmail(self.smtp_user, recipients, msg.as_string())
            server.quit()
            
            return f"Email sent to {to}, Sir. Subject: {subject}. Via {self.smtp_host}."
        
        except Exception as e:
            return f"Send email to {to} failed, Sir: {e}. Check SMTP host {self.smtp_host}:{self.smtp_port}, user, app password, and that SMTP is enabled."
    
    def get_overview(self) -> Dict:
        """Get email overview - not fetching emails, just config status"""
        return {
            "configured": self.is_configured,
            "imap_host": self.imap_host or "not set",
            "smtp_host": self.smtp_host or "not set",
            "user": (self.imap_user[:3] + "***" + self.imap_user[-3:] if len(self.imap_user) > 6 else "not set") if self.imap_user else "not set",
            "instructions": "Set in .env: EMAIL_IMAP_HOST, EMAIL_IMAP_USER, EMAIL_IMAP_PASS, EMAIL_SMTP_HOST, SMTP_USER, SMTP_PASS, IMAP_PORT=993, SMTP_PORT=587. For Gmail: imap.gmail.com:993 + smtp.gmail.com:587, app password from myaccount.google.com/apppasswords, IMAP enabled. For Outlook: outlook.office365.com + smtp.office365.com"
        }

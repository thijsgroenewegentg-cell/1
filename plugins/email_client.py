"""Opt-in email plugin using standard IMAP/SMTP and environment variables.

No password is stored in MARK's repository or normal config file. Host, port
and username can be entered in the plugin settings screen or supplied through
environment variables. The password is always process-environment-only:

MARK_EMAIL_IMAP_HOST, MARK_EMAIL_IMAP_PORT (default 993),
MARK_EMAIL_SMTP_HOST, MARK_EMAIL_SMTP_PORT (default 465),
MARK_EMAIL_USERNAME, MARK_EMAIL_PASSWORD.

The send action is intentionally explicit: the model must provide recipient,
subject and body, and the tool reports exactly what was sent.
"""
from __future__ import annotations

import email
import imaplib
import os
import smtplib
from core import confirm as confirm_gate
from email.header import decode_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime


PLUGIN = {
    "name": "email_client",
    "description": (
        "Opt-in email helper for a user's own IMAP/SMTP mailbox. Use it to list "
        "recent inbox messages, search by text, read a message by number, or send "
        "an email when the local email settings and MARK_EMAIL_PASSWORD are configured. "
        "Never use this for an account that has not been configured."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "inbox | search | read | send"},
            "query": {"type": "STRING", "description": "Search text for search action"},
            "message_id": {"type": "STRING", "description": "Message number from inbox/search results"},
            "count": {"type": "INTEGER", "description": "Number of messages (default: 10)"},
            "recipient": {"type": "STRING", "description": "Email address for send"},
            "subject": {"type": "STRING", "description": "Subject for send"},
            "body": {"type": "STRING", "description": "Message body for send"},
        },
        "required": ["action"],
    },
}


def _port(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        return value if 1 <= value <= 65535 else default
    except (TypeError, ValueError):
        return default


def _settings(overrides: dict | None = None) -> dict:
    """Merge non-secret UI settings with environment values.

    Environment values win, while the password is deliberately environment-only
    and is never accepted from the plugin settings form.
    """
    try:
        from memory.config_manager import get_plugin_config
        stored = get_plugin_config("email_client")
    except Exception:
        stored = {}
    stored = {**stored, **(overrides or {})}

    def text(key: str, env_name: str) -> str:
        return os.environ.get(env_name, "").strip() or str(stored.get(key, "")).strip()

    def port(key: str, env_name: str, default: int) -> int:
        value = os.environ.get(env_name, str(stored.get(key, default)))
        try:
            value = int(value)
            return value if 1 <= value <= 65535 else default
        except (TypeError, ValueError):
            return default

    return {
        "imap_host": text("imap_host", "MARK_EMAIL_IMAP_HOST"),
        "imap_port": port("imap_port", "MARK_EMAIL_IMAP_PORT", 993),
        "smtp_host": text("smtp_host", "MARK_EMAIL_SMTP_HOST"),
        "smtp_port": port("smtp_port", "MARK_EMAIL_SMTP_PORT", 465),
        "username": text("username", "MARK_EMAIL_USERNAME"),
        "password": os.environ.get("MARK_EMAIL_PASSWORD", ""),
    }


def _require(settings: dict, *keys: str) -> str | None:
    missing = [key for key in keys if not settings.get(key)]
    if missing:
        return (
            "Email is not configured. Set the host, username and password in "
            "PLUGIN SETTINGS/environment; the password must be MARK_EMAIL_PASSWORD "
            f"(missing: {', '.join(missing)})."
        )
    return None


def _decode(value: str) -> str:
    pieces = []
    for chunk, encoding in decode_header(value or ""):
        if isinstance(chunk, bytes):
            pieces.append(chunk.decode(encoding or "utf-8", errors="replace"))
        else:
            pieces.append(str(chunk))
    return "".join(pieces).strip()


def _connect(settings: dict):
    error = _require(settings, "imap_host", "username", "password")
    if error:
        return None, error
    try:
        conn = imaplib.IMAP4_SSL(settings["imap_host"], settings["imap_port"])
        conn.login(settings["username"], settings["password"])
        conn.select("INBOX", readonly=True)
        return conn, None
    except Exception as exc:
        return None, f"Could not connect to the mailbox: {exc}"


def _test_connection(values: dict) -> tuple[bool, str]:
    settings = _settings(values)
    conn, error = _connect(settings)
    if error:
        return False, error
    try:
        smtp_state = "SMTP host is configured." if settings.get("smtp_host") else "SMTP host is not configured yet."
        return True, f"IMAP connection succeeded. {smtp_state}"
    finally:
        try:
            conn.logout()
        except Exception:
            pass


PLUGIN_SETTINGS = {
    "namespace": "email_client",
    "title": "EMAIL — IMAP / SMTP",
    "note": (
        "Host, port and username may be saved locally. The password is never saved "
        "here; set MARK_EMAIL_PASSWORD in MARK's launch environment."
    ),
    "fields": [
        {"key": "imap_host", "label": "IMAP host", "placeholder": "imap.example.com"},
        {"key": "imap_port", "label": "IMAP port", "default": 993},
        {"key": "smtp_host", "label": "SMTP host", "placeholder": "smtp.example.com"},
        {"key": "smtp_port", "label": "SMTP port", "default": 465},
        {"key": "username", "label": "Mailbox username"},
    ],
    "action": {"label": "TEST IMAP CONNECTION", "run": _test_connection},
}


def _header(conn, number: bytes) -> dict:
    code, data = conn.fetch(number, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])")
    if code != "OK":
        return {"id": number.decode(), "subject": "(unavailable)"}
    raw = b"".join(part for part in data if isinstance(part, tuple))
    message = email.message_from_bytes(raw)
    date = message.get("Date", "")
    try:
        date = parsedate_to_datetime(date).strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return {
        "id": number.decode(),
        "subject": _decode(message.get("Subject", "(no subject)")),
        "from": _decode(message.get("From", "")),
        "date": date,
    }


def _inbox(settings: dict, query: str, count: int) -> str:
    conn, error = _connect(settings)
    if error:
        return error
    try:
        criterion = f'(TEXT "{query.replace(chr(34), "")}")' if query else "ALL"
        code, data = conn.search(None, criterion)
        if code != "OK":
            return "Mailbox search failed."
        ids = data[0].split()[-count:][::-1]
        if not ids:
            return "No messages found."
        rows = [_header(conn, ident) for ident in ids]
        return "\n".join(
            f"{row['id']}: {row['date']} — {row['from']} — {row['subject']}"
            for row in rows
        )
    except Exception as exc:
        return f"Inbox lookup failed: {exc}"
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _read_message(settings: dict, message_id: str) -> str:
    conn, error = _connect(settings)
    if error:
        return error
    try:
        number = str(message_id or "").strip()
        if not number.isdigit():
            return "Provide the numeric message_id shown by inbox or search."
        code, data = conn.fetch(number.encode(), "(BODY.PEEK[])")
        if code != "OK":
            return "That message could not be read."
        raw = b"".join(part for part in data if isinstance(part, tuple))
        message = email.message_from_bytes(raw)
        body = ""
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_type() == "text/plain" and not part.get_filename():
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    break
        else:
            payload = message.get_payload(decode=True)
            body = (payload or b"").decode(message.get_content_charset() or "utf-8", errors="replace")
        return (
            f"From: {_decode(message.get('From', ''))}\n"
            f"Subject: {_decode(message.get('Subject', ''))}\n"
            f"Date: {message.get('Date', '')}\n\n{body[:12000]}"
        )
    except Exception as exc:
        return f"Reading the message failed: {exc}"
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _send(settings: dict, recipient: str, subject: str, body: str) -> str:
    error = _require(settings, "smtp_host", "username", "password")
    if error:
        return error
    if not recipient.strip() or not subject.strip() or not body.strip():
        return "Sending email requires recipient, subject and body. Nothing was sent."
    message = EmailMessage()
    message["From"] = settings["username"]
    message["To"] = recipient.strip()
    message["Subject"] = subject.strip()
    message.set_content(body)
    try:
        if settings["smtp_port"] == 465:
            with smtplib.SMTP_SSL(settings["smtp_host"], settings["smtp_port"], timeout=20) as smtp:
                smtp.login(settings["username"], settings["password"])
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings["smtp_host"], settings["smtp_port"], timeout=20) as smtp:
                smtp.starttls()
                smtp.login(settings["username"], settings["password"])
                smtp.send_message(message)
        return f"Email sent to {recipient.strip()} with subject {subject.strip()!r}."
    except Exception as exc:
        return f"Email was not sent: {exc}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "inbox")).strip().lower()
    settings = _settings()
    try:
        count = max(1, min(30, int(params.get("count", 10))))
    except (TypeError, ValueError):
        count = 10

    if action == "inbox":
        result = _inbox(settings, "", count)
    elif action == "search":
        result = _inbox(settings, str(params.get("query", "")).strip(), count)
    elif action == "read":
        result = _read_message(settings, str(params.get("message_id", "")))
    elif action == "send":
        recipient = str(params.get("recipient", "")).strip()
        subject = str(params.get("subject", "")).strip()
        body = str(params.get("body", ""))
        if not recipient or not subject or not body.strip():
            result = "Sending email requires recipient, subject and body. Nothing was sent."
        else:
            configuration_error = _require(settings, "smtp_host", "username", "password")
            if configuration_error:
                result = configuration_error
            else:
                preview = body.strip().replace("\n", " ")[:120]
                result = confirm_gate.request(
                    "email_send",
                    "Send email",
                    f"Send to {recipient}: {subject} — {preview}",
                    lambda: _send(settings, recipient, subject, body),
                )
    else:
        return "Unknown email action. Use inbox, search, read or send."

    if player:
        try:
            player.write_log(f"[Email] {action}")
        except Exception:
            pass
    return result

"""
Gmail API tools used by the Email Agent.
Handles OAuth2 auth, reading inbox, sending, and replying.
"""

import base64
import json
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config


def _get_gmail_service():
    creds = None
    token_path = config.GMAIL_TOKEN_FILE
    creds_path = config.GMAIL_CREDENTIALS_FILE

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), config.GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), config.GMAIL_SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def send_email(to: str, subject: str, body: str, reply_to_thread_id: Optional[str] = None) -> dict:
    """Send an email from the business address. Returns Gmail message dict."""
    service = _get_gmail_service()

    message = MIMEMultipart("alternative")
    message["to"] = to
    message["from"] = config.BUSINESS_EMAIL
    message["subject"] = subject
    message.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    payload: dict = {"raw": raw}
    if reply_to_thread_id:
        payload["threadId"] = reply_to_thread_id

    result = service.users().messages().send(userId="me", body=payload).execute()
    return result


def list_unread_emails(max_results: int = 20) -> list[dict]:
    """Return unread emails from the business inbox."""
    service = _get_gmail_service()
    resp = service.users().messages().list(
        userId="me",
        labelIds=["INBOX", "UNREAD"],
        maxResults=max_results,
    ).execute()

    messages = resp.get("messages", [])
    result = []
    for m in messages:
        full = service.users().messages().get(userId="me", id=m["id"], format="full").execute()
        result.append(_parse_message(full))
    return result


def get_email_thread(thread_id: str) -> list[dict]:
    """Fetch all messages in a thread."""
    service = _get_gmail_service()
    thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    return [_parse_message(m) for m in thread.get("messages", [])]


def mark_as_read(message_id: str) -> None:
    service = _get_gmail_service()
    service.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def _parse_message(msg: dict) -> dict:
    headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
    body = _extract_body(msg["payload"])
    return {
        "id": msg["id"],
        "thread_id": msg["threadId"],
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "body": body,
        "snippet": msg.get("snippet", ""),
    }


def _extract_body(payload: dict) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""

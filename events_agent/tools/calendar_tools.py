"""Google Calendar tools for scheduling recurring Saturday events."""

from datetime import datetime, timedelta
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import config


def _get_calendar_service():
    creds = None
    token_path = config.BASE_DIR / "credentials" / "gcal_token.json"
    creds_path = config.GMAIL_CREDENTIALS_FILE   # same GCP project

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), config.GCAL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), config.GCAL_SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def create_event(
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    description: str = "",
    location: str = config.EVENT_VENUE,
    attendees: Optional[list[str]] = None,
) -> dict:
    service = _get_calendar_service()
    body = {
        "summary": title,
        "location": location,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/New_York"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/New_York"},
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]

    return service.events().insert(calendarId=config.GCAL_CALENDAR_ID, body=body).execute()


def list_upcoming_saturdays(weeks_ahead: int = 8) -> list[datetime]:
    """Return the next N Saturday dates."""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days_until_sat = (5 - today.weekday()) % 7 or 7
    first_saturday = today + timedelta(days=days_until_sat)
    return [first_saturday + timedelta(weeks=i) for i in range(weeks_ahead)]


def get_upcoming_events(days_ahead: int = 60) -> list[dict]:
    service = _get_calendar_service()
    now = datetime.utcnow().isoformat() + "Z"
    future = (datetime.utcnow() + timedelta(days=days_ahead)).isoformat() + "Z"
    result = service.events().list(
        calendarId=config.GCAL_CALENDAR_ID,
        timeMin=now,
        timeMax=future,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return result.get("items", [])

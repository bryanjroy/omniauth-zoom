"""
Configuration for Needham Events Company agent system.
All secrets are loaded from environment variables / .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent

# ── Anthropic ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = "claude-opus-4-7"  # Most capable for autonomous operation

# ── Business identity ────────────────────────────────────────────────────────
COMPANY_NAME = "Needham Community Events"
OWNER_NAME = os.getenv("OWNER_NAME", "Event Organizer")
OWNER_EMAIL = os.environ["OWNER_EMAIL"]          # your personal inbox for approvals
BUSINESS_EMAIL = os.environ["BUSINESS_EMAIL"]    # the public-facing events inbox
BUSINESS_PHONE = os.getenv("BUSINESS_PHONE", "")
TOWN = "Needham"
STATE = "MA"

# ── Email (Gmail API OAuth2) ─────────────────────────────────────────────────
GMAIL_CREDENTIALS_FILE = BASE_DIR / "credentials" / "gmail_credentials.json"
GMAIL_TOKEN_FILE = BASE_DIR / "credentials" / "gmail_token.json"
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

# ── Google Calendar ──────────────────────────────────────────────────────────
GCAL_SCOPES = ["https://www.googleapis.com/auth/calendar"]
GCAL_CALENDAR_ID = os.getenv("GCAL_CALENDAR_ID", "primary")

# ── Database ─────────────────────────────────────────────────────────────────
DB_URL = f"sqlite:///{BASE_DIR / 'data' / 'events.db'}"

# ── SendGrid (transactional email fallback) ──────────────────────────────────
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")

# ── Twilio (SMS alerts to owner) ─────────────────────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
OWNER_PHONE = os.getenv("OWNER_PHONE", "")

# ── Recurring event defaults ─────────────────────────────────────────────────
EVENT_DAY_OF_WEEK = "saturday"
EVENT_START_TIME = "14:00"   # 2 PM local
EVENT_END_TIME = "20:00"     # 8 PM local
EVENT_VENUE = "Needham Town Hall, 1471 Highland Ave, Needham, MA 02492"
EVENT_CAPACITY = 150

# ── Permit lead times (days before event) ────────────────────────────────────
PERMIT_LEAD_DAYS = {
    "venue_reservation": 30,
    "special_event": 21,
    "alcohol_one_day_license": 30,    # MA ABCC one-day license
    "amusement_device": 14,           # bounce house
    "food_service": 14,
}

# ── Budget defaults (per event) ──────────────────────────────────────────────
DEFAULT_BUDGET = {
    "venue_rental": 500,
    "bartender": 300,
    "bounce_house_rental": 350,
    "bounce_house_operator": 200,
    "insurance_rider": 150,
    "marketing": 100,
    "supplies_misc": 200,
}

# ── Autonomous mode ──────────────────────────────────────────────────────────
# When True, agents act without owner approval for routine tasks.
# High-stakes actions (permit submissions, contracts >$500) always ping owner.
AUTONOMOUS_MODE = True
HIGH_STAKES_THRESHOLD_USD = 500

"""
Weather Agent — monitors the Saturday forecast for Needham, MA and coordinates
a cancellation across all other agents when conditions are dangerous.

Data source: OpenWeatherMap 5-day/3-hour forecast API (free tier).
Checked: Wednesday and Friday before each Saturday event.

Cancellation triggers (any one is sufficient):
  - Thunderstorm in forecast window
  - Snow ≥ 0.5 in/hr
  - Sustained wind ≥ 35 mph
  - Rain probability ≥ 80%
  - Temperature ≤ 20°F or ≥ 100°F

Cancellation flow:
  1. Agent detects bad forecast → SMS + email owner with recommendation
  2. Owner replies GO or CANCEL (email reply to business inbox)
  3. If CANCEL: agent notifies staff, sends subscriber email blast, updates DB
  4. If no reply by Friday noon: agent sends a second urgent alert

The event is indoors (Town Hall) so moderate rain alone isn't a cancel —
only severe weather that would prevent safe travel or outdoor setup
(bounce house must be set up outside or in a parking area).
"""

import logging
import requests
from datetime import datetime, timedelta
from agents.base_agent import BaseAgent
from database import SessionLocal, Event
from tools import email_tools, notification_tools
import config

logger = logging.getLogger(__name__)

# OpenWeatherMap free forecast endpoint
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

TOOL_DEFINITIONS = [
    {
        "name": "get_saturday_forecast",
        "description": (
            "Fetch the weather forecast for Needham, MA for the upcoming Saturday event window "
            "(noon–9 PM). Returns temperature, precipitation probability, wind, and conditions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_date": {
                    "type": "string",
                    "description": "ISO date string for the Saturday (YYYY-MM-DD)",
                },
            },
            "required": ["event_date"],
        },
    },
    {
        "name": "assess_cancellation_risk",
        "description": (
            "Given a forecast summary, apply the cancellation rules and return a risk level: "
            "LOW, MODERATE, or HIGH, with the specific triggers that were hit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "forecast_summary": {"type": "object"},
            },
            "required": ["forecast_summary"],
        },
    },
    {
        "name": "recommend_cancellation",
        "description": (
            "Send the owner an SMS + email with the forecast, the risk assessment, "
            "and a clear recommendation to cancel or proceed. Owner should reply to "
            "the business inbox with GO or CANCEL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "event_date": {"type": "string"},
                "risk_level": {"type": "string"},
                "triggers": {"type": "array", "items": {"type": "string"}},
                "forecast_summary": {"type": "string"},
            },
            "required": ["event_id", "event_date", "risk_level", "forecast_summary"],
        },
    },
    {
        "name": "execute_cancellation",
        "description": (
            "Carry out a confirmed cancellation: mark event cancelled in DB, "
            "email all staff, send a subscriber cancellation notice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "event_date": {"type": "string"},
                "weather_reason": {"type": "string"},
                "staff_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "subscriber_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["event_id", "event_date", "weather_reason"],
        },
    },
    {
        "name": "get_upcoming_events",
        "description": "Return upcoming Saturday events from the database.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_staff_emails_for_event",
        "description": "Return email addresses of all staff assigned to an event.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
]


def _ms_to_mph(ms: float) -> float:
    return ms * 2.237


def _mm_to_inches(mm: float) -> float:
    return mm / 25.4


def _kelvin_to_f(k: float) -> float:
    return (k - 273.15) * 9 / 5 + 32


class WeatherAgent(BaseAgent):
    name = "Weather Agent"
    tools = TOOL_DEFINITIONS
    system_prompt = (
        "You monitor weather forecasts for Saturday events in Needham, MA.\n\n"
        "Your job is to protect attendees, staff, and equipment from dangerous weather.\n\n"
        "Cancellation triggers (any single one warrants a CANCEL recommendation):\n"
        "  - Thunderstorm forecast during noon–9 PM window\n"
        "  - Snow ≥ 0.5 inches/hour\n"
        "  - Sustained winds ≥ 35 mph (bounce house cannot be safely operated)\n"
        "  - Rain probability ≥ 80% (outdoor setup and attendee travel)\n"
        "  - Temperature ≤ 20°F or ≥ 100°F\n\n"
        "Process:\n"
        "1. Get the forecast for the upcoming Saturday.\n"
        "2. Assess the risk level.\n"
        "3. If risk is HIGH: send owner a cancel recommendation via SMS + email.\n"
        "4. If risk is MODERATE: send owner a heads-up, suggest monitoring.\n"
        "5. If risk is LOW: log it and do nothing.\n"
        "6. If the owner confirms CANCEL: execute the full cancellation workflow "
        "   (DB update, staff notifications, subscriber email).\n\n"
        "Always be specific about what weather condition is the concern. "
        "Frame the message around safety and attendee experience, not just the rule."
    )

    def _dispatch_tool(self, tool_name: str, tool_input: dict):
        db = SessionLocal()
        try:
            if tool_name == "get_saturday_forecast":
                return self._fetch_forecast(tool_input["event_date"])

            if tool_name == "assess_cancellation_risk":
                return self._assess_risk(tool_input["forecast_summary"])

            if tool_name == "recommend_cancellation":
                return self._send_recommendation(tool_input)

            if tool_name == "execute_cancellation":
                return self._execute_cancellation(tool_input, db)

            if tool_name == "get_upcoming_events":
                events = (
                    db.query(Event)
                    .filter(Event.date >= datetime.utcnow())
                    .filter(Event.status != "cancelled")
                    .order_by(Event.date)
                    .all()
                )
                return [{"id": e.id, "date": e.date.isoformat()} for e in events]

            if tool_name == "get_staff_emails_for_event":
                from database import StaffAssignment, Staff
                assignments = (
                    db.query(StaffAssignment)
                    .filter(StaffAssignment.event_id == tool_input["event_id"])
                    .all()
                )
                emails = []
                for a in assignments:
                    staff = db.query(Staff).get(a.staff_id)
                    if staff and staff.email:
                        emails.append(staff.email)
                return emails

        finally:
            db.close()

        raise ValueError(f"Unknown tool: {tool_name}")

    def _fetch_forecast(self, event_date: str) -> dict:
        if not config.OPENWEATHER_API_KEY:
            return {"error": "OPENWEATHER_API_KEY not set"}

        resp = requests.get(
            OWM_FORECAST_URL,
            params={
                "lat": config.VENUE_LAT,
                "lon": config.VENUE_LON,
                "appid": config.OPENWEATHER_API_KEY,
                "cnt": 40,  # 5 days of 3-hour slots
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # Filter to Saturday event window: noon–9 PM local (17:00–02:00 UTC, rough)
        target_date = datetime.fromisoformat(event_date).date()
        window_slots = []
        for slot in data.get("list", []):
            slot_dt = datetime.utcfromtimestamp(slot["dt"])
            if slot_dt.date() == target_date and 12 <= slot_dt.hour <= 21:
                window_slots.append(slot)

        if not window_slots:
            return {"error": f"No forecast data found for {event_date}. May be too far out."}

        # Aggregate across the window
        temps_f = [_kelvin_to_f(s["main"]["temp"]) for s in window_slots]
        wind_mph = [_ms_to_mph(s["wind"]["speed"]) for s in window_slots]
        rain_probs = [s.get("pop", 0) * 100 for s in window_slots]
        conditions = list({s["weather"][0]["main"] for s in window_slots})
        descriptions = list({s["weather"][0]["description"] for s in window_slots})
        rain_mm = sum(s.get("rain", {}).get("3h", 0) for s in window_slots)
        snow_mm = sum(s.get("snow", {}).get("3h", 0) for s in window_slots)

        return {
            "event_date": event_date,
            "temp_low_f": round(min(temps_f), 1),
            "temp_high_f": round(max(temps_f), 1),
            "wind_max_mph": round(max(wind_mph), 1),
            "rain_probability_max_pct": round(max(rain_probs), 0),
            "rain_total_inches": round(_mm_to_inches(rain_mm), 2),
            "snow_total_inches": round(_mm_to_inches(snow_mm), 2),
            "conditions": conditions,
            "descriptions": descriptions,
            "slots_checked": len(window_slots),
        }

    def _assess_risk(self, forecast: dict) -> dict:
        if "error" in forecast:
            return {"risk_level": "UNKNOWN", "triggers": [forecast["error"]]}

        rules = config.WEATHER_CANCEL_RULES
        triggers = []

        if any("Thunderstorm" in c for c in forecast.get("conditions", [])):
            triggers.append("Thunderstorm in forecast window")

        if forecast.get("snow_total_inches", 0) >= rules["snow_inches_per_hour"]:
            triggers.append(f"Snow: {forecast['snow_total_inches']} inches expected")

        if forecast.get("wind_max_mph", 0) >= rules["wind_mph"]:
            triggers.append(f"Wind: {forecast['wind_max_mph']} mph (bounce house unsafe above {rules['wind_mph']} mph)")

        if forecast.get("rain_probability_max_pct", 0) >= rules["rain_probability_pct"]:
            triggers.append(f"Rain probability: {forecast['rain_probability_max_pct']}%")

        if forecast.get("temp_low_f", 99) <= rules["temp_low_f"]:
            triggers.append(f"Temperature: low of {forecast['temp_low_f']}°F (threshold: {rules['temp_low_f']}°F)")

        if forecast.get("temp_high_f", 0) >= rules["temp_high_f"]:
            triggers.append(f"Temperature: high of {forecast['temp_high_f']}°F (threshold: {rules['temp_high_f']}°F)")

        if triggers:
            risk = "HIGH"
        elif forecast.get("rain_probability_max_pct", 0) >= 50:
            risk = "MODERATE"
        else:
            risk = "LOW"

        return {"risk_level": risk, "triggers": triggers}

    def _send_recommendation(self, tool_input: dict) -> dict:
        risk = tool_input["risk_level"]
        event_date = tool_input["event_date"]
        triggers = tool_input.get("triggers", [])
        forecast_summary = tool_input["forecast_summary"]

        if risk == "HIGH":
            action_line = "RECOMMENDATION: CANCEL this event."
            urgency = "ACTION REQUIRED"
        else:
            action_line = "RECOMMENDATION: Monitor closely. No action needed yet."
            urgency = "Weather Alert"

        trigger_lines = "\n".join(f"  • {t}" for t in triggers) if triggers else "  (none)"

        body = (
            f"Weather check for your Saturday event ({event_date}):\n\n"
            f"Risk Level: {risk}\n\n"
            f"Forecast:\n{forecast_summary}\n\n"
            f"Cancellation triggers hit:\n{trigger_lines}\n\n"
            f"{action_line}\n\n"
            f"To cancel: reply to this email with the word CANCEL.\n"
            f"To proceed: reply with GO.\n\n"
            f"If no reply is received by Friday at noon, a follow-up alert will be sent."
        )

        notification_tools.notify_owner(
            subject=f"[{urgency}] Saturday Event Weather — {event_date}",
            body=body,
            sms=(risk == "HIGH"),
        )

        return {"status": "recommendation_sent", "risk_level": risk}

    def _execute_cancellation(self, tool_input: dict, db) -> dict:
        event_id = tool_input["event_id"]
        event_date = tool_input["event_date"]
        reason = tool_input["weather_reason"]

        # Mark event cancelled in DB
        event = db.query(Event).get(event_id)
        if event:
            event.status = "cancelled"
            event.notes = (event.notes or "") + f"\nCancelled due to weather: {reason}"
            db.commit()

        # Notify staff
        for email in tool_input.get("staff_emails", []):
            email_tools.send_email(
                to=email,
                subject=f"Event Cancelled — {event_date} — Weather",
                body=(
                    f"Hi,\n\n"
                    f"Unfortunately we need to cancel this Saturday's event ({event_date}) "
                    f"due to weather conditions: {reason}.\n\n"
                    f"We'll be in touch to reschedule. Thank you for your flexibility.\n\n"
                    f"— {config.COMPANY_NAME}"
                ),
            )

        # Notify subscribers
        for email in tool_input.get("subscriber_emails", []):
            email_tools.send_email(
                to=email,
                subject=f"This Saturday's Event is Cancelled — Weather",
                body=(
                    f"Hi neighbor,\n\n"
                    f"Due to {reason.lower()}, we've made the difficult decision to cancel "
                    f"this Saturday's community event ({event_date}).\n\n"
                    f"Safety first — we'll see you next Saturday!\n\n"
                    f"— {config.COMPANY_NAME}\n{config.BUSINESS_EMAIL}"
                ),
            )

        logger.info("Event %s cancelled due to weather: %s", event_id, reason)
        return {
            "status": "cancelled",
            "staff_notified": len(tool_input.get("staff_emails", [])),
            "subscribers_notified": len(tool_input.get("subscriber_emails", [])),
        }

    # ── Public entry points ───────────────────────────────────────────────────

    def check_upcoming_weather(self) -> str:
        return self.run(
            "Check the weather forecast for the next Saturday event. "
            "Assess the cancellation risk and take appropriate action: "
            "notify the owner if risk is MODERATE or HIGH, do nothing if LOW. "
            "Report what you found and what you did."
        )

    def process_owner_cancellation(self, event_id: int, event_date: str) -> str:
        return self.run(
            f"The owner has confirmed cancellation of event {event_id} on {event_date}. "
            "Get the staff emails for this event, then execute the full cancellation: "
            "update the database, notify all staff, and send a cancellation notice "
            "to subscribers. Report when complete."
        )

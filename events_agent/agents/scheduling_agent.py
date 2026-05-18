"""
Scheduling Agent — creates and maintains recurring Saturday events
in both the DB and Google Calendar. Triggers all other agents
on the appropriate lead-time schedule.
"""

import logging
from datetime import datetime, time
from agents.base_agent import BaseAgent
from database import SessionLocal, Event
from tools import calendar_tools
import config

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "list_upcoming_saturdays",
        "description": "Return the next N Saturday dates.",
        "input_schema": {
            "type": "object",
            "properties": {"weeks_ahead": {"type": "integer", "default": 8}},
        },
    },
    {
        "name": "create_event_in_db",
        "description": "Create an event record in the database for a given Saturday.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "ISO datetime string"},
                "notes": {"type": "string"},
            },
            "required": ["date"],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Create a Google Calendar event for a Saturday event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_date": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["event_date"],
        },
    },
    {
        "name": "get_scheduled_events",
        "description": "List all events in the database.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_event",
        "description": "Mark an event as cancelled.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["event_id"],
        },
    },
]


class SchedulingAgent(BaseAgent):
    name = "Scheduling Agent"
    tools = TOOL_DEFINITIONS
    system_prompt = (
        "You manage the event schedule for Needham Community Events.\n\n"
        "Your job:\n"
        "1. Ensure all upcoming Saturday events (next 8 weeks) exist in the database.\n"
        "2. Create matching Google Calendar entries.\n"
        "3. Never duplicate an existing event.\n"
        "4. Events run every Saturday, 2:00 PM – 8:00 PM at Needham Town Hall.\n\n"
        "Run this check weekly (every Monday) to stay 8 weeks ahead."
    )

    def _dispatch_tool(self, tool_name: str, tool_input: dict):
        db = SessionLocal()
        try:
            if tool_name == "list_upcoming_saturdays":
                weeks = tool_input.get("weeks_ahead", 8)
                saturdays = calendar_tools.list_upcoming_saturdays(weeks)
                return [s.isoformat() for s in saturdays]

            if tool_name == "create_event_in_db":
                event_dt = datetime.fromisoformat(tool_input["date"])
                # Check for duplicate
                existing = db.query(Event).filter(
                    Event.date >= event_dt.replace(hour=0, minute=0),
                    Event.date <= event_dt.replace(hour=23, minute=59),
                    Event.status != "cancelled",
                ).first()
                if existing:
                    return {"status": "already_exists", "event_id": existing.id}

                start = event_dt.replace(hour=14, minute=0)
                event = Event(date=start, notes=tool_input.get("notes", ""))
                db.add(event)
                db.commit()
                db.refresh(event)
                return {"event_id": event.id, "date": start.isoformat(), "status": "created"}

            if tool_name == "create_calendar_event":
                event_dt = datetime.fromisoformat(tool_input["event_date"])
                start_dt = event_dt.replace(hour=14, minute=0)
                end_dt = event_dt.replace(hour=20, minute=0)
                title = tool_input.get("title", f"{config.COMPANY_NAME} Saturday Event")
                description = tool_input.get(
                    "description",
                    "Weekly community event at Needham Town Hall. "
                    "Cash bar, bounce house, community fun!"
                )
                result = calendar_tools.create_event(
                    title=title,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    description=description,
                )
                return {"calendar_event_id": result.get("id"), "link": result.get("htmlLink")}

            if tool_name == "get_scheduled_events":
                events = (
                    db.query(Event)
                    .filter(Event.date >= datetime.utcnow())
                    .order_by(Event.date)
                    .all()
                )
                return [
                    {"id": e.id, "date": e.date.isoformat(), "status": e.status}
                    for e in events
                ]

            if tool_name == "cancel_event":
                event = db.query(Event).get(tool_input["event_id"])
                if not event:
                    return {"error": "Event not found"}
                event.status = "cancelled"
                event.notes = (event.notes or "") + f"\nCancelled: {tool_input.get('reason', '')}"
                db.commit()
                return {"status": "cancelled"}

        finally:
            db.close()

        raise ValueError(f"Unknown tool: {tool_name}")

    def schedule_upcoming_events(self) -> str:
        return self.run(
            "Ensure all Saturday events for the next 8 weeks exist in the database "
            "and on Google Calendar. Create any that are missing. Report what was done."
        )

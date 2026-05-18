"""
Permit Agent — tracks and manages all permits required for Needham events.

Permits required for each Saturday event:
  1. Needham Town Hall Venue Reservation — Recreation Dept, (781) 455-7520
  2. Special Event Permit — Town Manager's office, 30 days lead
  3. MA ABCC One-Day Alcohol License — filed with local licensing authority, 30 days lead
  4. Amusement Device / Bounce House Permit — Building Dept or Board of Health
  5. Certificate of Insurance (COI) — $1M general liability, town named as additional insured

Timeline for a Saturday event:
  Week -5: File venue reservation + special event permit
  Week -4: File ABCC one-day license application
  Week -3: File bounce-house permit; confirm COI from insurer
  Week -1: Confirm all approvals; follow up on outstanding items
"""

import json
import logging
from datetime import datetime
from agents.base_agent import BaseAgent
from database import SessionLocal, Permit, Event, PermitStatus
from tools import email_tools, notification_tools
import config

logger = logging.getLogger(__name__)

# Needham-specific permit contacts (pre-populated knowledge base)
PERMIT_CONTACTS = {
    "venue_reservation": {
        "office": "Needham Recreation Department",
        "phone": "(781) 455-7520",
        "email": "recreation@needhamma.gov",
        "address": "1471 Highland Ave, Needham, MA 02492",
        "notes": "Reserve Town Hall Great Room. Application + $500 fee. 30-day lead time.",
        "form_url": "https://www.needhamma.gov/recreation",
    },
    "special_event": {
        "office": "Needham Town Manager's Office",
        "phone": "(781) 455-7500",
        "email": "townmanager@needhamma.gov",
        "address": "1471 Highland Ave, Needham, MA 02492",
        "notes": "Special Event Permit required for events >50 people. 30-day lead.",
        "form_url": "https://www.needhamma.gov/specialevents",
    },
    "alcohol_one_day_license": {
        "office": "Needham Licensing Authority / Town Clerk",
        "phone": "(781) 455-7500",
        "email": "townclerk@needhamma.gov",
        "address": "1471 Highland Ave, Needham, MA 02492",
        "notes": (
            "MA ABCC One-Day License (M.G.L. c. 138 §14). "
            "File with local licensing authority 30 days before event. "
            "$50-$100 fee. Bartender must hold Pouring Permit or work under license. "
            "TIPS certification strongly recommended."
        ),
        "state_url": "https://www.mass.gov/how-to/apply-for-a-one-day-liquor-license",
    },
    "insurance": {
        "notes": (
            "General liability minimum $1,000,000 per occurrence, $2,000,000 aggregate. "
            "Town of Needham must be named as Additional Insured. "
            "Liquor liability (host liquor) endorsement required if serving alcohol. "
            "Request COI from your insurer at least 3 weeks before event."
        ),
    },
}

TOOL_DEFINITIONS = [
    {
        "name": "get_permit_status",
        "description": "Check the status of all permits for a given event.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "create_permit_record",
        "description": "Create a new permit record in the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "permit_type": {"type": "string"},
                "status": {"type": "string", "default": "needed"},
                "contact_name": {"type": "string"},
                "contact_email": {"type": "string"},
                "contact_phone": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["event_id", "permit_type"],
        },
    },
    {
        "name": "update_permit_status",
        "description": "Update the status of an existing permit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "permit_id": {"type": "integer"},
                "status": {"type": "string"},
                "reference_number": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["permit_id", "status"],
        },
    },
    {
        "name": "draft_permit_email",
        "description": "Draft and send a permit application email to the appropriate town office.",
        "input_schema": {
            "type": "object",
            "properties": {
                "permit_type": {"type": "string"},
                "event_date": {"type": "string", "description": "ISO format date"},
                "additional_details": {"type": "string"},
            },
            "required": ["permit_type", "event_date"],
        },
    },
    {
        "name": "get_permit_contact_info",
        "description": "Get contact info and requirements for a specific permit type.",
        "input_schema": {
            "type": "object",
            "properties": {"permit_type": {"type": "string"}},
            "required": ["permit_type"],
        },
    },
    {
        "name": "notify_owner_permit_issue",
        "description": "Alert the owner when a permit is denied, delayed, or needs their signature.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["subject", "message"],
        },
    },
    {
        "name": "list_upcoming_events",
        "description": "List events in the DB that need permit work.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


class PermitAgent(BaseAgent):
    name = "Permit Agent"
    tools = TOOL_DEFINITIONS
    system_prompt = (
        "You manage permits and compliance for weekly Saturday events at Needham Town Hall.\n\n"
        "For EVERY Saturday event you must ensure these permits are obtained:\n"
        "1. Venue Reservation (Needham Recreation Dept) — 30+ days out\n"
        "2. Special Event Permit (Town Manager) — 30+ days out\n"
        "3. MA ABCC One-Day Alcohol License — 30 days out, filed through town licensing authority\n"
        "4. Certificate of Insurance ($1M GL, town as additional insured) — 21 days out\n\n"
        "Steps:\n"
        "- Check upcoming events and their permit status.\n"
        "- For any missing permits that are past their lead-time threshold, draft and send "
        "  the appropriate email to the town office.\n"
        "- Update DB records after each action.\n"
        "- Escalate to owner for denied permits or anything requiring a signature / in-person visit.\n"
        "- Always note that events are recurring (weekly Saturdays) in applications so the town "
        "  is aware — this may allow blanket permits covering multiple dates."
    )

    def _dispatch_tool(self, tool_name: str, tool_input: dict):
        db = SessionLocal()
        try:
            if tool_name == "get_permit_status":
                permits = db.query(Permit).filter(Permit.event_id == tool_input["event_id"]).all()
                return [
                    {
                        "id": p.id,
                        "type": p.permit_type,
                        "status": p.status.value,
                        "submitted": p.submitted_date.isoformat() if p.submitted_date else None,
                        "reference": p.reference_number,
                    }
                    for p in permits
                ]

            if tool_name == "create_permit_record":
                permit = Permit(
                    event_id=tool_input["event_id"],
                    permit_type=tool_input["permit_type"],
                    status=PermitStatus(tool_input.get("status", "needed")),
                    contact_name=tool_input.get("contact_name"),
                    contact_email=tool_input.get("contact_email"),
                    contact_phone=tool_input.get("contact_phone"),
                    notes=tool_input.get("notes"),
                )
                db.add(permit)
                db.commit()
                db.refresh(permit)
                return {"permit_id": permit.id, "status": "created"}

            if tool_name == "update_permit_status":
                permit = db.query(Permit).get(tool_input["permit_id"])
                if not permit:
                    return {"error": "Permit not found"}
                permit.status = PermitStatus(tool_input["status"])
                if tool_input.get("reference_number"):
                    permit.reference_number = tool_input["reference_number"]
                if tool_input.get("notes"):
                    permit.notes = (permit.notes or "") + "\n" + tool_input["notes"]
                if tool_input["status"] == "submitted":
                    permit.submitted_date = datetime.utcnow()
                elif tool_input["status"] == "approved":
                    permit.approved_date = datetime.utcnow()
                db.commit()
                return {"status": "updated"}

            if tool_name == "draft_permit_email":
                ptype = tool_input["permit_type"]
                info = PERMIT_CONTACTS.get(ptype, {})
                if not info:
                    return {"error": f"No contact info for permit type: {ptype}"}

                event_date = tool_input["event_date"]
                extra = tool_input.get("additional_details", "")

                body = self._build_permit_email_body(ptype, event_date, info, extra)
                recipient = info.get("email", config.OWNER_EMAIL)

                result = email_tools.send_email(
                    to=recipient,
                    subject=f"Permit Application — {config.COMPANY_NAME} — {event_date}",
                    body=body,
                )
                logger.info("Permit email sent for %s on %s", ptype, event_date)
                return {"sent_to": recipient, "message_id": result.get("id")}

            if tool_name == "get_permit_contact_info":
                info = PERMIT_CONTACTS.get(tool_input["permit_type"], {})
                return info if info else {"error": "Unknown permit type"}

            if tool_name == "notify_owner_permit_issue":
                notification_tools.notify_owner(
                    subject=tool_input["subject"],
                    body=tool_input["message"],
                    sms=True,
                )
                return {"status": "owner_notified"}

            if tool_name == "list_upcoming_events":
                events = (
                    db.query(Event)
                    .filter(Event.date >= datetime.utcnow())
                    .filter(Event.status != "cancelled")
                    .order_by(Event.date)
                    .all()
                )
                return [
                    {
                        "id": e.id,
                        "date": e.date.isoformat(),
                        "status": e.status,
                        "permits": [
                            {"type": p.permit_type, "status": p.status.value}
                            for p in e.permits
                        ],
                    }
                    for e in events
                ]

        finally:
            db.close()

        raise ValueError(f"Unknown tool: {tool_name}")

    def _build_permit_email_body(self, ptype: str, event_date: str, info: dict, extra: str) -> str:
        templates = {
            "venue_reservation": (
                f"Dear {info.get('office', 'Town Office')},\n\n"
                f"My name is {config.OWNER_NAME} and I am the organizer of {config.COMPANY_NAME}, "
                f"a community events company based in Needham. We are planning a recurring series "
                f"of family-friendly Saturday events at Needham Town Hall.\n\n"
                f"We would like to reserve the Town Hall Great Room for our next event on "
                f"{event_date} from 2:00 PM to 8:00 PM. We anticipate up to {config.EVENT_CAPACITY} "
                f"attendees. Activities will include a cash bar (with appropriate licensing) and "
                f"a bounce house for children.\n\n"
                f"We are interested in establishing a recurring reservation for future Saturdays "
                f"as well. Could you please send us the reservation form and fee schedule?\n\n"
                f"{extra}\n\n"
                f"We are happy to provide a certificate of insurance naming the Town as additional "
                f"insured. Please let us know what is required.\n\n"
                f"Thank you for your time.\n\nBest regards,\n{config.OWNER_NAME}\n"
                f"{config.COMPANY_NAME}\n{config.BUSINESS_EMAIL}\n{config.BUSINESS_PHONE}"
            ),
            "alcohol_one_day_license": (
                f"Dear {info.get('office', 'Licensing Authority')},\n\n"
                f"I am writing to apply for a One-Day Alcohol License under M.G.L. c. 138 §14 "
                f"for an event on {event_date}.\n\n"
                f"Event details:\n"
                f"  Organizer: {config.COMPANY_NAME} / {config.OWNER_NAME}\n"
                f"  Date: {event_date}, 2:00 PM – 8:00 PM\n"
                f"  Location: Needham Town Hall, 1471 Highland Ave, Needham MA 02492\n"
                f"  Expected attendance: up to {config.EVENT_CAPACITY} guests\n"
                f"  Type of service: Cash bar staffed by a TIPS-certified bartender\n\n"
                f"We will provide a certificate of general liability and liquor liability insurance. "
                f"Please let us know the fee and any additional documentation required.\n\n"
                f"{extra}\n\n"
                f"Sincerely,\n{config.OWNER_NAME}\n"
                f"{config.COMPANY_NAME}\n{config.BUSINESS_EMAIL}\n{config.BUSINESS_PHONE}"
            ),
            "amusement_device": (
                f"Dear {info.get('office', 'Building Department')},\n\n"
                f"I am writing to inquire about permit requirements for operating an inflatable "
                f"bounce house at a private event at Needham Town Hall on {event_date}.\n\n"
                f"The bounce house will be provided by a licensed vendor who carries their own "
                f"liability insurance and whose equipment is certified under ASTM F24 standards. "
                f"We will have a trained operator on-site at all times.\n\n"
                f"Could you please confirm whether a permit is required, the applicable fee, "
                f"and any inspection requirements?\n\n"
                f"{extra}\n\n"
                f"Thank you,\n{config.OWNER_NAME}\n"
                f"{config.COMPANY_NAME}\n{config.BUSINESS_EMAIL}\n{config.BUSINESS_PHONE}"
            ),
            "special_event": (
                f"Dear {info.get('office', 'Town Manager')},\n\n"
                f"I am submitting a Special Event Permit application for a community event "
                f"on {event_date} at Needham Town Hall.\n\n"
                f"Event: {config.COMPANY_NAME} Saturday Community Gathering\n"
                f"Date: {event_date}, 2:00 PM – 8:00 PM\n"
                f"Location: Needham Town Hall, 1471 Highland Ave\n"
                f"Expected attendance: ~{config.EVENT_CAPACITY} people\n"
                f"Activities: Community socializing, cash bar (licensed), bounce house\n"
                f"Organizer: {config.OWNER_NAME}, {config.BUSINESS_EMAIL}, {config.BUSINESS_PHONE}\n\n"
                f"We will provide proof of $1M general liability insurance with the Town named "
                f"as additional insured. Please let us know what other documentation is needed.\n\n"
                f"{extra}\n\n"
                f"Respectfully,\n{config.OWNER_NAME}\n{config.COMPANY_NAME}"
            ),
        }
        return templates.get(ptype, f"Permit application for {ptype} on {event_date}.\n\n{extra}")

    def check_and_file_permits(self, weeks_ahead: int = 6) -> str:
        return self.run(
            f"Check all events in the next {weeks_ahead} weeks. "
            "For each event, verify all 5 required permits are tracked. "
            "File any applications that are past their lead-time deadline. "
            "Report what was done and what is still pending."
        )

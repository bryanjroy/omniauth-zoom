"""
Staffing Agent — sources, vets, and schedules bartenders,
event staff, and bounce-house operators for each Saturday event.

MA requirements for bartenders:
- TIPS certification (Training for Intervention ProcedureS) strongly recommended
- Must be 18+ to serve; 21+ if handling distilled spirits in some venues
- For One-Day License events, bartender works under the license holder's authorization

Bounce-house operators:
- NAARSO-certified or vendor-trained
- Must be on-site at all times the inflatable is in use
"""

import logging
from agents.base_agent import BaseAgent
from database import SessionLocal, Staff, StaffAssignment, Event
from tools import email_tools, notification_tools
import config

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "list_available_staff",
        "description": "List all active staff members for a given role.",
        "input_schema": {
            "type": "object",
            "properties": {"role": {"type": "string"}},
        },
    },
    {
        "name": "add_staff_member",
        "description": "Add a new staff member to the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "role": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "tips_certified": {"type": "boolean"},
                "hourly_rate": {"type": "number"},
                "notes": {"type": "string"},
            },
            "required": ["name", "role"],
        },
    },
    {
        "name": "assign_staff_to_event",
        "description": "Assign a staff member to an event.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "staff_id": {"type": "integer"},
                "role": {"type": "string"},
            },
            "required": ["event_id", "staff_id", "role"],
        },
    },
    {
        "name": "send_availability_request",
        "description": "Email a staff member to confirm availability for a date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "staff_id": {"type": "integer"},
                "event_date": {"type": "string"},
                "role": {"type": "string"},
                "rate": {"type": "number"},
            },
            "required": ["staff_id", "event_date", "role"],
        },
    },
    {
        "name": "send_job_posting_email",
        "description": (
            "Draft a job posting email for open positions. "
            "Sends to a recipient list (e.g., local bartending networks)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "event_date": {"type": "string"},
                "rate": {"type": "number"},
                "recipient_email": {"type": "string"},
            },
            "required": ["role", "event_date", "recipient_email"],
        },
    },
    {
        "name": "confirm_staff_assignment",
        "description": "Mark a staff assignment as confirmed after the person replies yes.",
        "input_schema": {
            "type": "object",
            "properties": {"assignment_id": {"type": "integer"}},
            "required": ["assignment_id"],
        },
    },
    {
        "name": "get_event_staffing_status",
        "description": "Get the staffing status for an event.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
]

# Minimum staffing per event
MINIMUM_STAFF = {
    "bartender": 1,
    "event_staff": 1,        # general floor host
    "bounce_house_operator": 1,
}


class StaffingAgent(BaseAgent):
    name = "Staffing Agent"
    tools = TOOL_DEFINITIONS
    system_prompt = (
        "You manage staffing for weekly Saturday events at Needham Town Hall.\n\n"
        "Minimum per event:\n"
        "  - 1 TIPS-certified bartender (rate: ~$30-40/hr)\n"
        "  - 1 event host / floor staff (rate: ~$20/hr)\n"
        "  - 1 bounce-house operator (often provided by vendor, verify)\n\n"
        "Process:\n"
        "1. Check upcoming events for staffing gaps.\n"
        "2. Contact known staff for availability first.\n"
        "3. If no available staff, send job posting to local bartending networks.\n"
        "4. Confirm assignments once staff confirms via email.\n"
        "5. Remind all staff 48 hours before event.\n\n"
        "Compliance notes:\n"
        "- Bartender must be TIPS certified for events with an alcohol license.\n"
        "- Bounce-house operator must be on-site whenever inflatable is in use.\n"
        "- Always record hourly rate in DB for payroll."
    )

    def _dispatch_tool(self, tool_name: str, tool_input: dict):
        db = SessionLocal()
        try:
            if tool_name == "list_available_staff":
                query = db.query(Staff).filter(Staff.is_active == True)
                if tool_input.get("role"):
                    query = query.filter(Staff.role == tool_input["role"])
                staff = query.all()
                return [
                    {
                        "id": s.id,
                        "name": s.name,
                        "role": s.role,
                        "email": s.email,
                        "phone": s.phone,
                        "tips_certified": s.tips_certified,
                        "hourly_rate": s.hourly_rate,
                    }
                    for s in staff
                ]

            if tool_name == "add_staff_member":
                staff = Staff(**{k: v for k, v in tool_input.items()})
                db.add(staff)
                db.commit()
                db.refresh(staff)
                return {"staff_id": staff.id, "status": "added"}

            if tool_name == "assign_staff_to_event":
                assignment = StaffAssignment(
                    event_id=tool_input["event_id"],
                    staff_id=tool_input["staff_id"],
                    role=tool_input["role"],
                )
                db.add(assignment)
                db.commit()
                db.refresh(assignment)
                return {"assignment_id": assignment.id}

            if tool_name == "send_availability_request":
                staff = db.query(Staff).get(tool_input["staff_id"])
                if not staff or not staff.email:
                    return {"error": "Staff not found or no email"}

                rate_line = f"Rate: ${tool_input.get('rate', 'TBD')}/hr" if tool_input.get("rate") else ""
                body = (
                    f"Hi {staff.name},\n\n"
                    f"We have an upcoming event and would love to have you on the team!\n\n"
                    f"Role: {tool_input['role']}\n"
                    f"Date: {tool_input['event_date']}, 1:30 PM – 8:30 PM\n"
                    f"Location: Needham Town Hall, 1471 Highland Ave, Needham MA\n"
                    f"{rate_line}\n\n"
                    f"Please reply YES or NO to confirm your availability.\n\n"
                    f"Thanks!\nThe Needham Community Events Team"
                )
                result = email_tools.send_email(
                    to=staff.email,
                    subject=f"Availability Check — {tool_input['event_date']}",
                    body=body,
                )
                return {"sent": True, "message_id": result.get("id")}

            if tool_name == "send_job_posting_email":
                body = (
                    f"Hi,\n\n"
                    f"Needham Community Events is hiring for our Saturday event series!\n\n"
                    f"Position: {tool_input['role'].replace('_', ' ').title()}\n"
                    f"Date: {tool_input['event_date']}\n"
                    f"Time: 1:30 PM – 8:30 PM\n"
                    f"Location: Needham Town Hall, 1471 Highland Ave, Needham MA\n"
                    f"Pay: ${tool_input.get('rate', 'competitive')}/hr\n\n"
                    f"Requirements:\n"
                    f"  - TIPS certification (for bartender role)\n"
                    f"  - Reliable, professional, community-oriented\n\n"
                    f"To apply, reply to this email with your experience and availability.\n\n"
                    f"Needham Community Events\n{config.BUSINESS_EMAIL}"
                )
                result = email_tools.send_email(
                    to=tool_input["recipient_email"],
                    subject=f"[Hiring] {tool_input['role'].replace('_', ' ').title()} — {tool_input['event_date']}",
                    body=body,
                )
                return {"sent": True}

            if tool_name == "confirm_staff_assignment":
                assignment = db.query(StaffAssignment).get(tool_input["assignment_id"])
                if not assignment:
                    return {"error": "Assignment not found"}
                assignment.confirmed = True
                db.commit()
                return {"status": "confirmed"}

            if tool_name == "get_event_staffing_status":
                assignments = (
                    db.query(StaffAssignment)
                    .filter(StaffAssignment.event_id == tool_input["event_id"])
                    .all()
                )
                result = []
                for a in assignments:
                    staff = db.query(Staff).get(a.staff_id)
                    result.append({
                        "assignment_id": a.id,
                        "staff_name": staff.name if staff else "Unknown",
                        "role": a.role,
                        "confirmed": a.confirmed,
                    })
                needed = dict(MINIMUM_STAFF)
                for a in result:
                    if a["role"] in needed:
                        needed[a["role"]] = max(0, needed[a["role"]] - 1)
                return {"assignments": result, "still_needed": needed}

        finally:
            db.close()

        raise ValueError(f"Unknown tool: {tool_name}")

    def staff_upcoming_events(self) -> str:
        return self.run(
            "Review all upcoming events. For any event missing required staff, "
            "first check the existing staff roster and send availability requests. "
            "If roster is empty or no one is available, send job postings to "
            "local bartending networks. Report status for each event."
        )

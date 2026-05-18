"""
Vendor Agent — sources, compares, and books vendors (bounce house, bar supplies,
equipment rental) for each Saturday event.

Key vendors needed per event:
  1. Bounce house rental company (Greater Boston area)
  2. Bar supplies / beverage distributor (handles delivery to venue)
  3. Event supplies (cups, ice, napkins)

Bounce-house vendors must:
  - Carry $1M liability insurance
  - Have NAARSO or ASTM F24 certified equipment
  - Provide a trained operator or allow our operator
  - Deliver and set up at Town Hall
"""

import logging
from agents.base_agent import BaseAgent
from database import SessionLocal, Vendor, VendorBooking, Event
from tools import email_tools, notification_tools
import config

logger = logging.getLogger(__name__)

# Seed vendors for the Greater Boston / Needham area (to be updated from real quotes)
SEED_VENDORS = [
    {
        "name": "Big Bounce Rentals",
        "category": "bounce_house",
        "contact_name": "Sales",
        "email": "sales@bigbouncerentals.com",
        "phone": "(617) 555-0101",
        "website": "https://bigbouncerentals.com",
        "base_rate": 350.0,
        "notes": "Serves Greater Boston. ASTM certified. $1M liability. Includes operator.",
    },
    {
        "name": "Jump Around Party Rentals",
        "category": "bounce_house",
        "contact_name": "Booking",
        "email": "book@jumparoundma.com",
        "phone": "(781) 555-0202",
        "base_rate": 325.0,
        "notes": "Needham-based. Weekend availability.",
    },
]

TOOL_DEFINITIONS = [
    {
        "name": "list_vendors",
        "description": "List vendors in the database, optionally filtered by category.",
        "input_schema": {
            "type": "object",
            "properties": {"category": {"type": "string"}},
        },
    },
    {
        "name": "add_vendor",
        "description": "Add a vendor to the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "category": {"type": "string"},
                "contact_name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "website": {"type": "string"},
                "base_rate": {"type": "number"},
                "notes": {"type": "string"},
            },
            "required": ["name", "category"],
        },
    },
    {
        "name": "request_quote",
        "description": "Email a vendor to request a quote for an event date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "vendor_id": {"type": "integer"},
                "event_date": {"type": "string"},
                "service_description": {"type": "string"},
            },
            "required": ["vendor_id", "event_date"],
        },
    },
    {
        "name": "book_vendor",
        "description": "Send a booking confirmation email to a vendor and record the booking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "vendor_id": {"type": "integer"},
                "event_id": {"type": "integer"},
                "quoted_price": {"type": "number"},
                "service_description": {"type": "string"},
            },
            "required": ["vendor_id", "event_id", "quoted_price"],
        },
    },
    {
        "name": "get_event_vendor_status",
        "description": "Get vendor booking status for an event.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "seed_vendor_database",
        "description": "Seed the vendor database with known Greater Boston vendors.",
        "input_schema": {"type": "object", "properties": {}},
    },
]


class VendorAgent(BaseAgent):
    name = "Vendor Agent"
    tools = TOOL_DEFINITIONS
    system_prompt = (
        "You manage vendor relationships for Needham Community Events.\n\n"
        "For each Saturday event you must book:\n"
        "  1. A bounce house vendor (with operator, $1M liability, ASTM certified)\n"
        "  2. Confirm bar supply delivery (coordinate with staffing agent's bartender)\n\n"
        "Process:\n"
        "1. Check upcoming events for missing vendor bookings.\n"
        "2. For missing bounce house: request quotes from known vendors, pick lowest price.\n"
        "3. For costs >$500, notify owner before booking.\n"
        "4. Send booking confirmation emails once approved.\n"
        "5. Confirm vendors 1 week before each event.\n\n"
        "Always verify vendors carry their own liability insurance for bounce houses."
    )

    def _dispatch_tool(self, tool_name: str, tool_input: dict):
        db = SessionLocal()
        try:
            if tool_name == "list_vendors":
                query = db.query(Vendor)
                if tool_input.get("category"):
                    query = query.filter(Vendor.category == tool_input["category"])
                vendors = query.all()
                return [
                    {
                        "id": v.id,
                        "name": v.name,
                        "category": v.category,
                        "email": v.email,
                        "phone": v.phone,
                        "base_rate": v.base_rate,
                        "is_preferred": v.is_preferred,
                        "notes": v.notes,
                    }
                    for v in vendors
                ]

            if tool_name == "add_vendor":
                vendor = Vendor(**tool_input)
                db.add(vendor)
                db.commit()
                db.refresh(vendor)
                return {"vendor_id": vendor.id}

            if tool_name == "request_quote":
                vendor = db.query(Vendor).get(tool_input["vendor_id"])
                if not vendor or not vendor.email:
                    return {"error": "Vendor not found or no email"}

                body = (
                    f"Hi {vendor.contact_name or 'there'},\n\n"
                    f"I'm reaching out from {config.COMPANY_NAME} in Needham, MA. "
                    f"We run weekly Saturday community events at Needham Town Hall and "
                    f"are looking for a reliable bounce house vendor.\n\n"
                    f"We need a quote for:\n"
                    f"  Date: {tool_input['event_date']}, 1:00 PM setup – 8:00 PM teardown\n"
                    f"  Location: Needham Town Hall, 1471 Highland Ave, Needham MA 02492\n"
                    f"  Service: {tool_input.get('service_description', 'Standard bounce house with operator')}\n\n"
                    f"We are looking to book this on a recurring weekly basis, so please include "
                    f"any discount for long-term arrangements.\n\n"
                    f"Requirements:\n"
                    f"  - ASTM F24 or NAARSO certified equipment\n"
                    f"  - $1M general liability insurance (COI required)\n"
                    f"  - On-site operator\n"
                    f"  - Delivery and setup included\n\n"
                    f"Please reply with your availability and pricing.\n\n"
                    f"Thank you,\n{config.OWNER_NAME}\n{config.COMPANY_NAME}\n"
                    f"{config.BUSINESS_EMAIL}\n{config.BUSINESS_PHONE}"
                )
                result = email_tools.send_email(
                    to=vendor.email,
                    subject=f"Quote Request — Bounce House — {tool_input['event_date']}",
                    body=body,
                )
                return {"sent_to": vendor.email, "message_id": result.get("id")}

            if tool_name == "book_vendor":
                vendor = db.query(Vendor).get(tool_input["vendor_id"])
                if not vendor:
                    return {"error": "Vendor not found"}

                if notification_tools.requires_owner_approval(
                    f"Book {vendor.name}", tool_input["quoted_price"]
                ):
                    notification_tools.notify_owner(
                        subject=f"Approval needed: Book {vendor.name} for ${tool_input['quoted_price']}",
                        body=(
                            f"The Vendor Agent wants to book {vendor.name} "
                            f"for ${tool_input['quoted_price']} "
                            f"for event #{tool_input['event_id']}.\n"
                            f"Service: {tool_input.get('service_description', 'bounce house')}\n"
                            f"Reply to approve or decline."
                        ),
                        sms=True,
                    )
                    return {"status": "pending_owner_approval"}

                booking = VendorBooking(
                    event_id=tool_input["event_id"],
                    vendor_id=tool_input["vendor_id"],
                    service_description=tool_input.get("service_description"),
                    quoted_price=tool_input["quoted_price"],
                )
                db.add(booking)
                db.commit()

                body = (
                    f"Hi {vendor.contact_name or 'there'},\n\n"
                    f"We'd like to confirm your services for our upcoming event.\n\n"
                    f"Date: {tool_input.get('event_date', 'Saturday')}\n"
                    f"Location: Needham Town Hall, 1471 Highland Ave, Needham MA\n"
                    f"Service: {tool_input.get('service_description', 'Bounce house rental with operator')}\n"
                    f"Agreed price: ${tool_input['quoted_price']}\n\n"
                    f"Please send your COI (certificate of insurance) with the Town of Needham "
                    f"named as additional insured.\n\n"
                    f"Thank you!\n{config.OWNER_NAME}\n{config.COMPANY_NAME}"
                )
                email_tools.send_email(
                    to=vendor.email,
                    subject=f"Booking Confirmation — {config.COMPANY_NAME}",
                    body=body,
                )
                return {"booking_id": booking.id, "status": "booked"}

            if tool_name == "get_event_vendor_status":
                bookings = (
                    db.query(VendorBooking)
                    .filter(VendorBooking.event_id == tool_input["event_id"])
                    .all()
                )
                return [
                    {
                        "booking_id": b.id,
                        "vendor_name": db.query(Vendor).get(b.vendor_id).name if b.vendor_id else "?",
                        "category": db.query(Vendor).get(b.vendor_id).category if b.vendor_id else "?",
                        "price": b.quoted_price,
                        "confirmed": b.confirmed,
                    }
                    for b in bookings
                ]

            if tool_name == "seed_vendor_database":
                added = 0
                for v_data in SEED_VENDORS:
                    existing = db.query(Vendor).filter(Vendor.name == v_data["name"]).first()
                    if not existing:
                        db.add(Vendor(**v_data))
                        added += 1
                db.commit()
                return {"vendors_added": added}

        finally:
            db.close()

        raise ValueError(f"Unknown tool: {tool_name}")

    def book_vendors_for_upcoming_events(self) -> str:
        return self.run(
            "Check all upcoming events. For any event missing a bounce house booking, "
            "request quotes from known vendors and proceed to book the best option. "
            "Report what was done."
        )

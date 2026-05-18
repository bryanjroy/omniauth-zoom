"""
Marketing Agent — promotes each Saturday event via email newsletters,
social-media copy, and community postings.

Channels:
  - Email newsletter to subscriber list
  - Nextdoor / local Facebook group copy (owner posts manually)
  - Eventbrite listing (owner posts manually; agent drafts)
"""

import logging
from datetime import datetime
from agents.base_agent import BaseAgent
from database import SessionLocal, Event
from tools import email_tools
import config

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "get_upcoming_events",
        "description": "Get events that need marketing content created.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_newsletter",
        "description": "Send an event promotion newsletter to the subscriber list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_date": {"type": "string"},
                "event_highlights": {"type": "string"},
                "subscriber_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["event_date", "subscriber_emails"],
        },
    },
    {
        "name": "draft_social_post",
        "description": "Draft social media post copy for Nextdoor, Facebook, and Instagram.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_date": {"type": "string"},
                "platform": {"type": "string"},
                "event_highlights": {"type": "string"},
            },
            "required": ["event_date", "platform"],
        },
    },
    {
        "name": "draft_eventbrite_listing",
        "description": "Draft an Eventbrite event listing for the owner to post.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_date": {"type": "string"},
                "ticket_price": {"type": "number"},
                "capacity": {"type": "integer"},
            },
            "required": ["event_date"],
        },
    },
    {
        "name": "email_owner_marketing_drafts",
        "description": "Email all drafted marketing content to the owner for review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_date": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["event_date", "content"],
        },
    },
]


class MarketingAgent(BaseAgent):
    name = "Marketing Agent"
    tools = TOOL_DEFINITIONS
    system_prompt = (
        "You create marketing content for Needham Community Events Saturday events.\n\n"
        "For each upcoming event (4+ weeks out) you must:\n"
        "1. Draft a warm, friendly email newsletter (subject + body).\n"
        "2. Draft 3 social posts: one for Nextdoor, one for Facebook, one for Instagram.\n"
        "3. Draft an Eventbrite event listing.\n"
        "4. Email all drafts to the owner for review/posting.\n\n"
        "Tone: friendly, community-focused, excited. Highlight:\n"
        "  - Fun for all ages (bounce house!)\n"
        "  - Local community gathering\n"
        "  - Cash bar for adults\n"
        "  - Needham Town Hall location\n"
        "  - Date and time (2 PM – 8 PM)\n\n"
        "Keep social posts concise. Newsletter can be longer (150-200 words).\n"
        "Always include: date, time, location, and a call to action."
    )

    def _dispatch_tool(self, tool_name: str, tool_input: dict):
        db = SessionLocal()
        try:
            if tool_name == "get_upcoming_events":
                events = (
                    db.query(Event)
                    .filter(Event.date >= datetime.utcnow())
                    .filter(Event.status == "planned")
                    .order_by(Event.date)
                    .all()
                )
                return [{"id": e.id, "date": e.date.isoformat()} for e in events]

            if tool_name == "send_newsletter":
                event_date = tool_input["event_date"]
                highlights = tool_input.get("event_highlights", "bounce house, cash bar, community fun")
                subject = f"This Saturday in Needham — Community Event at Town Hall!"
                body = (
                    f"Hi neighbor!\n\n"
                    f"Join us this Saturday at Needham Town Hall for our weekly community gathering.\n\n"
                    f"📅 {event_date} | 2:00 PM – 8:00 PM\n"
                    f"📍 Needham Town Hall, 1471 Highland Ave, Needham MA\n\n"
                    f"What's happening:\n"
                    f"  🏀 Bounce house for the kids\n"
                    f"  🍺 Cash bar for adults (21+)\n"
                    f"  😊 Great community vibes\n"
                    f"  {highlights}\n\n"
                    f"This is a family-friendly event — bring the whole crew!\n\n"
                    f"See you there,\n"
                    f"The Needham Community Events Team\n"
                    f"needhamevents.com | {config.BUSINESS_EMAIL}"
                )
                results = []
                for email in tool_input["subscriber_emails"]:
                    result = email_tools.send_email(to=email, subject=subject, body=body)
                    results.append(result.get("id"))
                return {"sent_count": len(results), "message_ids": results}

            if tool_name == "draft_social_post":
                event_date = tool_input["event_date"]
                platform = tool_input["platform"]
                highlights = tool_input.get("event_highlights", "")

                if platform == "nextdoor":
                    post = (
                        f"Hey Needham neighbors! 👋\n\n"
                        f"We're hosting our weekly community event THIS SATURDAY at Town Hall!\n\n"
                        f"📅 {event_date} | 2–8 PM\n"
                        f"📍 Needham Town Hall, 1471 Highland Ave\n"
                        f"🎉 Bounce house + cash bar + community fun\n\n"
                        f"All ages welcome. Come say hi!\n\n"
                        f"— Needham Community Events"
                    )
                elif platform == "facebook":
                    post = (
                        f"🎉 SATURDAY EVENT AT NEEDHAM TOWN HALL 🎉\n\n"
                        f"Join us for our weekly community gathering!\n\n"
                        f"📅 {event_date}\n"
                        f"⏰ 2:00 PM – 8:00 PM\n"
                        f"📍 Needham Town Hall, 1471 Highland Ave\n\n"
                        f"✅ Bounce house for kids\n"
                        f"✅ Cash bar for adults (21+)\n"
                        f"✅ Family-friendly fun\n\n"
                        f"Tag a friend who needs to get out of the house! 👇\n\n"
                        f"#Needham #NeedhamMA #CommunityEvents #WeekendFun"
                    )
                elif platform == "instagram":
                    post = (
                        f"Your Saturday plans just got better. 🎉\n\n"
                        f"Community event at Needham Town Hall this Saturday!\n"
                        f"Bounce house 🏀 | Cash bar 🍺 | Good vibes only ✨\n\n"
                        f"{event_date} | 2–8 PM\n"
                        f"1471 Highland Ave, Needham MA\n\n"
                        f"#Needham #NeedhamMA #CommunityEvent #LocalEvent #WeekendVibes #BounceHouse"
                    )
                else:
                    post = f"Saturday event at Needham Town Hall — {event_date}, 2-8 PM!"

                return {"platform": platform, "post": post}

            if tool_name == "draft_eventbrite_listing":
                event_date = tool_input["event_date"]
                ticket_price = tool_input.get("ticket_price", 0)
                capacity = tool_input.get("capacity", config.EVENT_CAPACITY)
                price_str = "Free" if ticket_price == 0 else f"${ticket_price}"

                listing = {
                    "title": f"Needham Saturday Community Event — {event_date}",
                    "date": event_date,
                    "time": "2:00 PM – 8:00 PM EDT",
                    "location": "Needham Town Hall, 1471 Highland Ave, Needham, MA 02492",
                    "category": "Community / Family",
                    "price": price_str,
                    "capacity": capacity,
                    "description": (
                        f"Join Needham Community Events for our weekly Saturday gathering "
                        f"at Needham Town Hall!\n\n"
                        f"Every Saturday from 2 PM to 8 PM, we bring together Needham residents "
                        f"for a fun, family-friendly community event.\n\n"
                        f"What to expect:\n"
                        f"• Bounce house for kids (supervised)\n"
                        f"• Cash bar for adults (21+ with ID)\n"
                        f"• Friendly community atmosphere\n"
                        f"• Plenty of space to mingle\n\n"
                        f"Free entry — just bring yourself and your community spirit!\n\n"
                        f"Questions? Email {config.BUSINESS_EMAIL}"
                    ),
                }
                return listing

            if tool_name == "email_owner_marketing_drafts":
                body = (
                    f"Marketing drafts are ready for your {tool_input['event_date']} event.\n\n"
                    f"Please review and post the following content:\n\n"
                    f"{tool_input['content']}\n\n"
                    f"— Your Marketing Agent"
                )
                email_tools.send_email(
                    to=config.OWNER_EMAIL,
                    subject=f"Marketing Drafts Ready — {tool_input['event_date']}",
                    body=body,
                )
                return {"status": "sent_to_owner"}

        finally:
            db.close()

        raise ValueError(f"Unknown tool: {tool_name}")

    def create_marketing_for_upcoming_events(self) -> str:
        return self.run(
            "Generate marketing content for all upcoming events. "
            "Create newsletter, social posts (Nextdoor, Facebook, Instagram), "
            "and Eventbrite listing for each. Email all drafts to the owner."
        )

"""
Email Agent — reads the business inbox, classifies inbound mail,
and autonomously drafts / sends replies for routine requests.
High-stakes replies (contracts, legal) are routed to the owner.
"""

import logging
from agents.base_agent import BaseAgent
from tools import email_tools, notification_tools
import config

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "list_unread_emails",
        "description": "List unread emails in the business inbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_email_thread",
        "description": "Fetch the full thread for a given thread_id.",
        "input_schema": {
            "type": "object",
            "properties": {"thread_id": {"type": "string"}},
            "required": ["thread_id"],
        },
    },
    {
        "name": "send_email",
        "description": "Send an email from the business address.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "reply_to_thread_id": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "mark_as_read",
        "description": "Mark a Gmail message as read after handling it.",
        "input_schema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}},
            "required": ["message_id"],
        },
    },
    {
        "name": "escalate_to_owner",
        "description": (
            "Forward an email to the business owner when it requires human judgement — "
            "legal questions, complaints, contract negotiations, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "summary": {"type": "string"},
                "original_from": {"type": "string"},
                "thread_id": {"type": "string"},
            },
            "required": ["subject", "summary"],
        },
    },
]


class EmailAgent(BaseAgent):
    name = "Email Agent"
    tools = TOOL_DEFINITIONS
    system_prompt = (
        "You manage the business email inbox for Needham Community Events. "
        "Your jobs:\n"
        "1. Read all unread emails.\n"
        "2. For each email decide: can I handle this autonomously, or must I escalate?\n"
        "   - Autonomously handle: general event inquiries, attendance questions, vendor quotes, "
        "     staff availability checks, permit status follow-ups, sponsor inquiries.\n"
        "   - Escalate to owner: legal notices, complaints, anything requiring a payment >$500, "
        "     media requests, or anything ambiguous.\n"
        "3. Draft replies in a warm, professional tone representing Needham Community Events.\n"
        "4. Always sign off as: 'The Needham Community Events Team'.\n"
        "5. After handling each email, mark it as read.\n"
        "Be thorough — process every unread message."
    )

    def _dispatch_tool(self, tool_name: str, tool_input: dict):
        if tool_name == "list_unread_emails":
            return email_tools.list_unread_emails(tool_input.get("max_results", 20))
        if tool_name == "get_email_thread":
            return email_tools.get_email_thread(tool_input["thread_id"])
        if tool_name == "send_email":
            result = email_tools.send_email(
                to=tool_input["to"],
                subject=tool_input["subject"],
                body=tool_input["body"],
                reply_to_thread_id=tool_input.get("reply_to_thread_id"),
            )
            logger.info("Email sent to %s: %s", tool_input["to"], tool_input["subject"])
            return result
        if tool_name == "mark_as_read":
            email_tools.mark_as_read(tool_input["message_id"])
            return {"status": "marked_read"}
        if tool_name == "escalate_to_owner":
            body = (
                f"An email needs your attention.\n\n"
                f"From: {tool_input.get('original_from', 'unknown')}\n"
                f"Summary: {tool_input['summary']}\n\n"
                f"Thread ID: {tool_input.get('thread_id', 'N/A')}\n"
                f"Please reply directly in Gmail."
            )
            notification_tools.notify_owner(
                subject=tool_input["subject"],
                body=body,
                sms=True,
            )
            return {"status": "escalated"}
        raise ValueError(f"Unknown tool: {tool_name}")

    def process_inbox(self) -> str:
        return self.run(
            "Check the inbox now. Process every unread email: reply autonomously where you can, "
            "and escalate anything that needs the owner. Report a summary of what you did."
        )

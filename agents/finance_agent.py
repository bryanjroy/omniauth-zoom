"""
Finance Agent — tracks expenses per event, monitors budget vs. actuals,
and sends weekly financial summaries to the owner.
"""

import logging
from datetime import datetime
from agents.base_agent import BaseAgent
from database import SessionLocal, Expense, Event
from tools import email_tools
import config

logger = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "log_expense",
        "description": "Record an expense in the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer"},
                "category": {"type": "string"},
                "description": {"type": "string"},
                "amount": {"type": "number"},
            },
            "required": ["category", "description", "amount"],
        },
    },
    {
        "name": "get_event_budget_summary",
        "description": "Get a budget vs. actual summary for an event.",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "integer"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "get_all_expenses",
        "description": "Get all expenses for a date range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
            },
        },
    },
    {
        "name": "send_financial_summary",
        "description": "Email a financial summary to the owner.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["period", "summary"],
        },
    },
]


class FinanceAgent(BaseAgent):
    name = "Finance Agent"
    tools = TOOL_DEFINITIONS
    system_prompt = (
        "You manage the finances for Needham Community Events.\n\n"
        "Default budget per event:\n"
        + "\n".join(f"  - {k}: ${v}" for k, v in config.DEFAULT_BUDGET.items())
        + f"\n  Total: ${sum(config.DEFAULT_BUDGET.values())}\n\n"
        "Your weekly tasks:\n"
        "1. Check if any new expenses have been logged.\n"
        "2. Compare actuals to budget for each event.\n"
        "3. Flag any category overruns to the owner.\n"
        "4. Send a weekly P&L summary email every Sunday.\n\n"
        "Always present amounts as dollar figures with 2 decimal places."
    )

    def _dispatch_tool(self, tool_name: str, tool_input: dict):
        db = SessionLocal()
        try:
            if tool_name == "log_expense":
                expense = Expense(
                    event_id=tool_input.get("event_id"),
                    category=tool_input["category"],
                    description=tool_input["description"],
                    amount=tool_input["amount"],
                    paid_date=datetime.utcnow(),
                )
                db.add(expense)
                db.commit()
                return {"expense_id": expense.id}

            if tool_name == "get_event_budget_summary":
                event = db.query(Event).get(tool_input["event_id"])
                if not event:
                    return {"error": "Event not found"}

                expenses = (
                    db.query(Expense)
                    .filter(Expense.event_id == tool_input["event_id"])
                    .all()
                )
                actuals: dict[str, float] = {}
                for e in expenses:
                    actuals[e.category] = actuals.get(e.category, 0) + e.amount

                total_budget = sum(config.DEFAULT_BUDGET.values())
                total_actual = sum(actuals.values())
                breakdown = []
                for cat, budgeted in config.DEFAULT_BUDGET.items():
                    actual = actuals.get(cat, 0)
                    breakdown.append({
                        "category": cat,
                        "budgeted": budgeted,
                        "actual": actual,
                        "variance": actual - budgeted,
                    })

                return {
                    "event_date": event.date.isoformat(),
                    "total_budget": total_budget,
                    "total_actual": total_actual,
                    "variance": total_actual - total_budget,
                    "breakdown": breakdown,
                }

            if tool_name == "get_all_expenses":
                query = db.query(Expense)
                if tool_input.get("start_date"):
                    query = query.filter(Expense.paid_date >= tool_input["start_date"])
                if tool_input.get("end_date"):
                    query = query.filter(Expense.paid_date <= tool_input["end_date"])
                expenses = query.all()
                return [
                    {
                        "id": e.id,
                        "event_id": e.event_id,
                        "category": e.category,
                        "description": e.description,
                        "amount": e.amount,
                        "date": e.paid_date.isoformat() if e.paid_date else None,
                    }
                    for e in expenses
                ]

            if tool_name == "send_financial_summary":
                email_tools.send_email(
                    to=config.OWNER_EMAIL,
                    subject=f"Financial Summary — {tool_input['period']}",
                    body=tool_input["summary"],
                )
                return {"status": "sent"}

        finally:
            db.close()

        raise ValueError(f"Unknown tool: {tool_name}")

    def weekly_financial_report(self) -> str:
        return self.run(
            "Generate the weekly financial report. "
            "Show budget vs. actuals for all recent events. "
            "Flag any overruns. Email the summary to the owner."
        )

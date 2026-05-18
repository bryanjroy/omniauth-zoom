"""
Orchestrator — the top-level coordinator for Needham Community Events.

Runs on a schedule and delegates work to specialized sub-agents:
  - SchedulingAgent   : maintain 8-week event calendar
  - PermitAgent       : file and track all permits
  - StaffingAgent     : source and schedule staff
  - WeatherAgent      : monitor forecast, coordinate cancellations
  - MarketingAgent    : produce promotional content
  - FinanceAgent      : track budget and send reports
  - EmailAgent        : monitor and respond to inbox

Schedule (all times ET):
  Monday    08:00  — Weekly planning: scheduling + permits + staffing
  Wednesday 08:00  — Weather check + marketing content generation
  Thursday  08:00  — Email inbox sweep
  Friday    08:00  — Final pre-event checklist + weather re-check + staff reminders
  Saturday  07:00  — Day-of checklist (owner SMS)
  Sunday    18:00  — Financial report
  Every 4h          — Email inbox sweep
"""

import logging
import sys
from datetime import datetime

from agents.email_agent import EmailAgent
from agents.permit_agent import PermitAgent
from agents.staffing_agent import StaffingAgent
from agents.weather_agent import WeatherAgent
from agents.marketing_agent import MarketingAgent
from agents.finance_agent import FinanceAgent
from agents.scheduling_agent import SchedulingAgent
from database import init_db
from tools import notification_tools
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(config.BASE_DIR / "logs" / "orchestrator.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("orchestrator")


class Orchestrator:
    def __init__(self):
        self.scheduling = SchedulingAgent()
        self.permits = PermitAgent()
        self.staffing = StaffingAgent()
        self.weather = WeatherAgent()
        self.marketing = MarketingAgent()
        self.finance = FinanceAgent()
        self.email = EmailAgent()

    # ── Scheduled tasks ──────────────────────────────────────────────────────

    def weekly_planning(self):
        """Monday 08:00 — Full weekly planning cycle."""
        logger.info("=== Weekly Planning Cycle ===")
        self._run("Scheduling", self.scheduling.schedule_upcoming_events)
        self._run("Permits", self.permits.check_and_file_permits)
        self._run("Staffing", self.staffing.staff_upcoming_events)
        logger.info("=== Weekly Planning Complete ===")

    def midweek_run(self):
        """Wednesday 08:00 — Weather check + marketing."""
        logger.info("=== Midweek Run ===")
        # Weather first — if HIGH risk, owner needs time to decide before Friday
        self._run("Weather", self.weather.check_upcoming_weather)
        self._run("Marketing", self.marketing.create_marketing_for_upcoming_events)

    def email_sweep(self):
        """Run every 4 hours — Process inbox. Also handles owner CANCEL/GO replies."""
        logger.info("=== Email Sweep ===")
        result = self._run("Email", self.email.process_inbox)
        # The Email Agent will surface any CANCEL replies to the weather agent
        # via escalate_to_owner — owner's reply lands back in the inbox,
        # and the Email Agent routes it here.
        self._check_for_cancellation_instruction(result)

    def pre_event_checklist(self):
        """Friday 08:00 — Final check + weather re-check + staff reminders."""
        logger.info("=== Pre-Event Checklist ===")

        # Re-run weather — Friday forecast is more accurate than Wednesday's
        self._run("Weather/Friday", self.weather.check_upcoming_weather)

        checklist_prompt = (
            "Run the pre-event checklist for this Saturday's event:\n"
            "1. Confirm venue reservation is approved.\n"
            "2. Confirm all permits are in hand (venue, special event, alcohol license, COI).\n"
            "3. Confirm all staff are confirmed for Saturday.\n"
            "4. Send reminder emails to all confirmed staff with full event details "
            "   (time, location, parking, contact number).\n"
            "Report any gaps and notify the owner of anything outstanding."
        )
        result = self.staffing.run(checklist_prompt)
        logger.info("Pre-event checklist: %s", result)
        return result

    def day_of_checklist(self):
        """Saturday 07:00 — SMS the owner with day-of status."""
        logger.info("=== Day-of Checklist ===")
        status_msg = (
            "Good morning! Today is event day.\n\n"
            "Quick reminder:\n"
            "  • Venue: Needham Town Hall (arrive 1 PM to set up)\n"
            "  • Bartender arrives: 1:30 PM\n"
            "  • Doors open: 2:00 PM\n"
            "  • Cash bar closes: 7:30 PM\n"
            "  • Event ends: 8:00 PM\n\n"
            "Have a great event! — Your Event System"
        )
        notification_tools.notify_owner(
            subject="Today's Event — Day-of Checklist",
            body=status_msg,
            sms=True,
        )

    def weekly_financial_report(self):
        """Sunday 18:00 — Send financial summary."""
        logger.info("=== Financial Report ===")
        self._run("Finance", self.finance.weekly_financial_report)

    # ── Cancellation coordination ─────────────────────────────────────────────

    def trigger_cancellation(self, event_id: int, event_date: str):
        """Called when owner confirms a weather cancellation via email reply."""
        logger.info("Cancellation confirmed by owner for event %s (%s)", event_id, event_date)
        self._run(
            "Weather/Cancellation",
            lambda: self.weather.process_owner_cancellation(event_id, event_date),
        )

    def _check_for_cancellation_instruction(self, email_result: str):
        """
        Lightweight hook — the Email Agent surfaces 'CANCEL confirmed for event X'
        in its report when it detects a CANCEL reply from the owner. We parse
        that signal here and trigger the full cancellation workflow.
        """
        if not email_result:
            return
        if "CANCEL confirmed for event" in email_result:
            # Extract event_id and date from the Email Agent's summary
            # Format expected: "CANCEL confirmed for event 3 (2025-06-07)"
            import re
            match = re.search(r"CANCEL confirmed for event (\d+) \(([^)]+)\)", email_result)
            if match:
                event_id = int(match.group(1))
                event_date = match.group(2)
                self.trigger_cancellation(event_id, event_date)

    # ── One-time setup ────────────────────────────────────────────────────────

    def initial_setup(self):
        """Run once to bootstrap the system."""
        logger.info("=== Initial Setup ===")
        init_db()
        logger.info("Database initialized.")

        self._run("Scheduling/setup", self.scheduling.schedule_upcoming_events)
        self._run("Permits/setup", self.permits.check_and_file_permits)

        logger.info("=== Initial Setup Complete ===")
        notification_tools.notify_owner(
            subject="Event System Online",
            body=(
                "Your Needham Community Events autonomous agent system is now running.\n\n"
                "Actions taken:\n"
                "  ✓ Database initialized\n"
                "  ✓ Next 8 Saturday events scheduled\n"
                "  ✓ Permit applications drafted/queued\n\n"
                "What to do next:\n"
                "  1. Set up Gmail OAuth (run: python setup_auth.py)\n"
                "  2. Review and send permit applications in your drafts\n"
                "  3. Add your first bartender via the admin CLI\n"
                "  4. Review marketing drafts sent to your email\n\n"
                "System will run automatically from here on.\n\n"
                "Weather monitoring is active — you'll receive alerts Wednesday and Friday\n"
                "if severe weather threatens any Saturday event. Reply CANCEL or GO."
            ),
            sms=True,
        )

    def _run(self, label: str, fn):
        try:
            result = fn()
            logger.info("[%s] %s", label, result)
            return result
        except Exception as exc:
            logger.error("[%s] FAILED: %s", label, exc, exc_info=True)
            notification_tools.notify_owner(
                subject=f"Agent Error: {label}",
                body=f"The {label} agent encountered an error:\n\n{exc}",
                sms=False,
            )

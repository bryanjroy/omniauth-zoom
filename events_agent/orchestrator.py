"""
Orchestrator — the top-level coordinator for Needham Community Events.

Runs on a schedule and delegates work to specialized sub-agents:
  - SchedulingAgent   : maintain 8-week event calendar
  - PermitAgent       : file and track all permits
  - StaffingAgent     : source and schedule staff
  - VendorAgent       : book bounce house and vendors
  - MarketingAgent    : produce promotional content
  - FinanceAgent      : track budget and send reports
  - EmailAgent        : monitor and respond to inbox

Schedule (all times ET):
  Monday    08:00  — Weekly planning: scheduling + permits + staffing
  Tuesday   08:00  — Vendor checks
  Wednesday 08:00  — Marketing content generation
  Thursday  08:00  — Email inbox sweep
  Friday    08:00  — Final pre-event checklist + staff reminders
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
from agents.vendor_agent import VendorAgent
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
        self.vendors = VendorAgent()
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

    def vendor_check(self):
        """Tuesday 08:00 — Vendor booking."""
        logger.info("=== Vendor Check ===")
        self._run("Vendors", self.vendors.book_vendors_for_upcoming_events)

    def marketing_run(self):
        """Wednesday 08:00 — Generate marketing content."""
        logger.info("=== Marketing Run ===")
        self._run("Marketing", self.marketing.create_marketing_for_upcoming_events)

    def email_sweep(self):
        """Run every 4 hours — Process inbox."""
        logger.info("=== Email Sweep ===")
        self._run("Email", self.email.process_inbox)

    def pre_event_checklist(self):
        """Friday 08:00 — Verify everything is in place for Saturday."""
        logger.info("=== Pre-Event Checklist ===")
        checklist_prompt = (
            "Run the pre-event checklist for this Saturday's event:\n"
            "1. Confirm venue reservation is approved.\n"
            "2. Confirm all permits are in hand.\n"
            "3. Confirm all staff are confirmed for Saturday.\n"
            "4. Confirm bounce house vendor is booked and confirmed.\n"
            "5. Send reminder emails to all staff with event details.\n"
            "Report any gaps immediately and notify the owner."
        )
        # Reuse staffing agent for reminder logic
        result = self.staffing.run(checklist_prompt)
        logger.info("Pre-event checklist result: %s", result)
        return result

    def day_of_checklist(self):
        """Saturday 07:00 — SMS the owner with day-of status."""
        logger.info("=== Day-of Checklist ===")
        status_msg = (
            f"Good morning! Today is event day.\n\n"
            f"Quick reminder:\n"
            f"  • Venue: Needham Town Hall (arrive 1 PM to set up)\n"
            f"  • Bounce house vendor arrives: 12:30 PM\n"
            f"  • Bartender arrives: 1:30 PM\n"
            f"  • Doors open: 2:00 PM\n"
            f"  • Cash bar closes: 7:30 PM\n"
            f"  • Event ends: 8:00 PM\n\n"
            f"Have a great event! — Your Event System"
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

    # ── One-time setup ────────────────────────────────────────────────────────

    def initial_setup(self):
        """Run once to bootstrap the system."""
        logger.info("=== Initial Setup ===")
        init_db()
        logger.info("Database initialized.")

        # Seed vendors
        self._run("Vendors/seed", lambda: self.vendors.run(
            "Seed the vendor database with known Greater Boston bounce house vendors."
        ))

        # Create first 8 weeks of events
        self._run("Scheduling/setup", self.scheduling.schedule_upcoming_events)

        # Queue up permits for all events
        self._run("Permits/setup", self.permits.check_and_file_permits)

        logger.info("=== Initial Setup Complete ===")
        notification_tools.notify_owner(
            subject="Event System Online",
            body=(
                f"Your Needham Community Events autonomous agent system is now running.\n\n"
                f"Actions taken:\n"
                f"  ✓ Database initialized\n"
                f"  ✓ Vendor database seeded\n"
                f"  ✓ Next 8 Saturday events scheduled\n"
                f"  ✓ Permit applications drafted/queued\n\n"
                f"What to do next:\n"
                f"  1. Set up Gmail OAuth (run: python setup_auth.py)\n"
                f"  2. Review and send permit applications in your drafts\n"
                f"  3. Add your first bartender via the admin CLI\n"
                f"  4. Review marketing drafts sent to your email\n\n"
                f"System will run automatically from here on."
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

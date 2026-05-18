"""
Entry point — starts the APScheduler daemon that drives all agents.

Usage:
  python main.py setup    # one-time initial setup
  python main.py run      # start the scheduler daemon
  python main.py email    # manual email sweep
  python main.py permits  # manual permit check
"""

import sys
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from orchestrator import Orchestrator
from database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    orch = Orchestrator()

    if command == "setup":
        init_db()
        orch.initial_setup()
        return

    if command == "email":
        print(orch.email.process_inbox())
        return

    if command == "permits":
        print(orch.permits.check_and_file_permits())
        return

    if command == "staffing":
        print(orch.staffing.staff_upcoming_events())
        return

    if command == "weather":
        print(orch.weather.check_upcoming_weather())
        return

    if command == "marketing":
        print(orch.marketing.create_marketing_for_upcoming_events())
        return

    if command == "finance":
        print(orch.finance.weekly_financial_report())
        return

    if command == "run":
        init_db()
        scheduler = BlockingScheduler(timezone="America/New_York")

        # Monday 8 AM — Weekly planning
        scheduler.add_job(
            orch.weekly_planning,
            CronTrigger(day_of_week="mon", hour=8, minute=0),
            id="weekly_planning",
        )

        # Wednesday 8 AM — Weather check + marketing
        scheduler.add_job(
            orch.midweek_run,
            CronTrigger(day_of_week="wed", hour=8, minute=0),
            id="midweek_run",
        )

        # Thursday 8 AM — Email sweep
        scheduler.add_job(
            orch.email_sweep,
            CronTrigger(day_of_week="thu", hour=8, minute=0),
            id="email_thu",
        )

        # Friday 8 AM — Pre-event checklist
        scheduler.add_job(
            orch.pre_event_checklist,
            CronTrigger(day_of_week="fri", hour=8, minute=0),
            id="pre_event",
        )

        # Saturday 7 AM — Day-of SMS
        scheduler.add_job(
            orch.day_of_checklist,
            CronTrigger(day_of_week="sat", hour=7, minute=0),
            id="day_of",
        )

        # Sunday 6 PM — Financial report
        scheduler.add_job(
            orch.weekly_financial_report,
            CronTrigger(day_of_week="sun", hour=18, minute=0),
            id="finance_report",
        )

        # Every 4 hours — Email sweep
        scheduler.add_job(
            orch.email_sweep,
            CronTrigger(hour="*/4", minute=30),
            id="email_sweep",
        )

        logger.info("Needham Community Events scheduler started. Press Ctrl+C to stop.")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Scheduler stopped.")

    else:
        print(f"Unknown command: {command}")
        print("Usage: python main.py [setup|run|email|permits|staffing|weather|marketing|finance]")
        sys.exit(1)


if __name__ == "__main__":
    main()

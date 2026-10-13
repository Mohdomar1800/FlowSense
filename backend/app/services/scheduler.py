"""Background report generation.

Runs once at startup (to catch up on anything missed while the app was closed) and then hourly,
so each user's reports appear shortly after *their* local midnight. Report inserts are idempotent,
so running several app instances never creates duplicates.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.report import generate_due_reports

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="UTC")


def _run_report_job() -> None:
    try:
        generate_due_reports()
    except Exception:
        logger.exception("report generation failed")


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(_run_report_job, CronTrigger(minute=5), id="due_reports", replace_existing=True)
    # Catch-up run shortly after startup, in the background so it never delays boot.
    scheduler.add_job(_run_report_job, id="startup_reports", replace_existing=True)
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services.report import generate_daily_reports, generate_weekly_reports

scheduler = BackgroundScheduler(timezone="UTC")


def start_scheduler() -> None:
    if scheduler.running:
        return

    scheduler.add_job(
        generate_daily_reports,
        CronTrigger(hour=21, minute=0),
        id="daily_reports",
        replace_existing=True,
    )
    scheduler.add_job(
        generate_weekly_reports,
        CronTrigger(day_of_week="sun", hour=21, minute=0),
        id="weekly_reports",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)

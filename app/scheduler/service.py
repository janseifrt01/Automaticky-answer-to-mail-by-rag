"""APScheduler integration: build live providers and run the cycle.

Uses ``AsyncIOScheduler`` so the interval job shares FastAPI's event loop.
``run_once`` builds the configured providers and runs one cycle; it backs both
the scheduled job and the manual ``/sync/now`` route.
"""

from __future__ import annotations

import functools
import logging

from fastapi import FastAPI

from app.config import get_settings
from app.db.connection import connect
from app.mail.factory import get_mail_provider
from app.providers import get_provider
from app.scheduler.runner import run_cycle

logger = logging.getLogger(__name__)

_JOB_ID = "sync_cycle"


async def run_once(app: FastAPI | None = None) -> dict:
    """Build providers and run one processing cycle; record the summary."""
    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        mail_provider = get_mail_provider(conn, settings)
    finally:
        conn.close()
    llm_provider = get_provider()
    summary = await run_cycle(
        db_path=settings.db_path,
        mail_provider=mail_provider,
        llm_provider=llm_provider,
        settings=settings,
    )
    if app is not None:
        app.state.last_run = summary
    return summary


def start_scheduler(app: FastAPI):
    """Start the interval cycle job (unless disabled). Returns the scheduler."""
    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.info("scheduler disabled by config")
        return None

    # Imported here so apscheduler isn't required unless the scheduler runs.
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        functools.partial(run_once, app),
        trigger="interval",
        minutes=settings.sync_interval_min,
        id=_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("scheduler started (every %s min)", settings.sync_interval_min)
    return scheduler


def stop_scheduler(app: FastAPI) -> None:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        app.state.scheduler = None

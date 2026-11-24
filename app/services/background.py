"""In-process maintenance loop (no extra paid worker service needed).

Runs only when the database is enabled. Every few minutes it releases stock
held by abandoned checkouts and retries any order emails that failed.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi.concurrency import run_in_threadpool

from app.config import get_settings

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 300


def run_maintenance_once() -> dict:
    from app.services.db_checkout import DbCheckoutService
    from app.services.notifications import send_pending_notifications

    released = DbCheckoutService().release_expired_reservations()
    emails = send_pending_notifications()
    return {"released_orders": released, "emails": emails}


async def maintenance_loop() -> None:
    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        try:
            result = await run_in_threadpool(run_maintenance_once)
            if result["released_orders"] or any(result["emails"].values()):
                logger.info("Maintenance: %s", result)
        except Exception:
            logger.exception("Maintenance loop iteration failed")


def start_background_tasks(app) -> None:
    if not get_settings().database_enabled or getattr(app.state, "maintenance_task", None):
        return
    app.state.maintenance_task = asyncio.get_event_loop().create_task(maintenance_loop())

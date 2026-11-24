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

    from app.services.db_checkout import backfill_payment_fees

    from app.services import channel_sync

    channel_sync.seed_channels()
    released = DbCheckoutService().release_expired_reservations()
    imported = channel_sync.poll_marketplace_orders()
    sync = channel_sync.process_sync_events()
    reconciled = channel_sync.reconcile()
    emails = send_pending_notifications()
    fees = backfill_payment_fees() if get_settings().stripe_enabled else 0
    digest = send_daily_digest()
    return {"released_orders": released, "emails": emails, "fees": fees, "digest": digest, "sync": sync,
            "reconciled": reconciled, "imported": imported}


_last_digest: dict[str, str] = {}


def send_daily_digest(force: bool = False) -> bool:
    """Once a day after 08:00 (London): email pending orders and low-stock items to the shop."""
    from datetime import datetime

    from app.services import reporting
    from app.services.alerts import send_alert

    now = datetime.now(reporting.LONDON)
    today = now.date().isoformat()
    if not force and (now.hour < 8 or _last_digest.get("date") == today):
        return False
    _last_digest["date"] = today
    pending = reporting.pending_orders(50)
    low = reporting.low_stock(50)
    if not pending and not low:
        return False
    lines = [f"Orders waiting to be dispatched: {len(pending)}"]
    lines += [f"  - {o.order_number} {o.name} (paid {o.paid_at:%d %b})" for o in pending[:20]]
    lines.append("")
    lines.append(f"Low or sold-out stock: {len(low)}")
    lines += [f"  - {v['name']} {v['size']} [{v['sku']}]: {v['stock']} left" for v in low[:30]]
    return send_alert(f"digest-{today}", f"Daily summary: {len(pending)} to dispatch, {len(low)} low stock", "\n".join(lines))


async def maintenance_loop() -> None:
    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        try:
            result = await run_in_threadpool(run_maintenance_once)
            if result["released_orders"] or any(result["emails"].values()) or any(result["sync"].values()):
                logger.info("Maintenance: %s", result)
        except Exception as exc:
            logger.exception("Maintenance loop iteration failed")
            from app.services.alerts import send_alert

            send_alert("maintenance-failure", "Background maintenance failed",
                       f"The 5-minute maintenance job failed ({type(exc).__name__}). Stock holds may not be released.")


def start_background_tasks(app) -> None:
    if not get_settings().database_enabled or getattr(app.state, "maintenance_task", None):
        return
    app.state.maintenance_task = asyncio.get_event_loop().create_task(maintenance_loop())

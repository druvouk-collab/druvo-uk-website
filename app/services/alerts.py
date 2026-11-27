"""Operational alerts to the shop owner (email) and Sentry, throttled per alert key."""

from __future__ import annotations

import logging
import threading
import time

from app.config import get_settings
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)
_last_sent: dict[str, float] = {}
_lock = threading.Lock()
THROTTLE_SECONDS = 60 * 60


def send_alert(key: str, subject: str, body: str) -> bool:
    """Email the shop about a problem (payment webhook failure, stock conflict, sync failure)."""
    logger.error("ALERT %s: %s", key, subject)
    try:
        import sentry_sdk

        sentry_sdk.capture_message(f"{subject} [{key}]", level="error")
    except Exception:
        pass
    now = time.monotonic()
    with _lock:
        if now - _last_sent.get(key, -THROTTLE_SECONDS * 2) < THROTTLE_SECONDS:
            return False
        _last_sent[key] = now
    cfg = get_settings()
    to = cfg.shop_notification_email or cfg.contact_email
    return EmailService(cfg).send(
        to_email=to,
        subject=f"[DRUVO alert] {subject}",
        body=f"{body}\n\nAdmin: {cfg.public_site_url.rstrip('/')}/admin",
    )


def reset_throttle() -> None:
    with _lock:
        _last_sent.clear()

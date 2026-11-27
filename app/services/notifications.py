"""Customer and shop emails for orders: confirmation, new-order alert, dispatch, refund.

Each email records a sent timestamp on the order/refund, and uses a Resend
idempotency key, so retries never send duplicates. Failures are logged and
retried by ``send_pending_notifications`` (background sweep).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import or_, select

from app.config import Settings, get_settings
from app.db import models
from app.db.base import session_scope
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).resolve().parents[1] / "templates" / "emails")),
    autoescape=select_autoescape(["html"]),
)

ROYAL_MAIL_TRACKING = "https://www.royalmail.com/track-your-item#/tracking-results/{number}"


def money(pence: int) -> str:
    return f"£{pence / 100:,.2f}"


_env.filters["money"] = money


def _context(order: models.Order, settings: Settings, **extra) -> dict:
    base = settings.public_site_url.rstrip("/")
    return {
        "order": order,
        "items": list(order.items),
        "site_name": settings.site_name,
        "site_url": base,
        "contact_email": settings.contact_email,
        "returns_url": f"{base}/returns",
        "delivery_url": f"{base}/delivery",
        "business_legal_name": settings.business_legal_name,
        "business_address": settings.business_address,
        "company_number": settings.company_number,
        "order_page_url": _order_page_url(order, settings),
        **extra,
    }


def _order_page_url(order: models.Order, settings: Settings) -> str:
    if order.channel != "druvo.uk":
        return ""
    try:
        from app.services.order_tracking import tracking_url

        return tracking_url(order.order_number, settings)
    except RuntimeError:
        return ""


def _render(name: str, ctx: dict) -> tuple[str, str]:
    return _env.get_template(f"{name}.txt").render(**ctx), _env.get_template(f"{name}.html").render(**ctx)


def _send(to: str, subject: str, name: str, ctx: dict, key: str, settings: Settings) -> bool:
    text, html = _render(name, ctx)
    return EmailService(settings).send(to_email=to, subject=subject, body=text, html=html, idempotency_key=key)


def send_order_confirmation(order: models.Order, settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return _send(
        order.email,
        f"Order confirmed — {order.order_number}",
        "order_confirmation",
        _context(order, cfg),
        f"order-confirmation-{order.order_number}",
        cfg,
    )


def send_shop_new_order(order: models.Order, settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    to = cfg.shop_notification_email or cfg.contact_email
    return _send(
        to,
        f"New order {order.order_number} — {money(order.total_pence)}",
        "shop_new_order",
        _context(order, cfg),
        f"shop-new-order-{order.order_number}",
        cfg,
    )


def send_dispatch(order: models.Order, settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return _send(
        order.email,
        f"Your DRUVO UK order {order.order_number} is on its way",
        "order_dispatched",
        _context(order, cfg),
        f"dispatch-{order.order_number}-{order.tracking_number or 'untracked'}",
        cfg,
    )


def send_refund(order: models.Order, refund: models.Refund, settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return _send(
        order.email,
        f"Refund for order {order.order_number}",
        "order_refunded",
        _context(order, cfg, refund=refund),
        f"refund-{refund.stripe_refund_id}",
        cfg,
    )


def send_return_instructions(order: models.Order, request: models.ReturnRequest,
                             settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    return _send(order.email, f"Your return for order {order.order_number}", "return_instructions",
                 _context(order, cfg, return_request=request), f"return-{order.order_number}-{request.id}", cfg)


def send_shop_return_requested(order: models.Order, request: models.ReturnRequest,
                               settings: Settings | None = None) -> bool:
    cfg = settings or get_settings()
    to = cfg.shop_notification_email or cfg.contact_email
    return _send(to, f"Return requested — {order.order_number}", "shop_return_requested",
                 _context(order, cfg, return_request=request), f"shop-return-{order.order_number}-{request.id}", cfg)


def send_pending_notifications(order_id: int | None = None, settings: Settings | None = None) -> dict[str, int]:
    """Send any confirmation / shop / dispatch / refund emails not yet sent (last 14 days)."""
    cfg = settings or get_settings()
    counts = {"confirmation": 0, "shop": 0, "dispatch": 0, "refund": 0}
    if not EmailService(cfg).configured:
        return counts
    since = datetime.now(timezone.utc) - timedelta(days=14)
    with session_scope() as db:
        query = select(models.Order).where(
            models.Order.paid_at.is_not(None),
            models.Order.paid_at >= since,
            or_(
                models.Order.confirmation_email_sent_at.is_(None),
                models.Order.shop_notification_sent_at.is_(None),
                models.Order.dispatch_email_sent_at.is_(None) & models.Order.shipped_at.is_not(None),
            ),
        )
        if order_id is not None:
            query = query.where(models.Order.id == order_id)
        for order in db.scalars(query).all():
            now = datetime.now(timezone.utc)
            if order.confirmation_email_sent_at is None and order.channel == "druvo.uk" and send_order_confirmation(order, cfg):
                order.confirmation_email_sent_at = now
                counts["confirmation"] += 1
            if order.shop_notification_sent_at is None and send_shop_new_order(order, cfg):
                order.shop_notification_sent_at = now
                counts["shop"] += 1
            if order.channel != "druvo.uk":
                continue  # marketplaces email their own buyers; the shop alert above still goes out
            if order.shipped_at is not None and order.dispatch_email_sent_at is None and send_dispatch(order, cfg):
                order.dispatch_email_sent_at = now
                counts["dispatch"] += 1
        refunds = db.scalars(
            select(models.Refund).where(models.Refund.email_sent_at.is_(None), models.Refund.created_at >= since)
        ).all()
        for refund in refunds:
            order = db.get(models.Order, refund.order_id)
            if order_id is not None and order.id != order_id:
                continue
            if send_refund(order, refund, cfg):
                refund.email_sent_at = datetime.now(timezone.utc)
                counts["refund"] += 1
    return counts

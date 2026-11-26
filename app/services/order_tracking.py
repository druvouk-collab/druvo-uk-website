"""Customer order tracking and returns, without customer passwords.

Each order has a private tracking link (order number + an HMAC token derived from SESSION_SECRET). It is
sent in every order email, and customers who lost it can get to it with their order number AND email.
From that page a customer can start a return within the 14-day cancellation window.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.config import Settings, get_settings
from app.db import models
from app.db.base import session_scope

RETURN_WINDOW_DAYS = 14
RETURNABLE_STATUSES = ("paid", "packed", "shipped", "delivered")


class TrackingError(Exception):
    """Shown to the customer as-is."""


def _secret(settings: Settings) -> bytes:
    import os

    secret = settings.session_secret or ""
    deployed = settings.production_mode or os.getenv("RENDER", "").lower() == "true"
    if deployed and secret == "dev-only-change-in-production":
        raise RuntimeError("SESSION_SECRET is still the development default.")
    if len(secret) < 16:
        raise RuntimeError("SESSION_SECRET must be set (16+ characters) for order tracking links.")
    return secret.encode()


def tracking_token(order_number: str, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    digest = hmac.new(_secret(cfg), f"order-track:{order_number}".encode(), hashlib.sha256).hexdigest()
    return digest[:32]


def tracking_url(order_number: str, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    return f"{cfg.public_site_url.rstrip('/')}/orders/{order_number}?t={tracking_token(order_number, cfg)}"


def token_valid(order_number: str, token: str, settings: Settings | None = None) -> bool:
    try:
        expected = tracking_token(order_number, settings)
    except RuntimeError:
        return False
    return hmac.compare_digest(expected, (token or "").strip())


def find_order(order_number: str, email: str, settings: Settings | None = None) -> str | None:
    """Tracking URL when the order number and email match; None otherwise (same answer for both cases)."""
    number = (order_number or "").strip().upper()
    address = (email or "").strip().lower()
    if not number or not address:
        return None
    with session_scope() as db:
        order = db.scalar(select(models.Order).where(models.Order.order_number == number))
        if order is None or order.email.strip().lower() != address or order.status == "pending_payment":
            return None
    return tracking_url(number, settings)


def _return_deadline(order: models.Order) -> datetime | None:
    start = order.delivered_at or order.shipped_at
    if order.status in ("paid", "packed"):
        # Not sent yet: the customer may still cancel; window runs from delivery, so no deadline yet.
        return None
    if start is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    # Delivery date isn't always recorded; allow 14 days after delivery, assuming up to 5 days in transit.
    extra = timedelta(days=0 if order.delivered_at else 5)
    return start + extra + timedelta(days=RETURN_WINDOW_DAYS)


def order_view(order_number: str, token: str) -> dict[str, Any] | None:
    if not token_valid(order_number, token):
        return None
    with session_scope() as db:
        order = db.scalar(select(models.Order).where(models.Order.order_number == order_number))
        if order is None or order.status == "pending_payment":
            return None
        returns = db.scalars(
            select(models.ReturnRequest).where(models.ReturnRequest.order_id == order.id)
            .order_by(models.ReturnRequest.id.desc())
        ).all()
        latest_return = returns[0] if returns else None
        deadline = _return_deadline(order)
        now = datetime.now(timezone.utc)
        can_return = (
            order.status in RETURNABLE_STATUSES
            and latest_return is None
            and (deadline is None or now <= deadline)
        )
        steps = [
            ("Order placed", order.paid_at),
            ("Dispatched", order.shipped_at),
            ("Delivered", order.delivered_at),
        ]
        return {
            "order_number": order.order_number,
            "status": order.status,
            "name": order.name,
            "created_at": order.created_at,
            "items": [
                {"name": i.product_name, "size": i.size, "colour": i.colour, "quantity": i.quantity,
                 "line_pence": i.unit_price_pence * i.quantity}
                for i in order.items
            ],
            "subtotal_pence": order.subtotal_pence,
            "discount_pence": order.discount_pence,
            "shipping_pence": order.shipping_pence,
            "total_pence": order.total_pence,
            "refunded_pence": order.refunded_pence,
            "carrier": order.carrier,
            "tracking_number": order.tracking_number,
            "tracking_url": order.tracking_url,
            "steps": steps,
            "return": (
                {"status": latest_return.status, "reason": latest_return.reason,
                 "created_at": latest_return.created_at}
                if latest_return else None
            ),
            "can_return": can_return,
            "return_deadline": deadline,
        }


def request_return(order_number: str, token: str, reason: str) -> int:
    """Record a return request and email the customer instructions and the shop a notification."""
    if not token_valid(order_number, token):
        raise TrackingError("This link isn't valid. Use the link in your order email.")
    view = order_view(order_number, token)
    if view is None:
        raise TrackingError("Order not found.")
    if not view["can_return"]:
        raise TrackingError("This order can't be returned online. Please email us and we'll help.")
    reason = (reason or "").strip()[:500]
    from app.services import notifications

    with session_scope() as db:
        order = db.scalar(select(models.Order).where(models.Order.order_number == order_number))
        request = models.ReturnRequest(order_id=order.id, status="requested", reason=reason)
        db.add(request)
        db.add(models.AuditLog(actor=order.email, action="return.requested", entity="order",
                               entity_id=order.order_number, details={"reason": reason}))
        db.flush()
        request_id = request.id
        _ = order.items
        if notifications.send_return_instructions(order, request):
            request.customer_email_sent_at = datetime.now(timezone.utc)
        notifications.send_shop_return_requested(order, request)
    return request_id


def mark_return(order_number: str, status: str, *, actor: str) -> None:
    """Admin: mark the latest return for an order as received or rejected."""
    if status not in ("received", "rejected", "refunded"):
        raise ValueError("Unknown return status")
    with session_scope() as db:
        order = db.scalar(select(models.Order).where(models.Order.order_number == order_number))
        if order is None:
            raise ValueError("Order not found")
        request = db.scalar(
            select(models.ReturnRequest).where(models.ReturnRequest.order_id == order.id)
            .order_by(models.ReturnRequest.id.desc())
        )
        if request is None:
            raise ValueError("No return for this order")
        request.status = status
        if status == "received":
            request.received_at = datetime.now(timezone.utc)
        db.add(models.AuditLog(actor=actor, action=f"return.{status}", entity="order",
                               entity_id=order.order_number, details={}))

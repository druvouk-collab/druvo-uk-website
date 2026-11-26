"""Order operations used by the admin dashboard: dispatch + tracking, refunds, restock.

Every change is written to the audit log and queued for DRUVO Manager via the outbox.
Refunds go through Stripe (test mode until launch sign-off) and are mirrored back
from the ``charge.refunded`` webhook, so refunds made in the Stripe dashboard are
recorded too.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import models
from app.db.base import session_scope
from app.services.db_checkout import _get, enqueue_outbox, restore_stock

logger = logging.getLogger(__name__)

CARRIER_TRACKING_URLS = {
    "Royal Mail": "https://www.royalmail.com/track-your-item#/tracking-results/{number}",
}
DISPATCHABLE = ("paid", "packed")


class OrderOpError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def audit(db: Session, actor: str, action: str, entity: str, entity_id: str, **details: Any) -> None:
    db.add(models.AuditLog(actor=actor or "system", action=action, entity=entity, entity_id=str(entity_id), details=details))


def _order(db: Session, order_number: str) -> models.Order:
    order = db.scalar(
        select(models.Order).where(models.Order.order_number == order_number).with_for_update(of=models.Order)
    )
    if order is None:
        raise OrderOpError(f"Order {order_number} not found.")
    return order


def mark_packed(order_number: str, *, actor: str) -> None:
    with session_scope() as db:
        order = _order(db, order_number)
        if order.status != "paid":
            raise OrderOpError(f"Only paid orders can be marked packed (status is {order.status}).")
        order.status = "packed"
        audit(db, actor, "order.packed", "order", order_number)


def mark_dispatched(
    order_number: str,
    *,
    carrier: str,
    tracking_number: str = "",
    tracking_url: str = "",
    actor: str,
    send_email: bool = True,
) -> dict[str, Any]:
    carrier = (carrier or "").strip()[:60]
    tracking_number = (tracking_number or "").strip().replace(" ", "")[:120]
    tracking_url = (tracking_url or "").strip()[:500]
    if tracking_url and not tracking_url.startswith("https://"):
        raise OrderOpError("Tracking link must start with https://")
    if not tracking_url and tracking_number and carrier in CARRIER_TRACKING_URLS:
        tracking_url = CARRIER_TRACKING_URLS[carrier].format(number=tracking_number)
    with session_scope() as db:
        order = _order(db, order_number)
        if order.status not in DISPATCHABLE:
            raise OrderOpError(f"Order {order_number} can't be dispatched (status is {order.status}).")
        order.status = "shipped"
        order.carrier = carrier
        order.tracking_number = tracking_number
        order.tracking_url = tracking_url
        order.shipped_at = _now()
        audit(db, actor, "order.dispatched", "order", order_number, carrier=carrier, tracking=tracking_number)
        enqueue_outbox(
            db,
            "order.shipped",
            {"order_number": order_number, "channel": order.channel, "external_order_id": order.external_order_id,
             "carrier": carrier, "tracking_number": tracking_number},
        )
        if order.channel not in ("druvo.uk",) and order.external_order_id:
            from app.connectors import registered_codes

            cloud = order.channel in registered_codes()
            db.add(models.OutboxEvent(
                topic="order.submit_tracking", consumer="sync" if cloud else "manager",
                payload={"channel": order.channel, "external_order_id": order.external_order_id,
                         "carrier": carrier, "tracking_number": tracking_number}))
        order_id = order.id
    if send_email:
        from app.services.notifications import send_pending_notifications

        send_pending_notifications(order_id=order_id)
    return {"order_number": order_number, "status": "shipped", "tracking_url": tracking_url}


def mark_delivered(order_number: str, *, actor: str) -> None:
    with session_scope() as db:
        order = _order(db, order_number)
        if order.status != "shipped":
            raise OrderOpError("Only shipped orders can be marked delivered.")
        order.status = "delivered"
        order.delivered_at = _now()
        audit(db, actor, "order.delivered", "order", order_number)


def _apply_refund_totals(order: models.Order, refunded_pence: int) -> None:
    order.refunded_pence = min(refunded_pence, order.total_pence)
    if order.refunded_pence >= order.total_pence:
        order.status = "refunded"
    elif order.refunded_pence > 0 and order.status in ("paid", "packed", "shipped", "delivered"):
        order.status = "partially_refunded"


def refund_order(
    order_number: str,
    *,
    amount_pence: int | None = None,
    reason: str = "",
    restock: bool = False,
    actor: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Refund via Stripe. ``amount_pence=None`` refunds whatever is left."""
    cfg = settings or get_settings()
    with session_scope() as db:
        order = _order(db, order_number)
        if not order.stripe_payment_intent_id:
            if order.channel != "druvo.uk":
                raise OrderOpError(f"Refund this order on {order.channel} — marketplace refunds go through the marketplace.")
            raise OrderOpError("This order has no Stripe payment to refund.")
        remaining = order.total_pence - order.refunded_pence
        amount = remaining if amount_pence is None else int(amount_pence)
        if amount <= 0 or amount > remaining:
            raise OrderOpError(f"Refund must be between £0.01 and £{remaining / 100:.2f}.")
        payment_intent = order.stripe_payment_intent_id
        refunds_so_far = len(db.scalars(select(models.Refund).where(models.Refund.order_id == order.id)).all())

    stripe.api_key = cfg.stripe_secret_key
    refund = stripe.Refund.create(
        payment_intent=payment_intent,
        amount=amount,
        reason="requested_by_customer",
        metadata={"order_number": order_number, "note": reason[:200]},
        idempotency_key=f"druvo-refund-{order_number}-{refunds_so_far + 1}-{amount}",
    )

    with session_scope() as db:
        order = _order(db, order_number)
        refund_id = _get(refund, "id")
        row = db.scalar(select(models.Refund).where(models.Refund.stripe_refund_id == refund_id))
        if row is None:
            row = models.Refund(order_id=order.id, stripe_refund_id=refund_id, amount_pence=amount)
            db.add(row)
            _apply_refund_totals(order, order.refunded_pence + amount)
        row.reason = reason[:300]
        row.created_by = actor
        if restock and not row.restocked:
            for item in order.items:
                if item.variant_id is not None:
                    restore_stock(db, item.variant_id, item.quantity, reference=order_number,
                                  reason="refund_restock", actor=actor)
            row.restocked = True
            enqueue_outbox(
                db, "stock.restocked", {"order_number": order_number, "items": [{"sku": i.sku, "quantity": i.quantity} for i in order.items]}
            )
        audit(db, actor, "order.refunded", "order", order_number, amount_pence=amount, restock=restock, reason=reason[:200])
        open_return = db.scalar(
            select(models.ReturnRequest).where(models.ReturnRequest.order_id == order.id,
                                               models.ReturnRequest.status.in_(("requested", "received")))
        )
        if open_return is not None:
            open_return.status = "refunded"
        enqueue_outbox(db, "order.refunded", {"order_number": order_number, "amount_pence": amount})
        order_id = order.id
        status = order.status

    from app.services.notifications import send_pending_notifications

    send_pending_notifications(order_id=order_id)
    return {"order_number": order_number, "refund_id": refund_id, "amount_pence": amount, "status": status}


def sync_refunds_from_charge(db: Session, charge: Any) -> dict[str, Any]:
    """Webhook ``charge.refunded``: mirror refunds (including ones made in the Stripe dashboard)."""
    pi = _get(charge, "payment_intent")
    pi = pi if isinstance(pi, str) else _get(pi, "id")
    if not pi:
        return {"handled": False, "reason": "no_payment_intent"}
    order = db.scalar(
        select(models.Order).where(models.Order.stripe_payment_intent_id == pi).with_for_update(of=models.Order)
    )
    if order is None:
        return {"handled": False, "reason": "unknown_payment_intent"}
    refunds = _get(_get(charge, "refunds") or {}, "data")
    if refunds is None:
        refunds = stripe.Refund.list(payment_intent=pi, limit=100).data
    created = 0
    for refund in refunds or []:
        refund_id = _get(refund, "id")
        if not refund_id or _get(refund, "status") in ("failed", "canceled"):
            continue
        if db.scalar(select(models.Refund).where(models.Refund.stripe_refund_id == refund_id)) is None:
            db.add(
                models.Refund(
                    order_id=order.id,
                    stripe_refund_id=refund_id,
                    amount_pence=int(_get(refund, "amount") or 0),
                    reason="Refunded in Stripe dashboard",
                    created_by="stripe",
                )
            )
            created += 1
    amount_refunded = _get(charge, "amount_refunded")
    if amount_refunded is not None:
        _apply_refund_totals(order, int(amount_refunded))
    if created:
        audit(db, "stripe", "order.refund_synced", "order", order.order_number, new_refunds=created)
    return {"handled": True, "order_number": order.order_number, "order_id": order.id, "new_refunds": created, "notify": ["refund"] if created else []}

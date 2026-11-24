"""Mac-independent checkout: PostgreSQL stock ledger + Stripe Checkout.

Flow
1. ``create_checkout`` validates the basket against the database (prices are
   never trusted from the browser), atomically reserves stock, creates a
   ``pending_payment`` order and a Stripe Checkout Session.
2. Stripe webhooks are recorded in ``stripe_events`` (unique event id), so a
   replayed webhook can never create or change an order twice.
3. ``checkout.session.completed`` (paid) marks the order paid and consumes the
   reservation; ``checkout.session.expired`` releases the stock.
4. ``release_expired_reservations`` is a safety net if an expiry webhook is missed.

Stripe Checkout with automatic payment methods shows cards, Apple Pay,
Google Pay and Link (and PayPal once enabled in the Stripe dashboard).
"""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import stripe
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import models
from app.db.base import session_scope

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_LINES = 20
MAX_QTY_PER_LINE = 10


class CheckoutError(ValueError):
    """Customer-facing checkout problem (HTTP 400/409)."""


class OutOfStockError(CheckoutError):
    def __init__(self, skus: list[str]):
        self.skus = skus
        super().__init__("Sorry — some items in your basket have just sold out: " + ", ".join(skus))


@dataclass(frozen=True)
class BasketLine:
    sku: str
    quantity: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _new_order_number() -> str:
    return "DRV-" + _now().strftime("%y%m%d") + "-" + secrets.token_hex(3).upper()


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return getattr(obj, key, default)


def shipping_pence_for(subtotal_pence: int, settings: Settings) -> int:
    threshold = int(round(settings.shipping_free_threshold_gbp * 100))
    if threshold and subtotal_pence >= threshold:
        return 0
    return int(round(settings.shipping_standard_gbp * 100))


def unit_price_pence(variant: models.Variant) -> int:
    product = variant.product
    if product.is_on_sale and product.sale_price_pence is not None:
        return product.sale_price_pence
    return variant.price_pence


def _merge_lines(lines: list[BasketLine]) -> list[BasketLine]:
    merged: dict[str, int] = {}
    for line in lines:
        sku = (line.sku or "").strip()
        if not sku:
            raise CheckoutError("Basket contains an item without a SKU.")
        if line.quantity <= 0:
            raise CheckoutError("Quantities must be at least 1.")
        merged[sku] = merged.get(sku, 0) + int(line.quantity)
    if not merged:
        raise CheckoutError("Your basket is empty.")
    if len(merged) > MAX_LINES or any(q > MAX_QTY_PER_LINE for q in merged.values()):
        raise CheckoutError("Basket is too large for online checkout — please contact us.")
    return [BasketLine(sku, qty) for sku, qty in merged.items()]


def reserve_stock(session: Session, variant_id: int, quantity: int) -> bool:
    """Atomic conditional decrement — the core oversell guard (works under concurrency)."""
    result = session.execute(
        update(models.Variant)
        .where(models.Variant.id == variant_id, models.Variant.stock_quantity >= quantity)
        .values(stock_quantity=models.Variant.stock_quantity - quantity)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def restore_stock(session: Session, variant_id: int, quantity: int) -> None:
    session.execute(
        update(models.Variant)
        .where(models.Variant.id == variant_id)
        .values(stock_quantity=models.Variant.stock_quantity + quantity)
        .execution_options(synchronize_session=False)
    )


def release_reservations(session: Session, order: models.Order) -> int:
    released = 0
    for reservation in order.reservations:
        if reservation.status == "active":
            restore_stock(session, reservation.variant_id, reservation.quantity)
            reservation.status = "released"
            released += reservation.quantity
    return released


def enqueue_outbox(session: Session, topic: str, payload: dict) -> None:
    """Queue an event for DRUVO Manager / marketplace sync (delivered asynchronously)."""
    session.add(models.OutboxEvent(topic=topic, payload=payload))


class DbCheckoutService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings_override = settings

    @property
    def settings(self) -> Settings:
        return self._settings_override or get_settings()

    def _configure_stripe(self) -> None:
        stripe.api_key = self.settings.stripe_secret_key

    # ------------------------------------------------------------------ create

    def create_checkout(
        self,
        *,
        customer_email: str,
        customer_name: str,
        lines: list[BasketLine],
        idempotency_key: str = "",
        phone: str = "",
        promo_code: str = "",
    ) -> dict[str, str]:
        email = (customer_email or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise CheckoutError("Please enter a valid email address.")
        name = (customer_name or "").strip()[:200]
        key = (idempotency_key or "").strip()[:100] or None
        basket = _merge_lines(lines)

        # Double-click / retry: return the same Stripe session for the same key.
        if key:
            existing = self._existing_for_key(key)
            if existing:
                return existing

        order_id, stripe_lines, order_number, expires_at = self._reserve_and_create_order(
            email=email, name=name, basket=basket, key=key, phone=phone, promo_code=promo_code
        )

        try:
            session = self._create_stripe_session(
                order_number=order_number,
                email=email,
                stripe_lines=stripe_lines,
                expires_at=expires_at,
                shipping_pence=self._order_shipping(order_id),
                discount=self._order_discount(order_id),
            )
        except Exception:
            logger.exception("Stripe session creation failed for %s — releasing stock", order_number)
            with session_scope() as db:
                order = db.get(models.Order, order_id)
                release_reservations(db, order)
                order.status = "cancelled"
                order.notes = "Stripe session could not be created."
            raise RuntimeError("Payment provider is unavailable. Please try again in a moment.")

        with session_scope() as db:
            order = db.get(models.Order, order_id)
            order.stripe_checkout_session_id = _get(session, "id")
            order.stripe_checkout_url = _get(session, "url") or ""
        return {
            "checkout_url": _get(session, "url") or "",
            "session_id": _get(session, "id") or "",
            "order_number": order_number,
            "external_order_id": order_number,
        }

    def _existing_for_key(self, key: str) -> dict[str, str] | None:
        with session_scope() as db:
            order = db.scalar(select(models.Order).where(models.Order.idempotency_key == key))
            if order is None:
                return None
            if order.status == "pending_payment" and order.stripe_checkout_url:
                return {
                    "checkout_url": order.stripe_checkout_url,
                    "session_id": order.stripe_checkout_session_id or "",
                    "order_number": order.order_number,
                    "external_order_id": order.order_number,
                }
            if order.status in ("paid", "packed", "shipped", "delivered"):
                raise CheckoutError(f"This order ({order.order_number}) has already been paid.")
            # Expired/cancelled attempt: free the key so the customer can start again.
            order.idempotency_key = None
            return None

    def _reserve_and_create_order(self, *, email, name, basket, key, phone, promo_code=""):
        self.release_expired_reservations()
        expires_at = _now() + timedelta(minutes=self.settings.stock_reservation_minutes)
        with session_scope() as db:
            skus = [line.sku for line in basket]
            variants = {
                v.sku: v
                for v in db.scalars(select(models.Variant).where(models.Variant.sku.in_(skus))).all()
            }
            missing = [s for s in skus if s not in variants or variants[s].product.status != "live"]
            if missing:
                raise CheckoutError("Some items are no longer available: " + ", ".join(missing))

            sold_out: list[str] = []
            for line in basket:
                if not reserve_stock(db, variants[line.sku].id, line.quantity):
                    sold_out.append(line.sku)
            if sold_out:
                db.rollback()
                raise OutOfStockError(sold_out)

            customer = db.scalar(select(models.Customer).where(models.Customer.email == email))
            if customer is None:
                customer = models.Customer(email=email, name=name, phone=phone or "")
                db.add(customer)
            elif name and not customer.name:
                customer.name = name

            items = []
            stripe_lines = []
            subtotal = 0
            for line in basket:
                variant = variants[line.sku]
                price = unit_price_pence(variant)
                subtotal += price * line.quantity
                items.append(
                    models.OrderItem(
                        variant_id=variant.id,
                        product_slug=variant.product.slug,
                        product_name=variant.product.name,
                        sku=variant.sku,
                        size=variant.size,
                        colour=variant.colour,
                        quantity=line.quantity,
                        unit_price_pence=price,
                        unit_cost_pence=variant.cost_pence,
                    )
                )
                stripe_lines.append(
                    {
                        "name": variant.product.name,
                        "description": " / ".join(x for x in (variant.colour, variant.size) if x) or None,
                        "image": next((i.url for i in variant.product.images), ""),
                        "unit_amount": price,
                        "quantity": line.quantity,
                        "sku": variant.sku,
                    }
                )
            discount, applied_code = 0, ""
            if (promo_code or "").strip():
                discount, applied_code = apply_promotion(db, promo_code, subtotal)
            shipping = shipping_pence_for(subtotal - discount, self.settings)
            order = models.Order(
                order_number=_new_order_number(),
                customer=customer,
                email=email,
                name=name,
                phone=phone or "",
                status="pending_payment",
                subtotal_pence=subtotal,
                discount_pence=discount,
                promo_code=applied_code,
                shipping_pence=shipping,
                total_pence=subtotal - discount + shipping,
                idempotency_key=key,
                reservation_expires_at=expires_at,
                items=items,
            )
            db.add(order)
            db.flush()
            for line in basket:
                db.add(
                    models.StockReservation(
                        order_id=order.id,
                        variant_id=variants[line.sku].id,
                        quantity=line.quantity,
                        expires_at=expires_at,
                    )
                )
            return order.id, stripe_lines, order.order_number, expires_at

    def _order_discount(self, order_id: int) -> tuple[int, str]:
        with session_scope() as db:
            order = db.get(models.Order, order_id)
            return order.discount_pence, order.promo_code

    def _order_shipping(self, order_id: int) -> int:
        with session_scope() as db:
            return db.get(models.Order, order_id).shipping_pence

    def _absolute(self, url: str) -> str:
        if not url or url.startswith("http"):
            return url
        return self.settings.public_site_url.rstrip("/") + "/" + url.lstrip("/")

    def _create_stripe_session(self, *, order_number, email, stripe_lines, expires_at, shipping_pence, discount=(0, "")):
        self._configure_stripe()
        extra: dict[str, Any] = {}
        discount_pence, code = discount
        if discount_pence > 0:
            coupon = stripe.Coupon.create(
                amount_off=discount_pence,
                currency="gbp",
                duration="once",
                max_redemptions=1,
                name=f"Code {code}"[:40],
                metadata={"order_number": order_number, "promo_code": code},
                idempotency_key=f"druvo-coupon-{order_number}",
            )
            extra["discounts"] = [{"coupon": _get(coupon, "id")}]
        base = self.settings.public_site_url.rstrip("/")
        line_items = []
        for line in stripe_lines:
            product_data: dict[str, Any] = {"name": line["name"], "metadata": {"sku": line["sku"]}}
            if line["description"]:
                product_data["description"] = line["description"]
            image = self._absolute(line["image"])
            if image.startswith("https://"):
                product_data["images"] = [image]
            line_items.append(
                {
                    "price_data": {"currency": "gbp", "unit_amount": line["unit_amount"], "product_data": product_data},
                    "quantity": line["quantity"],
                }
            )
        shipping_label = "Free UK delivery (2–4 working days)" if shipping_pence == 0 else "Standard UK delivery (2–4 working days)"
        # Stripe requires expires_at at least 30 minutes ahead; stock is held a few minutes longer.
        stripe_expiry = max(_now() + timedelta(minutes=31), expires_at - timedelta(minutes=3))
        return stripe.checkout.Session.create(
            mode="payment",
            currency="gbp",
            customer_email=email,
            client_reference_id=order_number,
            metadata={"order_number": order_number, "external_order_id": order_number},
            payment_intent_data={"metadata": {"order_number": order_number}, "description": f"DRUVO UK order {order_number}"},
            line_items=line_items,
            shipping_address_collection={"allowed_countries": ["GB"]},
            shipping_options=[
                {
                    "shipping_rate_data": {
                        "type": "fixed_amount",
                        "display_name": shipping_label,
                        "fixed_amount": {"amount": shipping_pence, "currency": "gbp"},
                        "delivery_estimate": {
                            "minimum": {"unit": "business_day", "value": 3},
                            "maximum": {"unit": "business_day", "value": 6},
                        },
                    }
                }
            ],
            phone_number_collection={"enabled": True},
            expires_at=int(stripe_expiry.timestamp()),
            success_url=f"{base}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base}/checkout/cancel?external_order_id={order_number}",
            idempotency_key=f"druvo-checkout-{order_number}",
            **extra,
        )

    # ------------------------------------------------------------------ webhooks

    def verify_event(self, payload: bytes, signature: str) -> Any:
        if not self.settings.stripe_webhook_secret:
            raise RuntimeError("Stripe webhook secret is not configured.")
        try:
            return stripe.Webhook.construct_event(payload, signature, self.settings.stripe_webhook_secret)
        except (stripe.error.SignatureVerificationError, ValueError) as exc:
            raise ValueError("Invalid Stripe webhook signature.") from exc

    def handle_event(self, event: Any) -> dict[str, Any]:
        """Process one verified Stripe event exactly once. Raises on failure so Stripe retries."""
        event_id = _get(event, "id")
        event_type = _get(event, "type")
        obj = _get(_get(event, "data"), "object")
        try:
            with session_scope() as db:
                db.add(models.StripeEvent(event_id=event_id, event_type=event_type))
                db.flush()
                result = self._dispatch(db, event_type, obj)
        except IntegrityError:
            return {"handled": True, "duplicate": True, "event_type": event_type}
        self._after_commit(result)
        return result

    def _dispatch(self, db: Session, event_type: str, obj: Any) -> dict[str, Any]:
        if event_type in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            if _get(obj, "payment_status") not in ("paid", "no_payment_required"):
                return {"handled": False, "reason": "awaiting_payment", "event_type": event_type}
            return self._mark_paid(db, obj)
        if event_type in ("checkout.session.expired", "checkout.session.async_payment_failed"):
            return self._mark_expired(db, obj)
        if event_type == "charge.refunded":
            from app.services.order_ops import sync_refunds_from_charge

            return sync_refunds_from_charge(db, obj)
        return {"handled": False, "event_type": event_type}

    def _order_for_session(self, db: Session, obj: Any, *, lock: bool = True) -> models.Order | None:
        session_id = _get(obj, "id")
        query = select(models.Order).where(models.Order.stripe_checkout_session_id == session_id)
        if lock:
            query = query.with_for_update(of=models.Order)
        order = db.scalar(query)
        if order is None:
            number = _get(_get(obj, "metadata") or {}, "order_number") or _get(obj, "client_reference_id")
            if number:
                q = select(models.Order).where(models.Order.order_number == number)
                order = db.scalar(q.with_for_update(of=models.Order) if lock else q)
                if order is not None and not order.stripe_checkout_session_id:
                    order.stripe_checkout_session_id = session_id
        return order

    def _mark_paid(self, db: Session, obj: Any) -> dict[str, Any]:
        order = self._order_for_session(db, obj)
        if order is None:
            raise LookupError(f"No order for Stripe session {_get(obj, 'id')}")
        if order.status not in ("pending_payment", "expired", "cancelled"):
            return {"handled": True, "duplicate": True, "order_number": order.order_number}

        conflict = False
        if order.status in ("expired", "cancelled"):
            # Paid after the hold was released: try to take the stock again.
            for item in order.items:
                if item.variant_id is None or not reserve_stock(db, item.variant_id, item.quantity):
                    conflict = True
            if conflict:
                order.notes = (order.notes + "\n" if order.notes else "") + (
                    "STOCK CONFLICT: payment received after stock hold expired and an item is no longer "
                    "available. Contact the customer and refund."
                )
        else:
            for reservation in order.reservations:
                if reservation.status == "active":
                    reservation.status = "consumed"

        amount_total = _get(obj, "amount_total")
        if amount_total is not None and int(amount_total) != order.total_pence:
            order.notes = (order.notes + "\n" if order.notes else "") + (
                f"AMOUNT MISMATCH: Stripe charged {amount_total}p, order total {order.total_pence}p."
            )

        order.status = "paid"
        order.paid_at = _now()
        if order.promo_code:
            promo = db.scalar(select(models.Promotion).where(models.Promotion.code == order.promo_code))
            if promo is not None:
                promo.times_used += 1
        pi = _get(obj, "payment_intent")
        order.stripe_payment_intent_id = (pi if isinstance(pi, str) else _get(pi, "id")) or order.stripe_payment_intent_id
        details = _get(obj, "customer_details") or {}
        shipping = _get(_get(obj, "collected_information") or {}, "shipping_details") or _get(obj, "shipping_details") or {}
        address = _get(shipping, "address") or _get(details, "address") or {}
        order.shipping_address = {
            "name": _get(shipping, "name") or _get(details, "name") or order.name,
            "line1": _get(address, "line1") or "",
            "line2": _get(address, "line2") or "",
            "city": _get(address, "city") or "",
            "postal_code": _get(address, "postal_code") or "",
            "country": _get(address, "country") or "GB",
        }
        if not order.name:
            order.name = _get(details, "name") or order.shipping_address["name"] or ""
        order.phone = _get(details, "phone") or order.phone
        types = _get(obj, "payment_method_types") or []
        order.payment_method_type = ",".join(types)[:60] if isinstance(types, list) else ""

        enqueue_outbox(
            db,
            "order.paid",
            {
                "order_number": order.order_number,
                "channel": "druvo.uk",
                "items": [{"sku": i.sku, "quantity": i.quantity, "unit_price_pence": i.unit_price_pence} for i in order.items],
                "total_pence": order.total_pence,
            },
        )
        return {
            "handled": True,
            "status": "paid",
            "order_number": order.order_number,
            "order_id": order.id,
            "stock_conflict": conflict,
            "notify": ["order_confirmation", "shop_new_order"],
            "alert": "STOCK CONFLICT" in (order.notes or "") or "AMOUNT MISMATCH" in (order.notes or ""),
        }

    def _mark_expired(self, db: Session, obj: Any) -> dict[str, Any]:
        order = self._order_for_session(db, obj)
        if order is None:
            return {"handled": False, "reason": "unknown_session"}
        if order.status != "pending_payment":
            return {"handled": True, "duplicate": True, "order_number": order.order_number}
        released = release_reservations(db, order)
        order.status = "expired"
        order.idempotency_key = None
        return {"handled": True, "status": "expired", "order_number": order.order_number, "released": released}

    def _after_commit(self, result: dict[str, Any]) -> None:
        if result.get("status") == "paid" and result.get("order_id"):
            try:
                record_payment_fee(result["order_id"], self.settings)
            except Exception:
                logger.warning("Could not fetch Stripe fee yet for order %s — will retry", result.get("order_number"))
        if result.get("alert"):
            from app.services.alerts import send_alert

            send_alert(
                f"order-problem-{result.get('order_number')}",
                f"Order {result.get('order_number')} needs attention",
                "A paid order was flagged (stock conflict or amount mismatch). Open it in the admin dashboard.",
            )
        if not result.get("notify"):
            return
        try:
            from app.services.notifications import send_pending_notifications

            send_pending_notifications(order_id=result.get("order_id"))
        except Exception:
            logger.exception("Order emails failed — will retry in the background sweep")

    # ------------------------------------------------------------------ maintenance

    def _release_expired(self, db: Session) -> int:
        grace = _now() - timedelta(minutes=5)
        orders = db.scalars(
            select(models.Order)
            .where(models.Order.status == "pending_payment", models.Order.reservation_expires_at < grace)
            .with_for_update(of=models.Order, skip_locked=True)
        ).all()
        for order in orders:
            release_reservations(db, order)
            order.status = "expired"
            order.idempotency_key = None
        return len(orders)

    def release_expired_reservations(self) -> int:
        with session_scope() as db:
            return self._release_expired(db)

    # ------------------------------------------------------------------ queries

    def order_summary_for_session(self, session_id: str) -> dict[str, Any] | None:
        with session_scope() as db:
            order = db.scalar(select(models.Order).where(models.Order.stripe_checkout_session_id == session_id))
            if order is None:
                return None
            return {
                "order_number": order.order_number,
                "status": order.status,
                "email": order.email,
                "total_gbp": order.total_pence / 100,
                "paid": order.status in ("paid", "packed", "shipped", "delivered"),
            }

    def stock_check(self, lines: list[BasketLine]) -> dict[str, Any]:
        basket = _merge_lines(lines)
        with session_scope() as db:
            variants = {
                v.sku: v
                for v in db.scalars(
                    select(models.Variant).where(models.Variant.sku.in_([l.sku for l in basket]))
                ).all()
            }
            problems = [
                l.sku
                for l in basket
                if l.sku not in variants
                or variants[l.sku].product.status != "live"
                or variants[l.sku].stock_quantity < l.quantity
            ]
            return {"ok": not problems, "unavailable": problems}


# ---------------------------------------------------------------------- promotions & fees


class PromoCodeError(CheckoutError):
    pass


def apply_promotion(db: Session, code: str, subtotal_pence: int) -> tuple[int, str]:
    """Return (discount_pence, normalised_code) or raise PromoCodeError with a customer-friendly reason."""
    normalised = (code or "").strip().upper()
    promo = db.scalar(select(models.Promotion).where(models.Promotion.code == normalised))
    now = _now()
    if promo is None or not promo.active:
        raise PromoCodeError("That discount code isn't valid.")
    if promo.starts_at and now < _aware(promo.starts_at):
        raise PromoCodeError("That discount code isn't active yet.")
    if promo.ends_at and now > _aware(promo.ends_at):
        raise PromoCodeError("That discount code has expired.")
    if promo.usage_limit is not None and promo.times_used >= promo.usage_limit:
        raise PromoCodeError("That discount code has been fully used.")
    if subtotal_pence < promo.min_spend_pence:
        raise PromoCodeError(f"That code needs a minimum spend of £{promo.min_spend_pence / 100:.2f}.")
    if promo.discount_type == "percent":
        discount = subtotal_pence * min(promo.discount_value, 90) // 100
    else:
        discount = min(promo.discount_value, subtotal_pence)
    if discount <= 0:
        raise PromoCodeError("That discount code doesn't apply to this basket.")
    return discount, normalised


def record_payment_fee(order_id: int, settings: Settings | None = None) -> int | None:
    """Store Stripe's actual processing fee (from the balance transaction) for profit reports."""
    cfg = settings or get_settings()
    with session_scope() as db:
        order = db.get(models.Order, order_id)
        if order is None or order.payment_fee_pence is not None or not order.stripe_payment_intent_id:
            return None
        pi_id = order.stripe_payment_intent_id
    stripe.api_key = cfg.stripe_secret_key
    intent = stripe.PaymentIntent.retrieve(pi_id, expand=["latest_charge.balance_transaction"])
    txn = _get(_get(intent, "latest_charge"), "balance_transaction")
    fee = _get(txn, "fee")
    if fee is None:
        return None
    with session_scope() as db:
        db.get(models.Order, order_id).payment_fee_pence = int(fee)
    return int(fee)


def backfill_payment_fees(limit: int = 20) -> int:
    with session_scope() as db:
        ids = db.scalars(
            select(models.Order.id)
            .where(models.Order.paid_at.is_not(None), models.Order.payment_fee_pence.is_(None),
                   models.Order.stripe_payment_intent_id.is_not(None))
            .limit(limit)
        ).all()
    done = 0
    for order_id in ids:
        try:
            if record_payment_fee(order_id) is not None:
                done += 1
        except Exception:
            logger.warning("Fee lookup failed for order id %s", order_id)
    return done

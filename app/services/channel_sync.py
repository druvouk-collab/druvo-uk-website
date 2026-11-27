"""Multichannel engine: platforms, listings, marketplace sale import, stock propagation, reconciliation.

Platform modes
* internal  — druvo.uk: reads central stock directly (always in sync).
* automatic — eBay, Amazon: pushed through an API connector. Until the existing DRUVO Manager code is
  audited and ported, these run "via_manager": the cloud queues work for DRUVO Manager to pick up through
  the Manager sync API, so nothing is rebuilt twice.
* assisted  — Vinted, Depop: no permitted automation for this account yet; the system prepares the listing,
  tracks it, and raises a clear manual task (e.g. "item sold elsewhere — remove the Vinted listing").

No platform is assumed to be instant: oversell conflicts are detected, flagged and alerted, never hidden.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import models
from app.db.base import session_scope
from app.services import inventory
from app.services.order_ops import audit

logger = logging.getLogger(__name__)

DEFAULT_CHANNELS = [
    # code, name, mode, connection_status, dispatch_days, notes
    ("druvo.uk", "DRUVO.uk", "internal", "connected", 2, "Website checkout reads central stock directly."),
    ("ebay", "eBay", "automatic", "awaiting_manager", 2,
     "Existing DRUVO Manager integration — to be verified and connected through the Manager sync API."),
    ("amazon", "Amazon", "automatic", "awaiting_manager", 2,
     "Existing DRUVO Manager integration — to be verified (SP-API, own-seller private app)."),
    ("vinted", "Vinted", "assisted", "assisted", 2,
     "Official API = Vinted Pro Integrations (allowlist only). Until approved: assisted listing + manual tasks."),
    ("depop", "Depop", "assisted", "assisted", 2,
     "Official Selling API is partner/invitation-only. Until approved: assisted listing + manual tasks."),
]
ORDER_PREFIX = {"ebay": "EBAY", "amazon": "AMZ", "vinted": "VNT", "depop": "DPP", "druvo.uk": "DRV"}
MAX_ATTEMPTS = 6


class ChannelError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def seed_channels() -> int:
    created = 0
    with session_scope() as db:
        existing = set(db.scalars(select(models.Channel.code)).all())
        for code, name, mode, status, days, notes in DEFAULT_CHANNELS:
            if code not in existing:
                db.add(models.Channel(code=code, name=name, mode=mode, connection_status=status,
                                      dispatch_days=days, notes=notes))
                created += 1
    return created


def get_channel(db, code: str) -> models.Channel:
    channel = db.scalar(select(models.Channel).where(models.Channel.code == code))
    if channel is None:
        raise ChannelError(f"Unknown selling platform '{code}'.")
    return channel


def estimate_fee(channel: models.Channel, gross_pence: int) -> int:
    return channel.fee_fixed_pence + gross_pence * channel.fee_percent_bp // 10000


# ------------------------------------------------------------------ listings


def upsert_listing(
    variant_id: int,
    channel_code: str,
    *,
    actor: str,
    status: str | None = None,
    price_pence: int | None | str = "keep",
    external_listing_id: str | None = None,
    external_url: str | None = None,
    quantity_listed: int | None = None,
    error: str | None = None,
) -> dict:
    if status is not None and status not in models.LISTING_STATUSES:
        raise ChannelError(f"Unknown listing status '{status}'.")
    if external_url and not external_url.startswith("https://"):
        raise ChannelError("Listing link must start with https://")
    with session_scope() as db:
        channel = get_channel(db, channel_code)
        variant = db.get(models.Variant, variant_id)
        if variant is None:
            raise ChannelError("Variant not found.")
        listing = db.scalar(
            select(models.ChannelListing).where(
                models.ChannelListing.variant_id == variant_id, models.ChannelListing.channel_code == channel_code
            )
        )
        if listing is None:
            listing = models.ChannelListing(variant_id=variant_id, channel_code=channel_code)
            db.add(listing)
        before = listing.status
        if status is not None:
            listing.status = status
            if status in ("published", "ended", "not_listed", "sold"):
                listing.attention_reason = ""
        if price_pence != "keep":
            listing.price_pence = price_pence
        if external_listing_id is not None:
            listing.external_listing_id = external_listing_id.strip()[:200]
        if external_url is not None:
            listing.external_url = external_url.strip()[:1000]
        if quantity_listed is not None:
            listing.quantity_listed = quantity_listed
        if error is not None:
            listing.last_error = error[:2000]
        listing.last_synced_at = _now()
        db.flush()
        if channel.mode == "automatic" and status == "pending" and before != "pending":
            # Publishing request for an API platform: the cloud connector if it exists, else DRUVO Manager.
            from app.connectors import registered_codes

            cloud = channel_code in registered_codes()
            db.add(models.OutboxEvent(topic="listing.publish", consumer="sync" if cloud else "manager",
                                      payload={"listing_id": listing.id} if cloud else _listing_payload(db, listing)))
        audit(db, actor, "listing.updated", "listing", listing.id, channel=channel_code, sku=variant.sku,
              status=listing.status)
        return {"listing_id": listing.id, "status": listing.status}


def _effective_price(listing: models.ChannelListing) -> int:
    variant = listing.variant
    if listing.price_pence is not None:
        return listing.price_pence
    product = variant.product
    if product.is_on_sale and product.sale_price_pence is not None:
        return product.sale_price_pence
    return variant.price_pence


def _listing_payload(db, listing: models.ChannelListing) -> dict:
    variant = listing.variant
    product = variant.product
    return {
        "listing_id": listing.id,
        "channel": listing.channel_code,
        "sku": variant.sku,
        "external_listing_id": listing.external_listing_id,
        "quantity": variant.stock_quantity,
        "price_pence": _effective_price(listing),
        "title": product.name,
        "description": product.description,
        "brand": product.brand,
        "condition": product.condition,
        "size": variant.size,
        "colour": variant.colour,
        "category": product.category.slug if product.category else "",
        "images": [img.url for img in product.images],
        "product_id": product.id,
    }


# ------------------------------------------------------------------ marketplace sales


def record_marketplace_sale(
    channel_code: str,
    external_order_id: str,
    lines: list[dict],
    *,
    actor: str,
    shipping_pence: int = 0,
    marketplace_fee_pence: int | None = None,
    buyer_name: str = "",
    buyer_email: str = "",
    shipping_address: dict | None = None,
    dispatch_by: datetime | None = None,
    paid_at: datetime | None = None,
) -> dict[str, Any]:
    """Import one marketplace order exactly once and take the stock from the central ledger.

    If the stock was already gone (sold elsewhere first), the order is still recorded — the buyer has paid
    the marketplace — but flagged OVERSOLD with an alert so you can cancel/refund it on that platform.
    """
    external_order_id = (external_order_id or "").strip()
    if not external_order_id or not lines:
        raise ChannelError("A marketplace order needs an order id and at least one item.")
    if channel_code == "druvo.uk":
        raise ChannelError("Website orders are created by checkout, not imported.")
    try:
        with session_scope() as db:
            channel = get_channel(db, channel_code)
            existing = db.scalar(select(models.Order).where(
                models.Order.channel == channel_code, models.Order.external_order_id == external_order_id))
            if existing is not None:
                return {"duplicate": True, "order_number": existing.order_number, "status": existing.status}
            items, conflicts, subtotal = [], [], 0
            order_number = f"{ORDER_PREFIX.get(channel_code, channel_code[:4].upper())}-{external_order_id}"[:40]
            for line in lines:
                sku = str(line.get("sku", "")).strip().upper()
                qty = int(line.get("quantity", 1))
                price = int(line.get("unit_price_pence", 0))
                if qty <= 0:
                    raise ChannelError("Quantities must be at least 1.")
                variant = db.scalar(select(models.Variant).where(models.Variant.sku == sku))
                subtotal += price * qty
                if variant is None:
                    conflicts.append(f"unknown SKU {sku}")
                    items.append(models.OrderItem(product_slug="", product_name=str(line.get("title") or sku)[:300],
                                                  sku=sku or "UNKNOWN", quantity=qty, unit_price_pence=price))
                    continue
                if not inventory.take_stock(db, variant.id, qty, reason="marketplace_sale", channel=channel_code,
                                            reference=order_number, actor=actor):
                    conflicts.append(f"{sku} had no stock left")
                    inventory.record_movement(db, variant.id, 0, "oversold", channel=channel_code,
                                              reference=order_number, actor=actor)
                items.append(models.OrderItem(
                    variant_id=variant.id, product_slug=variant.product.slug, product_name=variant.product.name,
                    sku=variant.sku, size=variant.size, colour=variant.colour, quantity=qty,
                    unit_price_pence=price, unit_cost_pence=variant.cost_pence))
                listing = db.scalar(select(models.ChannelListing).where(
                    models.ChannelListing.variant_id == variant.id, models.ChannelListing.channel_code == channel_code))
                if listing is not None:
                    db.refresh(variant)
                    listing.status = "sold" if variant.stock_quantity <= 0 else "published"
                    listing.quantity_listed = max(variant.stock_quantity, 0)
            gross = subtotal + shipping_pence
            fee = marketplace_fee_pence if marketplace_fee_pence is not None else estimate_fee(channel, gross)
            paid = paid_at or _now()
            order = models.Order(
                order_number=order_number, channel=channel_code, external_order_id=external_order_id,
                email=(buyer_email or "").strip().lower()[:320], name=(buyer_name or "")[:200], status="paid",
                subtotal_pence=subtotal, shipping_pence=shipping_pence, total_pence=gross,
                marketplace_fee_pence=fee, payment_fee_pence=0,
                fee_status="actual" if marketplace_fee_pence is not None else "estimated",
                shipping_address=shipping_address or {}, paid_at=paid,
                dispatch_by=dispatch_by or paid + timedelta(days=channel.dispatch_days),
                confirmation_email_sent_at=paid,  # the marketplace emails its own buyers
                items=items,
            )
            if conflicts:
                order.notes = "STOCK CONFLICT (oversold): " + "; ".join(conflicts) + \
                    f". Cancel and refund on {channel.name} if you can't fulfil it."
            db.add(order)
            db.flush()
            audit(db, actor, "order.imported", "order", order_number, channel=channel_code, conflicts=conflicts)
            order_id = order.id
    except IntegrityError:
        # Two imports of the same order raced: the other one won.
        with session_scope() as db:
            existing = db.scalar(select(models.Order).where(
                models.Order.channel == channel_code, models.Order.external_order_id == external_order_id))
            return {"duplicate": True, "order_number": existing.order_number, "status": existing.status}

    from app.services.alerts import send_alert
    from app.services.notifications import send_pending_notifications

    try:
        send_pending_notifications(order_id=order_id)  # shop "new order" email
    except Exception:
        logger.exception("Shop notification failed for imported order %s", order_number)
    if conflicts:
        send_alert(f"oversold-{order_number}", f"Oversold: {order_number} on {channel_code}",
                   "This marketplace order arrived after the item had already sold elsewhere: "
                   + "; ".join(conflicts) + ". Open the order in DRUVO Manager to resolve it.")
    return {"duplicate": False, "order_number": order_number, "conflicts": conflicts, "order_id": order_id}


# ------------------------------------------------------------------ sync worker


class NotConnected(Exception):
    pass


def _assisted_sync(db, listing: models.ChannelListing, channel: models.Channel) -> str:
    qty = listing.variant.stock_quantity
    if qty <= 0 and listing.status == "published":
        listing.status = "needs_attention"
        listing.attention_reason = f"Sold out — mark this item sold or remove it on {channel.name}."
        return "manual_task"
    if qty > 0 and listing.status == "needs_attention" and listing.attention_reason.startswith("Sold out"):
        listing.status = "published"
        listing.attention_reason = ""
    listing.quantity_listed = None  # unknown — not readable without an API
    return "ok"


def _automatic_sync(db, listing: models.ChannelListing, channel: models.Channel) -> str:
    from app.connectors import connector_for

    connector = connector_for(channel.code)
    if connector is not None:
        qty = max(listing.variant.stock_quantity, 0)
        connector.update_quantity(_listing_payload(db, listing), qty)
        listing.quantity_listed = qty
        listing.last_error = ""
        if listing.status == "needs_attention" and listing.attention_reason.startswith("Sold out"):
            listing.status, listing.attention_reason = "published", ""
        return "ok"
    if channel.connection_status in ("via_manager", "awaiting_manager"):
        db.add(models.OutboxEvent(topic="listing.set_quantity", consumer="manager", payload=_listing_payload(db, listing)))
        if channel.connection_status == "awaiting_manager":
            listing.status = "needs_attention" if listing.variant.stock_quantity <= 0 else listing.status
            if listing.variant.stock_quantity <= 0:
                listing.attention_reason = (f"Sold out — {channel.name} sync isn't connected yet, so set the quantity "
                                            f"to 0 on {channel.name} yourself.")
        return "queued_for_manager"
    raise NotConnected(f"{channel.name} connector is not configured.")


def process_sync_events(limit: int = 50) -> dict[str, int]:
    counts = {"done": 0, "retry": 0, "failed": 0, "manual": 0}
    with session_scope() as db:
        events = db.scalars(
            select(models.OutboxEvent)
            .where(models.OutboxEvent.consumer == "sync", models.OutboxEvent.status == "pending",
                   (models.OutboxEvent.next_attempt_at.is_(None)) | (models.OutboxEvent.next_attempt_at <= _now()))
            .order_by(models.OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        seen: set[int] = set()
        for event in events:
            listing_id = int((event.payload or {}).get("listing_id", 0))
            if listing_id in seen:  # coalesce: the first run already pushed the current quantity
                event.status, event.sent_at = "done", _now()
                counts["done"] += 1
                continue
            if event.topic == "listing.sync_quantity":
                seen.add(listing_id)
            try:
                with db.begin_nested():
                    listing = db.get(models.ChannelListing, listing_id) if listing_id else None
                    if event.topic == "order.submit_tracking":
                        result = _submit_tracking(db, event.payload or {})
                    elif listing is None:
                        result = "ok"
                    elif event.topic == "listing.publish":
                        result = _publish(db, listing)
                    else:
                        channel = get_channel(db, listing.channel_code)
                        result = (_assisted_sync if channel.mode == "assisted" else _automatic_sync)(db, listing, channel)
                        listing.last_synced_at = _now()
                        channel.last_sync_at = _now()
                event.status, event.sent_at = "done", _now()
                counts["manual" if result == "manual_task" else "done"] += 1
            except Exception as exc:
                event.attempts += 1
                event.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                permanent = getattr(exc, "retryable", True) is False
                if permanent and listing_id:
                    failed_listing = db.get(models.ChannelListing, listing_id)
                    if failed_listing is not None:
                        failed_listing.status, failed_listing.last_error = "failed", str(exc)[:2000]
                if permanent or event.attempts >= MAX_ATTEMPTS:
                    event.status = "failed"
                    counts["failed"] += 1
                else:
                    event.next_attempt_at = _now() + timedelta(minutes=2 ** event.attempts)
                    counts["retry"] += 1
    if counts["failed"]:
        from app.services.alerts import send_alert

        send_alert("sync-failed", "Marketplace sync failed",
                   f"{counts['failed']} stock update(s) failed after {MAX_ATTEMPTS} attempts. "
                   "Check Marketplace connections in DRUVO Manager.")
    if counts["manual"]:
        from app.services.alerts import send_alert

        send_alert("manual-listing-tasks", "Listings need manual action",
                   f"{counts['manual']} listing(s) on Vinted/Depop need updating by hand (item sold elsewhere). "
                   "See Tasks in DRUVO Manager.")
    return counts


def reconcile() -> dict[str, int]:
    """Scheduled safety net: re-queue any listing whose last known marketplace quantity differs from central stock."""
    queued = 0
    with session_scope() as db:
        listings = db.scalars(select(models.ChannelListing).where(
            models.ChannelListing.status.in_(("published", "needs_attention")),
            models.ChannelListing.channel_code != "druvo.uk")).all()
        for listing in listings:
            stock = listing.variant.stock_quantity
            mismatch = listing.quantity_listed is not None and listing.quantity_listed != stock
            assisted_soldout = listing.quantity_listed is None and stock <= 0 and listing.status == "published"
            if mismatch or assisted_soldout:
                db.add(models.OutboxEvent(topic="listing.sync_quantity", consumer="sync", payload={"listing_id": listing.id}))
                queued += 1
    return {"queued": queued}


def open_tasks() -> dict[str, list]:
    """Everything that needs a human: listings needing attention, failed syncs, oversold orders, overdue dispatch."""
    with session_scope() as db:
        listings = db.scalars(select(models.ChannelListing).where(
            models.ChannelListing.status.in_(("needs_attention", "failed")))).all()
        failed = db.scalars(select(models.OutboxEvent).where(models.OutboxEvent.status == "failed")
                            .order_by(models.OutboxEvent.id.desc()).limit(50)).all()
        conflicts = db.scalars(select(models.Order).where(
            models.Order.notes.contains("STOCK CONFLICT") | models.Order.notes.contains("AMOUNT MISMATCH"),
            models.Order.status.in_(("paid", "packed")))).all()
        overdue = db.scalars(select(models.Order).where(
            models.Order.status.in_(("paid", "packed")), models.Order.dispatch_by.is_not(None),
            models.Order.dispatch_by < _now())).all()
        return {"listings": listings, "failed_syncs": failed, "conflicts": conflicts, "overdue": overdue}


# ------------------------------------------------------------------ cloud connector jobs


def _publish(db, listing: models.ChannelListing) -> str:
    from app.connectors import ConnectorError, connector_for, readiness_problems

    connector = connector_for(listing.channel_code)
    if connector is None:
        raise ConnectorError(f"{listing.channel_code} isn't connected in the cloud yet.", retryable=False)
    payload = _listing_payload(db, listing)
    problems = readiness_problems(payload, listing.channel_code)
    if problems:
        listing.status, listing.attention_reason = "needs_attention", " ".join(problems)[:300]
        return "manual_task"
    result = connector.publish(payload)
    listing.status, listing.attention_reason, listing.last_error = "published", "", ""
    listing.external_listing_id = result.external_listing_id[:200]
    listing.external_url = (result.external_url or "")[:1000]
    listing.quantity_listed = payload["quantity"]
    listing.last_synced_at = _now()
    return "ok"


def _submit_tracking(db, payload: dict) -> str:
    from app.connectors import ConnectorError, connector_for

    connector = connector_for(payload.get("channel", ""))
    if connector is None:
        raise ConnectorError("Marketplace isn't connected in the cloud yet.", retryable=False)
    connector.submit_tracking(payload["external_order_id"], payload.get("carrier", ""), payload.get("tracking_number", ""))
    return "ok"


def poll_marketplace_orders() -> dict[str, int]:
    """Import new orders from every platform that has a working cloud connector (runs every 5 minutes)."""
    from app.connectors import connector_for, registered_codes

    imported: dict[str, int] = {}
    for code in registered_codes():
        connector = connector_for(code)
        if connector is None:
            continue
        with session_scope() as db:
            channel = get_channel(db, code)
            since = channel.last_sync_at - timedelta(minutes=15) if channel.last_sync_at else None
        try:
            sales = connector.fetch_orders(since)
            count = 0
            for sale in sales:
                out = record_marketplace_sale(code, sale["external_order_id"], sale["lines"], actor=f"{code}-sync",
                                              **{k: v for k, v in sale.items() if k not in ("external_order_id", "lines")})
                count += 0 if out.get("duplicate") else 1
            with session_scope() as db:
                ch = get_channel(db, code)
                ch.last_sync_at, ch.last_error = _now(), ""
            imported[code] = count
        except Exception as exc:
            logger.exception("Order import failed for %s", code)
            with session_scope() as db:
                get_channel(db, code).last_error = f"Order import failed: {type(exc).__name__}"[:2000]
            from app.services.alerts import send_alert

            send_alert(f"order-import-{code}", f"{code} order import failed",
                       f"New {code} orders couldn't be imported ({type(exc).__name__}). Retrying every 5 minutes.")
    return imported


# ------------------------------------------------------------------ cross-listing ("upload once")


def crosslist_product(product_id: int, channel_codes: list[str], *, actor: str) -> dict[str, dict]:
    """Publish every variant of a product to the chosen platforms in one action.

    druvo.uk → goes live immediately. API platforms → publish job (cloud connector or DRUVO Manager).
    Assisted platforms → a task with the ready-made listing pack. Readiness problems are reported per platform.
    """
    from app.connectors import readiness_problems

    results: dict[str, dict] = {}
    with session_scope() as db:
        product = db.get(models.Product, product_id)
        if product is None:
            raise ChannelError("Product not found.")
        variant_ids = [v.id for v in product.variants]
        channels = {c.code: c for c in db.scalars(select(models.Channel).where(models.Channel.code.in_(channel_codes)))}
        for code in channel_codes:
            channel = channels.get(code)
            if channel is None or not channel.enabled:
                results[code] = {"status": "skipped", "problems": ["Platform is disabled."]}
                continue
            problems: list[str] = []
            for vid in variant_ids:
                draft = models.ChannelListing(variant_id=vid, channel_code=code)
                draft.variant = db.get(models.Variant, vid)
                payload = _listing_payload(db, draft)
                payload["gtin"] = product.gtin
                problems += [p for p in readiness_problems(payload, code) if p not in problems]
            results[code] = {"status": "blocked" if problems else "queued", "problems": problems, "mode": channel.mode}
        if any(r.get("status") == "queued" for c, r in results.items() if c == "druvo.uk"):
            product.status = "live"
    for code, info in results.items():
        if info["status"] != "queued":
            continue
        mode = info["mode"]
        for vid in variant_ids:
            if mode == "internal":
                upsert_listing(vid, code, actor=actor, status="published")
            elif mode == "automatic":
                upsert_listing(vid, code, actor=actor, status="pending")
            else:
                upsert_listing(vid, code, actor=actor, status="needs_attention")
                with session_scope() as db:
                    listing = db.scalar(select(models.ChannelListing).where(
                        models.ChannelListing.variant_id == vid, models.ChannelListing.channel_code == code))
                    if not listing.external_url:
                        listing.attention_reason = (f"Ready to list on {code.title()}: open the listing pack, list it, "
                                                    "then paste the link.")
        info["status"] = {"internal": "live", "automatic": "publishing", "assisted": "task_created"}[mode]
    return results

"""Central stock ledger — the single source of truth for every selling platform.

Every change to ``variants.stock_quantity`` goes through here so it is:
* atomic (conditional SQL update — no overselling under concurrency),
* recorded in ``stock_movements`` (complete history),
* propagated to every other platform the item is listed on (via 'sync' outbox events
  carrying the listing id; the worker always pushes the *current* quantity, so events
  coalesce and order doesn't matter).
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import models

ACTIVE_LISTING_STATUSES = ("pending", "published", "failed", "needs_attention")


def _current(db: Session, variant_id: int) -> int | None:
    return db.scalar(select(models.Variant.stock_quantity).where(models.Variant.id == variant_id))


def record_movement(
    db: Session, variant_id: int, delta: int, reason: str, *, channel: str = "", reference: str = "", actor: str = "system"
) -> None:
    db.add(
        models.StockMovement(
            variant_id=variant_id, delta=delta, quantity_after=_current(db, variant_id), reason=reason,
            channel=channel[:30], reference=reference[:120], actor=(actor or "system")[:320],
        )
    )


def take_stock(
    db: Session, variant_id: int, quantity: int, *, reason: str, channel: str = "", reference: str = "", actor: str = "system"
) -> bool:
    """Atomically remove ``quantity`` if available. Returns False (and changes nothing) if not enough stock."""
    result = db.execute(
        update(models.Variant)
        .where(models.Variant.id == variant_id, models.Variant.stock_quantity >= quantity)
        .values(stock_quantity=models.Variant.stock_quantity - quantity)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return False
    record_movement(db, variant_id, -quantity, reason, channel=channel, reference=reference, actor=actor)
    queue_listing_sync(db, variant_id, source_channel=channel)
    return True


def return_stock(
    db: Session, variant_id: int, quantity: int, *, reason: str, channel: str = "", reference: str = "", actor: str = "system"
) -> None:
    db.execute(
        update(models.Variant)
        .where(models.Variant.id == variant_id)
        .values(stock_quantity=models.Variant.stock_quantity + quantity)
        .execution_options(synchronize_session=False)
    )
    record_movement(db, variant_id, quantity, reason, channel=channel, reference=reference, actor=actor)
    queue_listing_sync(db, variant_id, source_channel=channel)


def set_stock(db: Session, variant: models.Variant, new_quantity: int, *, actor: str, reason: str = "manual_adjustment") -> None:
    delta = new_quantity - (variant.stock_quantity or 0)
    if delta == 0:
        return
    variant.stock_quantity = new_quantity
    db.flush()
    record_movement(db, variant.id, delta, reason, actor=actor)
    queue_listing_sync(db, variant.id)


def queue_listing_sync(db: Session, variant_id: int, *, source_channel: str = "") -> int:
    """Ask the sync worker to push the current quantity to every other platform listing this variant."""
    listings = db.scalars(
        select(models.ChannelListing).where(
            models.ChannelListing.variant_id == variant_id,
            models.ChannelListing.status.in_(ACTIVE_LISTING_STATUSES),
            models.ChannelListing.channel_code != (source_channel or "-"),
            models.ChannelListing.channel_code != "druvo.uk",  # the website reads central stock directly
        )
    ).all()
    for listing in listings:
        db.add(models.OutboxEvent(topic="listing.sync_quantity", consumer="sync", payload={"listing_id": listing.id}))
    return len(listings)


def reserved_quantity(db: Session, variant_id: int) -> int:
    from sqlalchemy import func

    return int(
        db.scalar(
            select(func.coalesce(func.sum(models.StockReservation.quantity), 0)).where(
                models.StockReservation.variant_id == variant_id, models.StockReservation.status == "active"
            )
        )
        or 0
    )

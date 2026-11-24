"""DRUVO Manager sync API — lets the existing DRUVO Manager (and later its cloud workers) use the central database.

Auth: ``Authorization: Bearer <MANAGER_API_KEY>``. All writes are idempotent.

  GET  /api/manager/v1/status                 platforms and connection state
  GET  /api/manager/v1/stock[?sku=]           central available + reserved stock, prices, costs
  POST /api/manager/v1/orders                 import a marketplace sale (eBay/Amazon/Vinted/Depop) — takes stock
  PUT  /api/manager/v1/listings               report a listing's status / id / url / quantity on a platform
  GET  /api/manager/v1/events                 pull queued work (publish listing, set quantity, send tracking…)
  POST /api/manager/v1/events/ack             report results (ok → done; error → retried with backoff)
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import models
from app.db.base import session_scope
from app.services import channel_sync, inventory

router = APIRouter(prefix="/api/manager/v1", tags=["manager-sync"], include_in_schema=False)
ACTOR = "druvo-manager"


def require_manager(request: Request) -> None:
    settings = get_settings()
    if not settings.database_enabled:
        raise HTTPException(status_code=404)
    expected = settings.manager_api_key.strip()
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if len(expected) < 32 or not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid DRUVO Manager API key.")


class SaleLine(BaseModel):
    sku: str
    quantity: int = Field(gt=0, le=100)
    unit_price_pence: int = Field(ge=0)
    title: str = ""


class MarketplaceOrder(BaseModel):
    channel: str
    external_order_id: str = Field(min_length=1, max_length=120)
    lines: list[SaleLine] = Field(min_length=1, max_length=50)
    shipping_pence: int = Field(default=0, ge=0)
    marketplace_fee_pence: int | None = Field(default=None, ge=0)
    buyer_name: str = ""
    buyer_email: str = ""
    shipping_address: dict = Field(default_factory=dict)
    dispatch_by: datetime | None = None
    paid_at: datetime | None = None


class ListingReport(BaseModel):
    sku: str
    channel: str
    status: str | None = None
    external_listing_id: str | None = None
    external_url: str | None = None
    quantity_listed: int | None = Field(default=None, ge=0)
    price_pence: int | None = Field(default=None, ge=0)
    error: str | None = None


class AckItem(BaseModel):
    id: int
    ok: bool
    error: str = ""


class Ack(BaseModel):
    results: list[AckItem] = Field(max_length=500)


@router.get("/status", dependencies=[Depends(require_manager)])
async def status() -> dict:
    channel_sync.seed_channels()
    with session_scope() as db:
        channels = db.scalars(select(models.Channel).order_by(models.Channel.id)).all()
        return {"channels": [{"code": c.code, "name": c.name, "mode": c.mode, "status": c.connection_status,
                              "enabled": c.enabled} for c in channels]}


@router.get("/stock", dependencies=[Depends(require_manager)])
async def stock(sku: str = "") -> dict:
    with session_scope() as db:
        query = select(models.Variant)
        if sku:
            query = query.where(models.Variant.sku == sku.strip().upper())
        rows = db.scalars(query.limit(5000)).all()
        return {"items": [{"sku": v.sku, "available": v.stock_quantity, "reserved": inventory.reserved_quantity(db, v.id),
                           "price_pence": v.price_pence, "cost_pence": v.cost_pence, "product_status": v.product.status,
                           "product_slug": v.product.slug} for v in rows]}


@router.post("/orders", dependencies=[Depends(require_manager)])
async def import_order(order: MarketplaceOrder) -> dict:
    try:
        return await run_in_threadpool(
            lambda: channel_sync.record_marketplace_sale(
                order.channel, order.external_order_id, [line.model_dump() for line in order.lines], actor=ACTOR,
                shipping_pence=order.shipping_pence, marketplace_fee_pence=order.marketplace_fee_pence,
                buyer_name=order.buyer_name, buyer_email=order.buyer_email, shipping_address=order.shipping_address,
                dispatch_by=order.dispatch_by, paid_at=order.paid_at))
    except channel_sync.ChannelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/listings", dependencies=[Depends(require_manager)])
async def report_listing(report: ListingReport) -> dict:
    with session_scope() as db:
        variant = db.scalar(select(models.Variant).where(models.Variant.sku == report.sku.strip().upper()))
        if variant is None:
            raise HTTPException(status_code=404, detail=f"Unknown SKU {report.sku}")
        variant_id = variant.id
    try:
        return await run_in_threadpool(
            lambda: channel_sync.upsert_listing(
                variant_id, report.channel, actor=ACTOR, status=report.status,
                price_pence=report.price_pence if report.price_pence is not None else "keep",
                external_listing_id=report.external_listing_id, external_url=report.external_url,
                quantity_listed=report.quantity_listed, error=report.error))
    except channel_sync.ChannelError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/events", dependencies=[Depends(require_manager)])
async def pull_events(limit: int = 100) -> dict:
    limit = max(1, min(limit, 500))
    now = datetime.now(timezone.utc)
    with session_scope() as db:
        events = db.scalars(
            select(models.OutboxEvent)
            .where(models.OutboxEvent.consumer == "manager", models.OutboxEvent.status == "pending",
                   (models.OutboxEvent.next_attempt_at.is_(None)) | (models.OutboxEvent.next_attempt_at <= now))
            .order_by(models.OutboxEvent.id).limit(limit)
        ).all()
        return {"events": [{"id": e.id, "topic": e.topic, "payload": e.payload, "created_at": e.created_at.isoformat(),
                            "attempts": e.attempts} for e in events]}


@router.post("/events/ack", dependencies=[Depends(require_manager)])
async def ack_events(ack: Ack) -> dict:
    now = datetime.now(timezone.utc)
    done = retried = failed = 0
    with session_scope() as db:
        for item in ack.results:
            event = db.get(models.OutboxEvent, item.id)
            if event is None or event.consumer != "manager" or event.status != "pending":
                continue
            if item.ok:
                event.status, event.sent_at = "done", now
                done += 1
            else:
                event.attempts += 1
                event.last_error = item.error[:2000]
                if event.attempts >= channel_sync.MAX_ATTEMPTS:
                    event.status = "failed"
                    failed += 1
                else:
                    event.next_attempt_at = now + timedelta(minutes=2 ** event.attempts)
                    retried += 1
    if failed:
        from app.services.alerts import send_alert

        send_alert("manager-sync-failed", "DRUVO Manager sync failed",
                   f"{failed} marketplace task(s) failed after {channel_sync.MAX_ATTEMPTS} attempts.")
    return {"done": done, "retried": retried, "failed": failed}

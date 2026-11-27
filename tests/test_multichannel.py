"""One stock figure across DRUVO.uk, eBay, Amazon, Vinted and Depop."""

from __future__ import annotations

import os
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import catalog_repo, models
from app.db.base import session_scope
from app.services import channel_sync
from app.services.db_checkout import BasketLine, DbCheckoutService, OutOfStockError
from tests.test_admin_panel import _login, _setup_owner, admin_env  # noqa: F401
from tests.test_db_checkout import _checkout, _order, _paid_event, shop  # noqa: F401
from tests.db_support import db_url  # noqa: F401

KEY = "k" * 40
AUTH = {"Authorization": f"Bearer {KEY}"}


@pytest.fixture
def mc(shop, monkeypatch):
    monkeypatch.setenv("MANAGER_API_KEY", KEY)
    get_settings.cache_clear()
    channel_sync.seed_channels()
    with session_scope() as db:
        v = db.scalar(select(models.Variant))
        v.stock_quantity = 1
        vid, sku = v.id, v.sku
    for ch in ("ebay", "vinted", "depop"):
        channel_sync.upsert_listing(vid, ch, actor="test", status="published", external_url=f"https://{ch}.example/x")
    with session_scope() as db:  # listing setup queued nothing relevant; start clean
        for e in db.scalars(select(models.OutboxEvent)).all():
            db.delete(e)
    return {"vid": vid, "sku": sku, **shop}


def _stock(vid):
    with session_scope() as db:
        return db.get(models.Variant, vid).stock_quantity


def _listing(vid, ch):
    with session_scope() as db:
        return db.scalar(select(models.ChannelListing).where(models.ChannelListing.variant_id == vid,
                                                            models.ChannelListing.channel_code == ch))


def test_channels_seeded_with_honest_modes(mc):
    with session_scope() as db:
        modes = {c.code: (c.mode, c.connection_status) for c in db.scalars(select(models.Channel))}
    assert modes["druvo.uk"] == ("internal", "connected")
    assert modes["ebay"][0] == "automatic" and modes["amazon"][0] == "automatic"
    assert modes["vinted"] == ("assisted", "assisted") and modes["depop"] == ("assisted", "assisted")


def test_ebay_sale_updates_every_platform(mc):
    out = channel_sync.record_marketplace_sale("ebay", "12-34567-89", [{"sku": mc["sku"], "quantity": 1, "unit_price_pence": 2500}],
                                               actor="test", marketplace_fee_pence=320, buyer_name="Jo")
    assert out["conflicts"] == [] and _stock(mc["vid"]) == 0
    assert _listing(mc["vid"], "ebay").status == "sold"
    counts = channel_sync.process_sync_events()
    assert counts["manual"] == 2  # vinted + depop need a human
    vinted = _listing(mc["vid"], "vinted")
    assert vinted.status == "needs_attention" and "Vinted" in vinted.attention_reason
    with pytest.raises(OutOfStockError):  # website can't sell it any more
        DbCheckoutService().create_checkout(customer_email="w@example.com", customer_name="W", lines=[BasketLine(mc["sku"], 1)])
    order = _order(out["order_number"])
    assert order.channel == "ebay" and order.fee_status == "actual" and order.marketplace_fee_pence == 320
    assert order.dispatch_by is not None
    subjects = [e["json"]["subject"] for e in mc["emails"]]
    assert any(s.startswith(f"New order {order.order_number}") for s in subjects)
    assert not any(s.startswith("Order confirmed") for s in subjects)  # eBay emails its own buyer
    assert any("Listings need manual action" in s for s in subjects)
    with session_scope() as db:
        reasons = [m.reason for m in db.scalars(select(models.StockMovement).where(models.StockMovement.variant_id == mc["vid"]))]
    assert "marketplace_sale" in reasons


def test_duplicate_import_is_ignored(mc):
    line = [{"sku": mc["sku"], "quantity": 1, "unit_price_pence": 2500}]
    channel_sync.record_marketplace_sale("vinted", "V-1", line, actor="test")
    again = channel_sync.record_marketplace_sale("vinted", "V-1", line, actor="test")
    assert again["duplicate"] is True and _stock(mc["vid"]) == 0


def test_oversell_is_recorded_flagged_and_alerted(mc):
    channel_sync.record_marketplace_sale("ebay", "E-1", [{"sku": mc["sku"], "quantity": 1, "unit_price_pence": 2500}], actor="t")
    late = channel_sync.record_marketplace_sale("depop", "D-9", [{"sku": mc["sku"], "quantity": 1, "unit_price_pence": 2400}], actor="t")
    assert late["conflicts"] and _stock(mc["vid"]) == 0
    order = _order(late["order_number"])
    assert "STOCK CONFLICT" in order.notes and order.fee_status == "estimated"
    assert any("Oversold" in e["json"]["subject"] for e in mc["emails"])
    tasks = channel_sync.open_tasks()
    assert any(o.order_number == late["order_number"] for o in tasks["conflicts"])


def test_website_sale_queues_ebay_update_for_manager(mc):
    result = _checkout()
    assert _stock(mc["vid"]) == 0  # held during checkout → other platforms told immediately
    channel_sync.process_sync_events()
    with session_scope() as db:
        jobs = db.scalars(select(models.OutboxEvent).where(models.OutboxEvent.consumer == "manager",
                                                           models.OutboxEvent.topic == "listing.set_quantity")).all()
        assert jobs and jobs[-1].payload["quantity"] == 0 and jobs[-1].payload["channel"] == "ebay"
    assert _listing(mc["vid"], "ebay").status == "needs_attention"  # eBay sync not connected yet → manual task
    # Abandoned checkout returns the item and the platforms are told again.
    DbCheckoutService().handle_event({"id": "evt_x", "type": "checkout.session.expired",
                                      "data": {"object": {"id": result["session_id"]}}})
    assert _stock(mc["vid"]) == 1
    channel_sync.process_sync_events()
    assert _listing(mc["vid"], "vinted").status == "published"


def test_sync_retries_with_backoff_then_alerts(mc, monkeypatch):
    def boom(db, listing, channel):
        raise RuntimeError("marketplace timeout")

    monkeypatch.setattr(channel_sync, "_automatic_sync", boom)
    with session_scope() as db:
        listing_id = db.scalar(select(models.ChannelListing.id).where(models.ChannelListing.channel_code == "ebay"))
        db.add(models.OutboxEvent(topic="listing.sync_quantity", consumer="sync", payload={"listing_id": listing_id}))
    assert channel_sync.process_sync_events()["retry"] == 1
    with session_scope() as db:
        event = db.scalar(select(models.OutboxEvent).where(models.OutboxEvent.consumer == "sync"))
        assert event.attempts == 1 and event.next_attempt_at is not None
        event.attempts = channel_sync.MAX_ATTEMPTS - 1
        event.next_attempt_at = None
    assert channel_sync.process_sync_events()["failed"] == 1
    assert any("Marketplace sync failed" in e["json"]["subject"] for e in mc["emails"])


def test_reconcile_requeues_mismatched_listing(mc):
    channel_sync.upsert_listing(mc["vid"], "ebay", actor="t", quantity_listed=5)
    assert channel_sync.reconcile()["queued"] >= 1


def test_manager_api(mc):
    from app.main import app

    client = TestClient(app)
    assert client.get("/api/manager/v1/status").status_code == 401
    assert client.get("/api/manager/v1/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert {c["code"] for c in client.get("/api/manager/v1/status", headers=AUTH).json()["channels"]} >= {"ebay", "amazon"}
    stock = client.get(f"/api/manager/v1/stock?sku={mc['sku']}", headers=AUTH).json()["items"][0]
    assert stock["available"] == 1 and stock["reserved"] == 0
    order = {"channel": "amazon", "external_order_id": "203-111", "lines": [{"sku": mc["sku"], "quantity": 1, "unit_price_pence": 2600}],
             "marketplace_fee_pence": 400, "buyer_name": "A Buyer"}
    first = client.post("/api/manager/v1/orders", json=order, headers=AUTH).json()
    assert first["duplicate"] is False and _stock(mc["vid"]) == 0
    assert client.post("/api/manager/v1/orders", json=order, headers=AUTH).json()["duplicate"] is True
    assert client.post("/api/manager/v1/orders", json=dict(order, channel="nope", external_order_id="z"),
                       headers=AUTH).status_code == 400
    put = client.put("/api/manager/v1/listings", json={"sku": mc["sku"], "channel": "ebay", "status": "ended",
                                                       "external_listing_id": "1234"}, headers=AUTH)
    assert put.status_code == 200 and _listing(mc["vid"], "ebay").status == "ended"
    channel_sync.upsert_listing(mc["vid"], "amazon", actor="t", status="pending")  # publish request
    events = client.get("/api/manager/v1/events", headers=AUTH).json()["events"]
    publish = [e for e in events if e["topic"] == "listing.publish"]
    assert publish and publish[0]["payload"]["sku"] == mc["sku"]
    ack = client.post("/api/manager/v1/events/ack", json={"results": [{"id": publish[0]["id"], "ok": False, "error": "rate limited"}]},
                      headers=AUTH).json()
    assert ack["retried"] == 1
    assert all(e["id"] != publish[0]["id"] for e in client.get("/api/manager/v1/events", headers=AUTH).json()["events"])


def test_admin_multichannel_screens(mc, admin_env):
    client = admin_env["client"]
    csrf = _login(client, _setup_owner(client))
    for url in ("/admin/tasks", "/admin/inventory", f"/admin/inventory/{mc['vid']}", "/admin/channels",
                "/admin/orders/import", "/admin/reports", "/admin/reports.csv?by=month"):
        assert client.get(url).status_code == 200, url
    with session_scope() as db:
        pid = db.get(models.Variant, mc["vid"]).product_id
    page = client.get(f"/admin/products/{pid}")
    assert "Where it" in page.text and "Listing pack" in page.text
    assert client.get(f"/admin/products/{pid}/pack/vinted").status_code == 200
    r = client.post("/admin/orders/import", data={"csrf": csrf, "channel": "vinted", "external_order_id": "VNT-55",
                                                  "sku": mc["sku"], "quantity": "1", "price": "22.00"}, follow_redirects=True)
    assert "Sale recorded" in r.text and _stock(mc["vid"]) == 0
    r = client.post("/admin/channels/ebay", data={"csrf": csrf, "fee_percent": "12.8", "fee_fixed": "0.30",
                                                  "dispatch_days": "2", "enabled": "1"}, follow_redirects=True)
    assert "saved" in r.text
    with session_scope() as db:
        assert db.scalar(select(models.Channel).where(models.Channel.code == "ebay")).fee_percent_bp == 1280


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL")
def test_simultaneous_website_and_marketplace_sale(mc):
    barrier = threading.Barrier(2)
    results = {}

    def web():
        barrier.wait()
        try:
            _checkout(email="race@example.com")
            results["web"] = "got_it"
        except OutOfStockError:
            results["web"] = "sold_out"

    def ebay():
        barrier.wait()
        out = channel_sync.record_marketplace_sale("ebay", "RACE-1", [{"sku": mc["sku"], "quantity": 1, "unit_price_pence": 2500}], actor="t")
        results["ebay"] = "conflict" if out["conflicts"] else "got_it"

    threads = [threading.Thread(target=web), threading.Thread(target=ebay)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results.values()) in (["conflict", "got_it"], ["got_it", "sold_out"])
    assert _stock(mc["vid"]) == 0

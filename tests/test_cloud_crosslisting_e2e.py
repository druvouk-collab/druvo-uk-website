"""End-to-end, cloud-only: create → publish everywhere → marketplace order → stock → delist → dispatch → profit.

eBay and Amazon are SIMULATED here by in-memory fake marketplaces implementing the same Connector contract the
real cloud connectors will implement. This proves DRUVO Manager's own flow end-to-end without the MacBook; it is
not a substitute for sandbox/live marketplace testing (see docs/PROGRESS.md, Phase 12).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

import app.connectors as connectors
from app.config import get_settings
from app.connectors import Connector, PublishResult
from app.db import models
from app.db.base import session_scope
from app.services import channel_sync, reporting
from app.services.background import run_maintenance_once
from app.services.credentials import CredentialsError, credential_summary, load_credentials, save_credentials
from app.services.db_checkout import BasketLine, DbCheckoutService, OutOfStockError
from tests.test_admin_panel import _login, _png, _setup_owner, admin_env  # noqa: F401
from tests.test_db_checkout import shop  # noqa: F401
from tests.db_support import db_url  # noqa: F401


class FakeMarketplace(Connector):
    """In-memory stand-in for a marketplace API."""

    listings: dict = {}
    pending_orders: list = []
    tracking: list = []

    def publish(self, listing):
        lid = f"{self.channel_code.upper()}-{listing['sku']}"
        FakeMarketplace.listings[(self.channel_code, lid)] = {"qty": listing["quantity"], "price": listing["price_pence"]}
        return PublishResult(lid, f"https://{self.channel_code}.example/itm/{lid}")

    def update_quantity(self, listing, quantity):
        FakeMarketplace.listings[(self.channel_code, listing["external_listing_id"])]["qty"] = quantity

    def fetch_orders(self, since):
        mine = [o for o in FakeMarketplace.pending_orders if o["channel"] == self.channel_code]
        return [{k: v for k, v in o.items() if k != "channel"} for o in mine]

    def submit_tracking(self, external_order_id, carrier, tracking_number):
        FakeMarketplace.tracking.append((self.channel_code, external_order_id, carrier, tracking_number))


class FakeEbay(FakeMarketplace):
    channel_code = "ebay"


class FakeAmazon(FakeMarketplace):
    channel_code = "amazon"


@pytest.fixture
def cloud(admin_env, monkeypatch):
    monkeypatch.setenv("CREDENTIALS_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    monkeypatch.setattr(connectors, "_REGISTRY", {"ebay": FakeEbay, "amazon": FakeAmazon})
    FakeMarketplace.listings, FakeMarketplace.pending_orders, FakeMarketplace.tracking = {}, [], []
    channel_sync.seed_channels()
    save_credentials("ebay", {"refresh_token": "secret-ebay"}, environment="sandbox", account_label="druvo-test")
    save_credentials("amazon", {"refresh_token": "secret-amz"}, environment="sandbox")
    return admin_env


def test_credentials_are_encrypted_and_never_displayed(cloud, monkeypatch):
    with session_scope() as db:
        raw = db.scalar(select(models.ChannelCredential).where(models.ChannelCredential.channel_code == "ebay")).encrypted
    assert "secret-ebay" not in raw
    assert load_credentials("ebay")["refresh_token"] == "secret-ebay"
    assert load_credentials("ebay")["_environment"] == "sandbox"
    assert "secret" not in str(credential_summary())
    monkeypatch.setenv("CREDENTIALS_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    with pytest.raises(CredentialsError):
        load_credentials("ebay")


def test_full_journey_without_the_mac(cloud):
    client = cloud["client"]
    csrf = _login(client, _setup_owner(client))

    # 1. Create the product once (with a photo) in DRUVO Manager.
    r = client.post("/admin/products/new", data={
        "csrf": csrf, "name": "Nike Air Max 90 White Trainers UK 9", "brand": "Nike", "condition": "Pre-loved – Excellent",
        "category": "footwear", "status": "draft", "description": "Worn twice, excellent condition, original box.",
        "variant_count": "0", "v0_sku": "NK-AM90-9", "v0_size": "UK 9", "v0_colour": "White", "v0_price": "60.00",
        "v0_cost": "22.00", "v0_stock": "1"}, follow_redirects=False)
    pid = int(re.search(r"/admin/products/(\d+)", r.headers["location"]).group(1))
    client.post(f"/admin/products/{pid}/images", data={"csrf": csrf}, files={"photo": ("a.png", _png(), "image/png")})

    # 2. Publish everywhere in one action.
    r = client.post(f"/admin/products/{pid}/crosslist", data={"csrf": csrf, "channels": ["druvo.uk", "ebay", "amazon", "vinted"]},
                    follow_redirects=True)
    assert "druvo.uk: live" in r.text and "ebay: publishing" in r.text and "vinted: listing pack ready" in r.text
    assert "amazon: needs fixing" in r.text  # no barcode → honest readiness check, not a silent failure
    run_maintenance_once()  # cloud worker publishes to the marketplaces
    assert ("ebay", "EBAY-NK-AM90-9") in FakeMarketplace.listings
    with session_scope() as db:
        ebay_listing = db.scalar(select(models.ChannelListing).where(models.ChannelListing.channel_code == "ebay"))
        assert ebay_listing.status == "published" and ebay_listing.external_url.startswith("https://ebay.example/")
        variant_id = ebay_listing.variant_id
    assert client.get("/product/nike-air-max-90-white-trainers-uk-9").status_code == 200  # live on DRUVO.uk

    # 3. An order arrives on eBay (imported by the cloud worker).
    FakeMarketplace.pending_orders.append({"channel": "ebay", "external_order_id": "26-11111-22222",
                                           "lines": [{"sku": "NK-AM90-9", "quantity": 1, "unit_price_pence": 6000}],
                                           "marketplace_fee_pence": 790, "buyer_name": "Sam Buyer",
                                           "shipping_address": {"line1": "1 Road", "city": "Leeds", "postal_code": "LS1 1AA"}})
    run_maintenance_once()
    run_maintenance_once()  # second run proves the import is idempotent
    with session_scope() as db:
        orders = db.scalars(select(models.Order).where(models.Order.channel == "ebay")).all()
        assert len(orders) == 1
        number = orders[0].order_number
        # 4. Central stock updated, 5. other platforms updated or turned into tasks.
        assert db.get(models.Variant, variant_id).stock_quantity == 0
        vinted = db.scalar(select(models.ChannelListing).where(models.ChannelListing.channel_code == "vinted"))
        assert vinted.status == "needs_attention"
    with pytest.raises(OutOfStockError):
        DbCheckoutService().create_checkout(customer_email="x@example.com", customer_name="X", lines=[BasketLine("NK-AM90-9", 1)])

    # 6. Dispatch + tracking pushed back to eBay by the cloud worker.
    r = client.post(f"/admin/orders/{number}/dispatch", data={"csrf": csrf, "carrier": "Royal Mail",
                                                              "tracking_number": "RM123456789GB", "postage_cost": "3.40"},
                    follow_redirects=True)
    assert "Dispatched" in r.text
    run_maintenance_once()
    assert ("ebay", "26-11111-22222", "Royal Mail", "RM123456789GB") in FakeMarketplace.tracking
    emails = [e["json"]["subject"] for e in cloud["emails"]]
    assert not any("on its way" in s for s in emails)  # eBay notifies its own buyer

    # 7. Actual profit: £60 − £7.90 eBay fee − £22 cost − £3.40 postage = £26.70
    with session_scope() as db:
        order = db.scalar(select(models.Order).where(models.Order.order_number == number))
        assert order.fee_status == "actual"
    t = reporting.totals_between(datetime(2000, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc))
    assert t.profit_pence == 6000 - 790 - 2200 - 340
    assert t.by_channel["ebay"]["profit_pence"] == 2670


def test_permanent_marketplace_rejection_marks_listing_failed(cloud, monkeypatch):
    from app.connectors import ConnectorError

    def reject(self, listing):
        raise ConnectorError("Category requires 'Shoe Size'", retryable=False)

    monkeypatch.setattr(FakeEbay, "publish", reject)
    with session_scope() as db:
        v = db.scalar(select(models.Variant))
        v.stock_quantity = 1
        p = v.product
        p.description, p.condition, p.brand = "A good description of the item here.", "New", "BALANCE"
        pid = p.id
    channel_sync.crosslist_product(pid, ["ebay"], actor="t")
    out = channel_sync.process_sync_events()
    assert out["failed"] == 1
    with session_scope() as db:
        listing = db.scalar(select(models.ChannelListing).where(models.ChannelListing.channel_code == "ebay"))
        assert listing.status == "failed" and "Shoe Size" in listing.last_error

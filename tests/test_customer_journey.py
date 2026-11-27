"""End-to-end customer journey on the cloud shop, one test per step in order:
browse → basket → pay → confirmation → find order → dispatch → delivered → return → refund + restock.

Stripe and the email provider are replaced with recorders (see test_db_checkout.shop); everything else is the
real application, database and templates. The same journey with real Stripe test mode runs in
.github/workflows/stripe-e2e.yml once Stripe test keys are added.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import models
from app.db.base import session_scope
from app.main import app
from app.services import order_ops, order_tracking
from app.services.db_checkout import DbCheckoutService
from tests import test_db_checkout as checkout_tests
from tests.test_db_checkout import _order, _paid_event, _stock, shop  # noqa: F401
from tests.db_support import db_url  # noqa: F401


@pytest.fixture
def client(shop, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SESSION_SECRET", "journey-test-secret-0123456789abcdef")
    from app.config import get_settings

    get_settings.cache_clear()
    with TestClient(app, base_url="https://druvo.uk") as c:
        yield c


def _emails(shop, starts: str) -> list[dict]:  # noqa: F811
    return [e["json"] for e in shop["emails"] if e["json"]["subject"].startswith(starts)]


def test_full_customer_journey(client, shop):  # noqa: F811
    sku = checkout_tests.SKU
    with session_scope() as db:
        variant = db.scalar(select(models.Variant).where(models.Variant.sku == sku))
        slug, price = variant.product.slug, variant.price_pence / 100
    stock_start = _stock()

    # 1. Browse: shop and product page show the item with an add-to-basket button.
    assert client.get("/shop").status_code == 200
    page = client.get(f"/product/{slug}")
    assert page.status_code == 200 and "data-add-to-cart" in page.text

    # 2. Checkout: the basket becomes a Stripe Checkout session; stock is held for this customer.
    started = client.post("/api/checkout/payment-session", json={
        "customer_email": "Journey@Example.com", "customer_name": "Jo Journey",
        "external_order_id": "journey-1", "lines": [{"sku": sku, "quantity": 1, "unit_price_gbp": price}],
    })
    assert started.status_code == 200, started.text
    body = started.json()
    number = body["order_number"]
    assert body["checkout_url"].startswith("https://checkout.stripe.com/")
    assert _stock() == stock_start - 1

    # 3. Payment: Stripe's webhook marks the order paid exactly once.
    order = _order(number)
    DbCheckoutService().handle_event(_paid_event(body["session_id"], order))
    assert _order(number).status == "paid"

    # 4. Confirmation email carries the private order page link.
    confirmation = _emails(shop, "Order confirmed")[0]
    link = re.search(r"https://druvo\.uk/orders/[^\s\"]+", confirmation["text"]).group(0)
    path = link.replace("https://druvo.uk", "")
    status_page = client.get(path)
    assert status_page.status_code == 200 and 'data-order-status="paid"' in status_page.text
    assert status_page.headers["x-robots-tag"].startswith("noindex")

    # 5. A customer who lost the email finds the order with number + email; wrong email or token fails.
    found = client.post("/orders/find", data={"order_number": number.lower(), "email": "journey@example.com"},
                        follow_redirects=False)
    assert found.status_code == 303 and found.headers["location"] == path
    assert client.post("/orders/find", data={"order_number": number, "email": "someone@else.com"}).status_code == 404
    assert client.get(f"/orders/{number}?t=wrongtoken").status_code == 404

    # 6. Dispatch: tracking saved, customer emailed, order page shows the parcel.
    order_ops.mark_dispatched(number, carrier="Royal Mail", tracking_number="AB123456789GB", actor="admin@druvo.uk")
    dispatch = _emails(shop, "Your DRUVO UK order")[0]
    assert "AB123456789GB" in dispatch["text"] and path in dispatch["text"]
    shipped_page = client.get(path).text
    assert 'data-order-status="shipped"' in shipped_page and "AB123456789GB" in shipped_page

    # 7. Delivered.
    order_ops.mark_delivered(number, actor="admin@druvo.uk")
    delivered_page = client.get(path).text
    assert 'data-order-status="delivered"' in delivered_page and "data-start-return" in delivered_page

    # 8. Return: customer starts it from the order page; both sides are emailed; it can't be started twice.
    token = path.split("t=")[1]
    started_return = client.post(f"/orders/{number}/return", data={"t": token, "reason": "Too small"},
                                 follow_redirects=False)
    assert started_return.status_code == 303
    assert _emails(shop, f"Your return for order {number}")
    assert _emails(shop, f"Return requested — {number}")
    after = client.get(path).text
    assert 'data-return-status="requested"' in after and "data-start-return" not in after
    assert client.post(f"/orders/{number}/return", data={"t": token, "reason": "again"}).status_code == 400

    # 9. Parcel arrives: shop marks it received and refunds with restock; customer emailed; stock back.
    order_tracking.mark_return(number, "received", actor="admin@druvo.uk")
    order_ops.refund_order(number, reason="Returned within 14 days", restock=True, actor="admin@druvo.uk")
    assert _emails(shop, f"Refund for order {number}")
    final = client.get(path).text
    assert 'data-order-status="refunded"' in final and 'data-return-status="refunded"' in final
    assert _stock() == stock_start
    assert shop["refunds"][0]["payment_intent"] == _order(number).stripe_payment_intent_id


def test_return_window_closes_after_14_days(client, shop):  # noqa: F811
    from datetime import datetime, timedelta, timezone

    result = checkout_tests._checkout(email="late@example.com")
    number = result["order_number"]
    DbCheckoutService().handle_event(_paid_event(result["session_id"], _order(number)))
    order_ops.mark_dispatched(number, carrier="Royal Mail", tracking_number="AB000000001GB", actor="a@druvo.uk")
    order_ops.mark_delivered(number, actor="a@druvo.uk")
    with session_scope() as db:
        o = db.scalar(select(models.Order).where(models.Order.order_number == number))
        o.delivered_at = datetime.now(timezone.utc) - timedelta(days=15)
    token = order_tracking.tracking_token(number)
    page = client.get(f"/orders/{number}?t={token}").text
    assert "data-start-return" not in page
    assert client.post(f"/orders/{number}/return", data={"t": token}).status_code == 400


def test_lookup_is_rate_limited(client, shop):  # noqa: F811
    from app.routes import orders as orders_routes

    orders_routes._LOOKUPS.clear()
    codes = [client.post("/orders/find", data={"order_number": "DRV-X", "email": "x@y.com"}).status_code
             for _ in range(11)]
    assert codes[:10] == [404] * 10 and codes[10] == 429
    orders_routes._LOOKUPS.clear()

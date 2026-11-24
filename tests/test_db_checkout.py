"""Mac-independent checkout: stock reservation, Stripe webhooks, emails, dispatch, refunds."""

from __future__ import annotations

import itertools
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest
import stripe
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.data.static_catalog import CATALOG_PATH
from app.db import catalog_repo, models
from app.db.base import session_scope
from app.services import order_ops
from app.services.db_checkout import BasketLine, CheckoutError, DbCheckoutService, OutOfStockError
from tests.db_support import db_url  # noqa: F401

SKU = "DRUVO-BAL-TRK-CRM-L"
_ids = itertools.count(1)


@pytest.fixture
def shop(db_url, monkeypatch):
    for key, value in {
        "STRIPE_SECRET_KEY": "sk_test_dummy",
        "STRIPE_PUBLISHABLE_KEY": "pk_test_dummy",
        "STRIPE_WEBHOOK_SECRET": "whsec_dummy",
        "RESEND_API_KEY": "re_test_dummy",
        "SITE_URL": "https://druvo.uk",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    catalog_repo.import_catalog_json(CATALOG_PATH)
    with session_scope() as s:
        variant = s.scalar(select(models.Variant))
        global SKU
        SKU = variant.sku

    sessions: list[dict] = []
    refunds: list[dict] = []
    emails: list[dict] = []

    def fake_session_create(**kwargs):
        sid = f"cs_test_{next(_ids)}"
        sessions.append({"id": sid, **kwargs})
        return {"id": sid, "url": f"https://checkout.stripe.com/c/pay/{sid}"}

    def fake_refund_create(**kwargs):
        rid = f"re_{next(_ids)}"
        refunds.append({"id": rid, **kwargs})
        return {"id": rid, "amount": kwargs["amount"], "status": "succeeded"}

    class FakeResponse:
        status_code = 200

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url == "https://api.resend.com/emails"
        emails.append({"json": json, "headers": headers})
        return FakeResponse()

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(fake_session_create))
    monkeypatch.setattr(stripe.Refund, "create", staticmethod(fake_refund_create))
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", staticmethod(
        lambda pi, expand=None: {"id": pi, "latest_charge": {"balance_transaction": {"fee": 56}}}))
    monkeypatch.setattr("app.services.email_service.httpx.post", fake_post)
    yield {"sessions": sessions, "refunds": refunds, "emails": emails}
    get_settings.cache_clear()


def _stock() -> int:
    with session_scope() as s:
        return s.scalar(select(models.Variant).where(models.Variant.sku == SKU)).stock_quantity


def _order(number: str) -> models.Order:
    with session_scope() as s:
        order = s.scalar(select(models.Order).where(models.Order.order_number == number))
        _ = order.items, order.reservations
        return order


def _set_stock(qty: int) -> None:
    with session_scope() as s:
        s.scalar(select(models.Variant).where(models.Variant.sku == SKU)).stock_quantity = qty


def _checkout(key: str = "", email: str = "buyer@example.com") -> dict:
    return DbCheckoutService().create_checkout(
        customer_email=email, customer_name="Test Buyer", lines=[BasketLine(SKU, 1)], idempotency_key=key
    )


def _paid_event(session_id: str, order: models.Order, event_id: str | None = None) -> dict:
    return {
        "id": event_id or f"evt_{next(_ids)}",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "payment_status": "paid",
                "amount_total": order.total_pence,
                "payment_intent": f"pi_{session_id}",
                "payment_method_types": ["card"],
                "metadata": {"order_number": order.order_number},
                "customer_details": {"name": "Test Buyer", "email": order.email, "phone": "+447700900000"},
                "collected_information": {
                    "shipping_details": {
                        "name": "Test Buyer",
                        "address": {"line1": "1 High St", "city": "Oldham", "postal_code": "OL1 1AA", "country": "GB"},
                    }
                },
            }
        },
    }


def test_checkout_reserves_stock_and_uses_database_prices(shop):
    start = _stock()
    result = _checkout()
    assert result["checkout_url"].startswith("https://checkout.stripe.com/")
    assert _stock() == start - 1
    order = _order(result["order_number"])
    assert order.status == "pending_payment"
    assert order.total_pence == order.subtotal_pence + order.shipping_pence
    assert order.shipping_pence == 399  # £20 item < £75 threshold
    assert order.reservations[0].status == "active"
    sent = shop["sessions"][0]
    assert sent["line_items"][0]["price_data"]["unit_amount"] == order.subtotal_pence
    assert sent["shipping_address_collection"] == {"allowed_countries": ["GB"]}
    assert sent["shipping_options"][0]["shipping_rate_data"]["fixed_amount"]["amount"] == 399
    assert "payment_method_types" not in sent  # dynamic: cards, Apple Pay, Google Pay, Link, PayPal
    assert sent["idempotency_key"] == f"druvo-checkout-{order.order_number}"


def test_last_item_cannot_be_sold_twice(shop):
    _set_stock(1)
    _checkout(email="first@example.com")
    with pytest.raises(OutOfStockError):
        _checkout(email="second@example.com")
    assert _stock() == 0


def test_double_click_returns_same_session(shop):
    _set_stock(1)
    first = _checkout(key="web-abc")
    second = _checkout(key="web-abc")
    assert first == second
    assert len(shop["sessions"]) == 1
    assert _stock() == 0


def test_paid_webhook_confirms_order_once_and_sends_emails(shop):
    start = _stock()
    result = _checkout()
    order = _order(result["order_number"])
    service = DbCheckoutService()
    event = _paid_event(result["session_id"], order)
    out = service.handle_event(event)
    assert out["status"] == "paid"
    paid = _order(result["order_number"])
    assert paid.status == "paid"
    assert paid.reservations[0].status == "consumed"
    assert paid.shipping_address["postal_code"] == "OL1 1AA"
    assert paid.confirmation_email_sent_at is not None and paid.shop_notification_sent_at is not None
    assert paid.payment_fee_pence == 56  # actual Stripe fee captured for profit reports
    assert _stock() == start - 1

    # Exact replay and a second event for the same session are both ignored.
    assert service.handle_event(event)["duplicate"] is True
    assert service.handle_event(_paid_event(result["session_id"], order))["duplicate"] is True
    assert _stock() == start - 1
    subjects = [e["json"]["subject"] for e in shop["emails"]]
    assert subjects.count(f"Order confirmed — {paid.order_number}") == 1
    confirmation = next(e for e in shop["emails"] if e["json"]["subject"].startswith("Order confirmed"))
    assert "14 days" in confirmation["json"]["text"]
    assert "£23.99" in confirmation["json"]["text"]
    assert confirmation["headers"]["Idempotency-Key"] == f"order-confirmation-{paid.order_number}"
    with session_scope() as s:
        assert s.scalar(select(models.OutboxEvent).where(models.OutboxEvent.topic == "order.paid")) is not None


def test_expired_checkout_returns_stock(shop):
    start = _stock()
    result = _checkout()
    out = DbCheckoutService().handle_event(
        {"id": "evt_exp", "type": "checkout.session.expired", "data": {"object": {"id": result["session_id"]}}}
    )
    assert out["status"] == "expired"
    assert _stock() == start
    assert _order(result["order_number"]).status == "expired"


def test_payment_after_expiry_reclaims_stock_or_flags_conflict(shop):
    _set_stock(1)
    service = DbCheckoutService()
    first = _checkout(email="a@example.com")
    service.handle_event({"id": "evt_e1", "type": "checkout.session.expired", "data": {"object": {"id": first["session_id"]}}})
    second = _checkout(email="b@example.com")  # takes the only unit
    order = _order(first["order_number"])
    service.handle_event(_paid_event(first["session_id"], order))
    late = _order(first["order_number"])
    assert late.status == "paid"
    assert "STOCK CONFLICT" in late.notes
    assert _stock() == 0
    assert second["order_number"] != first["order_number"]


def test_stripe_failure_releases_stock(shop, monkeypatch):
    start = _stock()

    def boom(**kwargs):
        raise stripe.error.APIConnectionError("down")

    monkeypatch.setattr(stripe.checkout.Session, "create", staticmethod(boom))
    with pytest.raises(RuntimeError):
        _checkout()
    assert _stock() == start


def test_abandoned_reservations_are_swept(shop):
    start = _stock()
    result = _checkout()
    with session_scope() as s:
        order = s.scalar(select(models.Order).where(models.Order.order_number == result["order_number"]))
        order.reservation_expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    assert DbCheckoutService().release_expired_reservations() == 1
    assert _stock() == start


def test_invalid_basket_rejected(shop):
    with pytest.raises(CheckoutError):
        DbCheckoutService().create_checkout(customer_email="bad", customer_name="", lines=[BasketLine(SKU, 1)])
    with pytest.raises(CheckoutError):
        DbCheckoutService().create_checkout(customer_email="a@b.co", customer_name="", lines=[BasketLine("NOPE", 1)])


def _paid_order(shop) -> str:
    result = _checkout()
    DbCheckoutService().handle_event(_paid_event(result["session_id"], _order(result["order_number"])))
    return result["order_number"]


def test_dispatch_sets_tracking_and_emails_customer(shop):
    number = _paid_order(shop)
    out = order_ops.mark_dispatched(number, carrier="Royal Mail", tracking_number="AB 1234 5678 9GB", actor="admin@druvo.uk")
    assert out["tracking_url"].endswith("AB123456789GB")
    order = _order(number)
    assert order.status == "shipped" and order.dispatch_email_sent_at is not None
    dispatch = [e for e in shop["emails"] if "on its way" in e["json"]["subject"]]
    assert len(dispatch) == 1 and "AB123456789GB" in dispatch[0]["json"]["text"]
    with pytest.raises(order_ops.OrderOpError):
        order_ops.mark_dispatched(number, carrier="Royal Mail", actor="admin@druvo.uk")


def test_full_refund_with_restock(shop):
    start = _stock()
    number = _paid_order(shop)
    out = order_ops.refund_order(number, reason="Returned within 14 days", restock=True, actor="admin@druvo.uk")
    order = _order(number)
    assert out["status"] == "refunded" and order.refunded_pence == order.total_pence
    assert _stock() == start
    assert shop["refunds"][0]["payment_intent"] == order.stripe_payment_intent_id
    assert any(e["json"]["subject"] == f"Refund for order {number}" for e in shop["emails"])
    with pytest.raises(order_ops.OrderOpError):
        order_ops.refund_order(number, actor="admin@druvo.uk")
    # The matching charge.refunded webhook doesn't double count.
    DbCheckoutService().handle_event(
        {
            "id": "evt_ref",
            "type": "charge.refunded",
            "data": {
                "object": {
                    "payment_intent": order.stripe_payment_intent_id,
                    "amount_refunded": order.total_pence,
                    "refunds": {"data": [{"id": out["refund_id"], "amount": order.total_pence, "status": "succeeded"}]},
                }
            },
        }
    )
    with session_scope() as s:
        assert len(s.scalars(select(models.Refund)).all()) == 1


def test_partial_refund_from_stripe_dashboard_is_mirrored(shop):
    number = _paid_order(shop)
    order = _order(number)
    DbCheckoutService().handle_event(
        {
            "id": "evt_dash",
            "type": "charge.refunded",
            "data": {
                "object": {
                    "payment_intent": order.stripe_payment_intent_id,
                    "amount_refunded": 500,
                    "refunds": {"data": [{"id": "re_dash", "amount": 500, "status": "succeeded"}]},
                }
            },
        }
    )
    updated = _order(number)
    assert updated.status == "partially_refunded" and updated.refunded_pence == 500


def test_api_endpoints(shop, monkeypatch):
    from app.main import app

    client = TestClient(app)
    page = client.get("/checkout")
    assert "Continue to secure payment" in page.text
    assert "Test mode" in page.text
    resp = client.post(
        "/api/checkout/payment-session",
        json={"customer_email": "api@example.com", "customer_name": "Api", "external_order_id": "web-1",
              "lines": [{"sku": SKU, "quantity": 1, "unit_price_gbp": 0.01}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    order = _order(body["order_number"])
    assert order.subtotal_pence > 1  # browser price ignored

    monkeypatch.setattr(stripe.Webhook, "construct_event", staticmethod(lambda p, s, k: _paid_event(body["session_id"], order)))
    hook = client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": "t=1,v1=x"})
    assert hook.status_code == 200 and hook.json()["status"] == "paid"
    success = client.get(f"/checkout/success?session_id={body['session_id']}")
    assert order.order_number in success.text

    def bad_sig(p, s, k):
        raise stripe.error.SignatureVerificationError("bad", s)

    monkeypatch.setattr(stripe.Webhook, "construct_event", staticmethod(bad_sig))
    assert client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": "x"}).status_code == 400

    _set_stock(0)
    sold = client.post(
        "/api/checkout/payment-session",
        json={"customer_email": "late@example.com", "external_order_id": "web-2", "lines": [{"sku": SKU, "quantity": 1, "unit_price_gbp": 20}]},
    )
    assert sold.status_code == 409


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"), reason="needs PostgreSQL")
def test_concurrent_buyers_cannot_oversell(shop):
    _set_stock(1)
    results: list[str] = []
    barrier = threading.Barrier(8)

    def buy(i: int) -> None:
        barrier.wait()
        try:
            _checkout(email=f"buyer{i}@example.com")
            results.append("ok")
        except OutOfStockError:
            results.append("sold_out")

    threads = [threading.Thread(target=buy, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count("ok") == 1
    assert results.count("sold_out") == 7
    assert _stock() == 0

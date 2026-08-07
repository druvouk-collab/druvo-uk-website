"""Stripe webhook and payment-session tests (test mode only)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app
from app.services.order_service import CheckoutLine, WebsiteOrderService
from app.services.stripe_service import StripeCheckoutService
from app.storage.checkout_store import get_pending, mark_status, save_pending


@pytest.fixture
def checkout_db(tmp_path, monkeypatch):
    db_path = tmp_path / "checkout.db"
    monkeypatch.setattr("app.storage.checkout_store.DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def stripe_env(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "druvo_api")
    monkeypatch.setenv("DRUVO_API_BASE_URL", "http://127.0.0.1:8790")
    monkeypatch.setenv("DRUVO_API_KEY", "d" * 43)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_fake")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_fake")
    monkeypatch.setenv("SITE_URL", "http://test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _pending_lines():
    return [{"sku": "DRUVO-2-NAVY-M", "quantity": 1, "unit_price_gbp": 40.0, "variant_id": 1}]


def _completed_session(external_order_id: str, session_id: str = "cs_test_123") -> dict:
    return {
        "id": session_id,
        "payment_status": "paid",
        "payment_intent": "pi_test_456",
        "client_reference_id": external_order_id,
        "metadata": {"external_order_id": external_order_id},
    }


@pytest.mark.asyncio
async def test_payment_session_disabled_without_stripe(client):
    response = await client.post(
        "/api/checkout/payment-session",
        json={
            "customer_email": "buyer@example.com",
            "customer_name": "Test Buyer",
            "lines": [{"sku": "SKU-1", "quantity": 1, "unit_price_gbp": 10.0}],
        },
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_direct_orders_blocked_when_payments_enabled(client, stripe_env):
    response = await client.post(
        "/api/checkout/orders",
        json={
            "customer_email": "buyer@example.com",
            "customer_name": "Test Buyer",
            "lines": [{"sku": "SKU-1", "quantity": 1, "unit_price_gbp": 10.0}],
        },
    )
    assert response.status_code == 403
    assert "stripe" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_successful_webhook_creates_one_order(checkout_db, stripe_env):
    external_order_id = "web-stripe-success"
    save_pending(external_order_id, "buyer@druvo.uk", "Stripe Tester", _pending_lines(), stripe_session_id="cs_test_123")

    mock_orders = MagicMock(spec=WebsiteOrderService)
    mock_orders.submit_after_payment = AsyncMock(
        return_value={"order_id": 99, "external_order_id": external_order_id, "duplicate": False}
    )
    service = StripeCheckoutService(order_service=mock_orders)

    event = {"type": "checkout.session.completed", "data": {"object": _completed_session(external_order_id)}}
    with patch("app.services.stripe_service.stripe.Webhook.construct_event", return_value=event):
        result = await service.handle_webhook(b"{}", "sig")

    assert result["handled"] is True
    assert result["duplicate"] is False
    assert mock_orders.submit_after_payment.await_count == 1
    assert get_pending(external_order_id).status == "paid"


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_resubmit_order(checkout_db, stripe_env):
    external_order_id = "web-stripe-dup"
    save_pending(external_order_id, "buyer@druvo.uk", "Stripe Tester", _pending_lines(), stripe_session_id="cs_test_dup")
    mark_status(external_order_id, "paid")

    mock_orders = MagicMock(spec=WebsiteOrderService)
    mock_orders.get_by_external_id = AsyncMock(return_value={"order_id": 99, "external_order_id": external_order_id})
    mock_orders.submit_after_payment = AsyncMock()
    service = StripeCheckoutService(order_service=mock_orders)

    event = {"type": "checkout.session.completed", "data": {"object": _completed_session(external_order_id, "cs_test_dup")}}
    with patch("app.services.stripe_service.stripe.Webhook.construct_event", return_value=event):
        result = await service.handle_webhook(b"{}", "sig")

    assert result["handled"] is True
    assert result["duplicate"] is True
    mock_orders.submit_after_payment.assert_not_awaited()


@pytest.mark.asyncio
async def test_unpaid_session_does_not_create_order(checkout_db, stripe_env):
    external_order_id = "web-stripe-unpaid"
    save_pending(external_order_id, "buyer@druvo.uk", "Stripe Tester", _pending_lines())

    mock_orders = MagicMock(spec=WebsiteOrderService)
    mock_orders.submit_after_payment = AsyncMock()
    service = StripeCheckoutService(order_service=mock_orders)

    session = _completed_session(external_order_id)
    session["payment_status"] = "unpaid"
    event = {"type": "checkout.session.completed", "data": {"object": session}}
    with patch("app.services.stripe_service.stripe.Webhook.construct_event", return_value=event):
        result = await service.handle_webhook(b"{}", "sig")

    assert result["handled"] is False
    mock_orders.submit_after_payment.assert_not_awaited()
    assert get_pending(external_order_id).status == "pending"


@pytest.mark.asyncio
async def test_expired_session_marks_checkout_expired(checkout_db, stripe_env):
    external_order_id = "web-stripe-expired"
    save_pending(external_order_id, "buyer@druvo.uk", "Stripe Tester", _pending_lines(), stripe_session_id="cs_expired")

    mock_orders = MagicMock(spec=WebsiteOrderService)
    service = StripeCheckoutService(order_service=mock_orders)
    event = {
        "type": "checkout.session.expired",
        "data": {"object": _completed_session(external_order_id, "cs_expired")},
    }
    with patch("app.services.stripe_service.stripe.Webhook.construct_event", return_value=event):
        result = await service.handle_webhook(b"{}", "sig")

    assert result["handled"] is True
    assert get_pending(external_order_id).status == "expired"


@pytest.mark.asyncio
async def test_invalid_webhook_signature_rejected(client, stripe_env):
    import stripe

    with patch(
        "app.services.stripe_service.stripe.Webhook.construct_event",
        side_effect=stripe.error.SignatureVerificationError("bad sig", "sig"),
    ):
        response = await client.post(
            "/api/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "bad"},
        )
    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_success_page_shows_paid_order(client, stripe_env):
    mock_service = MagicMock()
    mock_service.get_success_context = AsyncMock(
        return_value={
            "session_id": "cs_test_show",
            "payment_status": "paid",
            "external_order_id": "web-show-1",
            "customer_email": "buyer@druvo.uk",
            "paid": True,
            "order": {"order_id": 42, "external_order_id": "web-show-1", "status": "received"},
        }
    )
    with patch("app.services.stripe_service.StripeCheckoutService", return_value=mock_service):
        response = await client.get("/checkout/success?session_id=cs_test_show")
    assert response.status_code == 200
    assert "Payment successful" in response.text
    assert "#42" in response.text or "web-show-1" in response.text


@pytest.mark.asyncio
async def test_cancel_page_shows_no_order_message(client):
    response = await client.get("/checkout/cancel?external_order_id=web-cancel-1")
    assert response.status_code == 200
    assert "cancelled" in response.text.lower()
    assert "No order was created" in response.text


@pytest.mark.asyncio
async def test_create_payment_session_redirect_url(checkout_db, stripe_env):
    mock_orders = MagicMock(spec=WebsiteOrderService)
    mock_orders.validate_stock = AsyncMock(return_value={"ok": True, "lines": []})
    service = StripeCheckoutService(order_service=mock_orders)

    fake_session = MagicMock()
    fake_session.id = "cs_test_new"
    fake_session.url = "https://checkout.stripe.com/c/pay/cs_test_new"

    with patch("app.services.stripe_service.stripe.checkout.Session.create", return_value=fake_session):
        result = await service.create_checkout_session(
            customer_email="buyer@druvo.uk",
            customer_name="Stripe Tester",
            lines=[CheckoutLine(sku="DRUVO-2-NAVY-M", quantity=1, unit_price_gbp=40.0, variant_id=1)],
        )

    assert result["checkout_url"].startswith("https://checkout.stripe.com/")
    pending = get_pending(result["external_order_id"])
    assert pending is not None
    assert pending.stripe_session_id == "cs_test_new"

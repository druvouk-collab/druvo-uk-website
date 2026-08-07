"""Stripe webhook and payment-session tests (test mode only)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app
from app.lib.druvo_api.errors import CatalogApiError
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
async def test_webhook_route_exists_not_404(client, stripe_env):
    response = await client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": "bad"})
    assert response.status_code != 404


@pytest.mark.asyncio
async def test_invalid_webhook_signature_rejected(client, stripe_env):
    import stripe

    with patch(
        "app.services.stripe_service.stripe.Webhook.construct_event",
        side_effect=stripe.error.SignatureVerificationError("bad sig", "sig"),
    ):
        response = await client.post(
            "/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "bad"},
        )
    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_valid_checkout_session_completed_accepted(client, checkout_db, stripe_env):
    external_order_id = "web-stripe-http"
    save_pending(external_order_id, "buyer@druvo.uk", "Stripe Tester", _pending_lines(), stripe_session_id="cs_http")

    event = {"type": "checkout.session.completed", "data": {"object": _completed_session(external_order_id, "cs_http")}}
    with patch("app.services.stripe_service.stripe.Webhook.construct_event", return_value=event), patch(
        "app.services.stripe_service.WebsiteOrderService.submit_after_payment",
        new=AsyncMock(return_value={"order_id": 77, "external_order_id": external_order_id, "duplicate": False}),
    ):
        response = await client.post(
            "/webhooks/stripe",
            content=b'{"id":"evt_test"}',
            headers={"stripe-signature": "sig_test"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["handled"] is True
    assert payload["duplicate"] is False


@pytest.mark.asyncio
async def test_duplicate_webhook_http_does_not_resubmit(client, checkout_db, stripe_env):
    external_order_id = "web-stripe-http-dup"
    save_pending(external_order_id, "buyer@druvo.uk", "Stripe Tester", _pending_lines(), stripe_session_id="cs_http_dup")
    mark_status(external_order_id, "paid")

    event = {"type": "checkout.session.completed", "data": {"object": _completed_session(external_order_id, "cs_http_dup")}}
    submit_mock = AsyncMock()
    with patch("app.services.stripe_service.stripe.Webhook.construct_event", return_value=event), patch(
        "app.services.stripe_service.WebsiteOrderService.submit_after_payment",
        new=submit_mock,
    ), patch(
        "app.services.stripe_service.WebsiteOrderService.get_by_external_id",
        new=AsyncMock(return_value={"order_id": 88, "external_order_id": external_order_id}),
    ):
        response = await client.post(
            "/webhooks/stripe",
            content=b'{"id":"evt_test_dup"}',
            headers={"stripe-signature": "sig_test"},
        )
    assert response.status_code == 200
    assert response.json()["duplicate"] is True
    submit_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_api_webhook_path_returns_404(client, stripe_env):
    response = await client.post("/api/webhooks/stripe", content=b"{}", headers={"stripe-signature": "bad"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_production_checkout_urls_use_render_host(checkout_db, stripe_env, monkeypatch):
    monkeypatch.setenv("SITE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://druvo-uk-website.onrender.com")
    get_settings.cache_clear()

    mock_orders = MagicMock(spec=WebsiteOrderService)
    mock_orders.validate_stock = AsyncMock(return_value={"ok": True, "lines": []})
    service = StripeCheckoutService(order_service=mock_orders)

    fake_session = MagicMock()
    fake_session.id = "cs_prod"
    fake_session.url = "https://checkout.stripe.com/c/pay/cs_prod"
    captured: dict = {}

    def _capture_create(**kwargs):
        captured.update(kwargs)
        return fake_session

    with patch("app.services.stripe_service.stripe.checkout.Session.create", side_effect=_capture_create):
        await service.create_checkout_session(
            customer_email="buyer@druvo.uk",
            customer_name="Stripe Tester",
            lines=[CheckoutLine(sku="DRUVO-2-NAVY-M", quantity=1, unit_price_gbp=40.0, variant_id=1)],
        )

    assert captured["success_url"].startswith("https://druvo-uk-website.onrender.com/checkout/success")
    assert captured["cancel_url"].startswith("https://druvo-uk-website.onrender.com/checkout/cancel")
    assert "127.0.0.1" not in captured["success_url"]
    assert "127.0.0.1" not in captured["cancel_url"]
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_webhook_fulfills_from_stripe_metadata_when_pending_missing(stripe_env):
    external_order_id = "web-meta-fallback"
    lines = _pending_lines()
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                **_completed_session(external_order_id, "cs_meta"),
                "metadata": {
                    "external_order_id": external_order_id,
                    "customer_email": "buyer@druvo.uk",
                    "customer_name": "Stripe Tester",
                    "lines_json": json.dumps(lines, separators=(",", ":")),
                },
            }
        },
    }
    mock_orders = MagicMock(spec=WebsiteOrderService)
    mock_orders.submit_after_payment = AsyncMock(
        return_value={"order_id": 55, "external_order_id": external_order_id, "duplicate": False}
    )
    service = StripeCheckoutService(order_service=mock_orders)
    with patch("app.services.stripe_service.stripe.Webhook.construct_event", return_value=event):
        result = await service.handle_webhook(b"{}", "sig")
    assert result["handled"] is True
    assert mock_orders.submit_after_payment.await_count == 1


@pytest.mark.asyncio
async def test_druvo_rejection_returns_clear_503_not_generic(client, checkout_db, stripe_env):
    external_order_id = "web-druvo-fail"
    save_pending(external_order_id, "buyer@druvo.uk", "Stripe Tester", _pending_lines())
    event = {"type": "checkout.session.completed", "data": {"object": _completed_session(external_order_id)}}
    with patch("app.services.stripe_service.stripe.Webhook.construct_event", return_value=event), patch(
        "app.routes.stripe_webhook.stripe_checkout._orders.submit_after_payment",
        new=AsyncMock(side_effect=CatalogApiError("reject", cause="http_500")),
    ):
        response = await client.post(
            "/webhooks/stripe",
            content=b'{"id":"evt_fail"}',
            headers={"stripe-signature": "sig_test"},
        )
    assert response.status_code == 503
    assert response.json()["detail"] == "DRUVO master order system could not accept the paid order."
    assert "Service temporarily unavailable" not in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_payment_session_stores_metadata_backup(checkout_db, stripe_env):
    mock_orders = MagicMock(spec=WebsiteOrderService)
    mock_orders.validate_stock = AsyncMock(return_value={"ok": True, "lines": []})
    service = StripeCheckoutService(order_service=mock_orders)
    fake_session = MagicMock(id="cs_meta2", url="https://checkout.stripe.com/c/pay/cs_meta2")
    captured: dict = {}

    def _capture_create(**kwargs):
        captured.update(kwargs)
        return fake_session

    with patch("app.services.stripe_service.stripe.checkout.Session.create", side_effect=_capture_create):
        await service.create_checkout_session(
            customer_email="buyer@druvo.uk",
            customer_name="Stripe Tester",
            lines=[CheckoutLine(sku="DRUVO-2-NAVY-M", quantity=1, unit_price_gbp=40.0, variant_id=1)],
        )

    metadata = captured["metadata"]
    assert metadata["customer_email"] == "buyer@druvo.uk"
    assert "lines_json" in metadata
    assert "DRUVO-2-NAVY-M" in metadata["lines_json"]


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

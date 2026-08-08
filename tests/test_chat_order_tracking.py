"""DRUVO Chat order tracking flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.account_order_service import AccountOrderService
from app.services.chat_order_tracking_service import (
    EMAIL_VERIFY_PROMPT,
    ORDER_REF_PROMPT,
    ChatOrderTrackingService,
)
from app.services.chat_rate_limit import get_chat_rate_limiter
from app.types.commerce import Order, OrderLine


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    get_chat_rate_limiter().reset()
    yield
    get_chat_rate_limiter().reset()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def live_account_env(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "druvo_api")
    monkeypatch.setenv("DRUVO_API_BASE_URL", "http://127.0.0.1:8790")
    monkeypatch.setenv("DRUVO_API_KEY", "d" * 43)
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _sample_order(**extra) -> Order:
    defaults = {
        "id": "web-40ea9feb6981478a",
        "placed_at": "2026-08-07 21:30:00",
        "status": "Processing",
        "tracking_number": None,
        "carrier": None,
        "lines": [
            OrderLine(
                product_slug="DRUVO-0001-L-CREAM",
                product_name="Cream Tracksuit",
                sku="DRUVO-0001-L-CREAM",
                size="L",
                colour="Cream",
                quantity=1,
                unit_price_gbp=20.0,
            )
        ],
        "subtotal_gbp": 20.0,
        "shipping_gbp": 3.99,
        "total_gbp": 23.99,
        "status_code": "processing",
    }
    defaults.update(extra)
    return Order(**defaults)


@pytest.mark.asyncio
async def test_track_my_order_starts_lookup_flow(client, live_account_env):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Track my order", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert ORDER_REF_PROMPT.split(".")[0] in reply
    assert "Standard UK delivery" not in reply
    assert "2–4 working days" not in reply


@pytest.mark.asyncio
async def test_valid_order_lookup_after_verification(client, live_account_env):
    fake_orders = AsyncMock()
    fake_orders.get_order = AsyncMock(return_value=_sample_order())
    history = [
        {"role": "user", "content": "Track my order"},
        {"role": "assistant", "content": ORDER_REF_PROMPT},
        {"role": "user", "content": "web-40ea9feb6981478a"},
        {"role": "assistant", "content": EMAIL_VERIFY_PROMPT},
    ]
    with patch.object(AccountOrderService, "get_order", fake_orders.get_order):
        response = await client.post(
            "/api/chat/message",
            json={
                "message": "test@example.com",
                "history": history,
                "locale": "en-GB",
            },
        )
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "web-40ea9feb6981478a" in reply
    assert "Preparing" in reply
    assert "£23.99" in reply
    assert "Cream Tracksuit" in reply
    fake_orders.get_order.assert_awaited_once_with("web-40ea9feb6981478a", "test@example.com")


@pytest.mark.asyncio
async def test_invalid_order_reference(client, live_account_env):
    history = [
        {"role": "user", "content": "Track my order"},
        {"role": "assistant", "content": ORDER_REF_PROMPT},
    ]
    response = await client.post(
        "/api/chat/message",
        json={"message": "???", "history": history},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "valid order reference" in reply


@pytest.mark.asyncio
async def test_verification_failure_wrong_email(client, live_account_env):
    fake_orders = AsyncMock()
    fake_orders.get_order = AsyncMock(return_value=None)
    history = [
        {"role": "user", "content": "Track my order"},
        {"role": "assistant", "content": ORDER_REF_PROMPT},
        {"role": "user", "content": "web-40ea9feb6981478a"},
        {"role": "assistant", "content": EMAIL_VERIFY_PROMPT},
    ]
    with patch.object(AccountOrderService, "get_order", fake_orders.get_order):
        response = await client.post(
            "/api/chat/message",
            json={"message": "wrong@example.com", "history": history},
        )
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "couldn't find an order" in reply.lower()
    assert "test@example.com" not in reply
    assert "Cream Tracksuit" not in reply


@pytest.mark.asyncio
async def test_privacy_same_message_for_missing_order_and_wrong_email(client, live_account_env):
    fake_orders = AsyncMock()
    fake_orders.get_order = AsyncMock(return_value=None)
    history_missing = [
        {"role": "user", "content": "Track my order"},
        {"role": "assistant", "content": ORDER_REF_PROMPT},
        {"role": "user", "content": "web-does-not-exist"},
        {"role": "assistant", "content": EMAIL_VERIFY_PROMPT},
    ]
    history_wrong = [
        {"role": "user", "content": "Track my order"},
        {"role": "assistant", "content": ORDER_REF_PROMPT},
        {"role": "user", "content": "web-40ea9feb6981478a"},
        {"role": "assistant", "content": EMAIL_VERIFY_PROMPT},
    ]
    with patch.object(AccountOrderService, "get_order", fake_orders.get_order):
        missing = await client.post(
            "/api/chat/message",
            json={"message": "shopper@example.com", "history": history_missing},
        )
        wrong = await client.post(
            "/api/chat/message",
            json={"message": "shopper@example.com", "history": history_wrong},
        )
    assert missing.json()["reply"] == wrong.json()["reply"]


@pytest.mark.asyncio
async def test_missing_tracking_not_invented_for_processing_order(client, live_account_env):
    fake_orders = AsyncMock()
    fake_orders.get_order = AsyncMock(return_value=_sample_order(status="Processing", status_code="processing"))
    history = [
        {"role": "user", "content": "Track my order"},
        {"role": "assistant", "content": ORDER_REF_PROMPT},
        {"role": "user", "content": "web-40ea9feb6981478a"},
        {"role": "assistant", "content": EMAIL_VERIFY_PROMPT},
    ]
    with patch.object(AccountOrderService, "get_order", fake_orders.get_order):
        response = await client.post(
            "/api/chat/message",
            json={"message": "test@example.com", "history": history},
        )
    reply = response.json()["reply"]
    assert "RM" not in reply
    assert "Tracking:" not in reply
    assert "dispatched with tracking" in reply.lower()


@pytest.mark.asyncio
async def test_shipped_order_includes_tracking_when_available(client, live_account_env):
    fake_orders = AsyncMock()
    fake_orders.get_order = AsyncMock(
        return_value=_sample_order(
            status="Shipped",
            status_code="shipped",
            tracking_number="RM123456789GB",
            carrier="Royal Mail",
            shipped_at="2026-08-08 10:00:00",
        )
    )
    history = [
        {"role": "user", "content": "Where is my order?"},
        {"role": "assistant", "content": ORDER_REF_PROMPT},
        {"role": "user", "content": "web-40ea9feb6981478a"},
        {"role": "assistant", "content": EMAIL_VERIFY_PROMPT},
    ]
    with patch.object(AccountOrderService, "get_order", fake_orders.get_order):
        response = await client.post(
            "/api/chat/message",
            json={"message": "test@example.com", "history": history},
        )
    reply = response.json()["reply"]
    assert "Dispatched" in reply
    assert "RM123456789GB" in reply
    assert "Royal Mail" in reply
    assert "royalmail.com" in reply


@pytest.mark.asyncio
async def test_multilingual_order_tracking_presentation(live_account_env, monkeypatch):
    async def fake_translate(text, locale):
        return text.replace("Preparing", "تیاری")

    service = ChatOrderTrackingService()
    monkeypatch.setattr(service._presentation, "_translate", fake_translate)
    service._presentation._openai_api_key = "test-key"

    fake_get = AsyncMock(return_value=_sample_order())
    with patch.object(AccountOrderService, "get_order", fake_get):
        result = await service.handle(
            "test@example.com",
            [
                type("H", (), {"role": "user", "content": "Track my order"})(),
                type("H", (), {"role": "assistant", "content": ORDER_REF_PROMPT})(),
                type("H", (), {"role": "user", "content": "web-40ea9feb6981478a"})(),
                type("H", (), {"role": "assistant", "content": EMAIL_VERIFY_PROMPT})(),
            ],
            "ur-PK",
        )
    assert result is not None
    assert "تیاری" in result.reply
    assert "£23.99" in result.reply


@pytest.mark.asyncio
async def test_order_tracking_does_not_leak_email_in_api_response(client, live_account_env):
    fake_orders = AsyncMock()
    fake_orders.get_order = AsyncMock(return_value=_sample_order())
    history = [
        {"role": "user", "content": "Track my order"},
        {"role": "assistant", "content": ORDER_REF_PROMPT},
        {"role": "user", "content": "web-40ea9feb6981478a"},
        {"role": "assistant", "content": EMAIL_VERIFY_PROMPT},
    ]
    with patch.object(AccountOrderService, "get_order", fake_orders.get_order):
        response = await client.post(
            "/api/chat/message",
            json={"message": "test@example.com", "history": history},
        )
    payload = response.json()
    serialized = str(payload).lower()
    assert "test@example.com" not in serialized
    assert "openai" not in serialized
    assert "api_key" not in serialized

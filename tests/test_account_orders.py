"""Account order lookup tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.account_order_service import AccountOrderService


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


def _real_test_order(status: str = "processing", status_label: str = "Processing", **extra) -> dict:
    return {
        "order_id": 7,
        "external_order_id": "web-40ea9feb6981478a",
        "customer_email": "test@example.com",
        "status": status,
        "status_label": status_label,
        "created_at": "2026-08-07 21:30:00",
        "total_amount": 40.0,
        "lines": [
            {
                "sku": "DRUVO-2-NAVY-L",
                "product_name": "Adidas Tracksuit",
                "size": "L",
                "colour": "Navy",
                "quantity": 1,
                "unit_price_gbp": 40.0,
            }
        ],
        **extra,
    }


@pytest.mark.asyncio
async def test_account_dashboard_shows_no_mock_orders(client):
    response = await client.get("/account")
    assert response.status_code == 200
    assert "DRU-10042" not in response.text
    assert "DRU-10038" not in response.text
    assert 'name="email"' in response.text


@pytest.mark.asyncio
async def test_orders_page_shows_no_mock_orders(client):
    response = await client.get("/account/orders")
    assert response.status_code == 200
    assert "Order history" in response.text
    assert "DRU-10042" not in response.text
    assert "DRU-10038" not in response.text
    assert 'name="email"' in response.text


@pytest.mark.asyncio
async def test_orders_page_shows_email_lookup_form(client):
    response = await client.get("/account/orders")
    assert response.status_code == 200
    assert "Look up orders by checkout email" in response.text


@pytest.mark.asyncio
async def test_test_example_com_shows_real_processing_order(client, live_account_env):
    fake_client = AsyncMock()
    fake_client.list_orders_for_email = AsyncMock(return_value=[_real_test_order()])
    with patch.object(AccountOrderService, "_client", lambda self: fake_client):
        response = await client.get("/account/orders?email=test@example.com")
    assert response.status_code == 200
    assert "web-40ea9feb6981478a" in response.text
    assert "Processing" in response.text
    assert "Adidas Tracksuit" in response.text
    assert "Navy / L" in response.text
    assert "£40.00" in response.text
    assert "DRU-10042" not in response.text


@pytest.mark.asyncio
async def test_status_update_reflected_on_refresh(client, live_account_env):
    fake_client = AsyncMock()
    fake_client.list_orders_for_email = AsyncMock(
        side_effect=[
            [_real_test_order(status="processing", status_label="Processing")],
            [
                _real_test_order(
                    status="shipped",
                    status_label="Shipped",
                    tracking_number="RM123456789GB",
                    carrier="Royal Mail",
                )
            ],
        ]
    )
    with patch.object(AccountOrderService, "_client", lambda self: fake_client):
        first = await client.get("/account/orders?email=test@example.com")
        second = await client.get("/account/orders?email=test@example.com")
    assert "Processing" in first.text
    assert "Shipped" in second.text
    assert "RM123456789GB" not in first.text
    shipped = _real_test_order(
        status="shipped",
        status_label="Shipped",
        tracking_number="RM123456789GB",
        carrier="Royal Mail",
    )
    fake_client.get_order = AsyncMock(return_value=shipped)
    with patch.object(AccountOrderService, "_client", lambda self: fake_client):
        detail = await client.get(
            "/account/orders/web-40ea9feb6981478a?email=test@example.com"
        )
    assert "Royal Mail" in detail.text
    assert "RM123456789GB" in detail.text


@pytest.mark.asyncio
async def test_tracking_only_after_shipped_on_detail_page(client, live_account_env):
    processing = _real_test_order()
    shipped = _real_test_order(
        status="shipped",
        status_label="Shipped",
        tracking_number="RM123456789GB",
        carrier="Royal Mail",
    )
    fake_client = AsyncMock()
    fake_client.get_order = AsyncMock(side_effect=[processing, shipped])
    with patch.object(AccountOrderService, "_client", lambda self: fake_client):
        processing_resp = await client.get(
            "/account/orders/web-40ea9feb6981478a?email=test@example.com"
        )
        shipped_resp = await client.get(
            "/account/orders/web-40ea9feb6981478a?email=test@example.com"
        )
    assert processing_resp.status_code == 200
    assert "Processing" in processing_resp.text
    assert "RM123456789GB" not in processing_resp.text
    assert shipped_resp.status_code == 200
    assert "Shipped" in shipped_resp.text
    assert "RM123456789GB" in shipped_resp.text
    assert "Royal Mail" in shipped_resp.text


@pytest.mark.asyncio
async def test_order_detail_requires_email_lookup(client, live_account_env):
    response = await client.get("/account/orders/web-40ea9feb6981478a")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_catalog_image_proxy_not_configured(client):
    response = await client.get("/api/catalog/images/product_1/test.jpg")
    assert response.status_code == 404

"""Checkout API tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_checkout_orders_disabled_by_default(client):
    response = await client.post(
        "/api/checkout/orders",
        json={
            "customer_email": "buyer@example.com",
            "customer_name": "Test Buyer",
            "lines": [{"sku": "SKU-1", "quantity": 1, "unit_price_gbp": 10.0}],
        },
    )
    assert response.status_code == 503
    assert "druvo_api" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_checkout_validate_disabled(client):
    response = await client.post(
        "/api/checkout/validate",
        json={
            "customer_email": "buyer@example.com",
            "lines": [{"sku": "SKU-1", "quantity": 1, "unit_price_gbp": 10.0}],
        },
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_checkout_page_shows_structure(client):
    response = await client.get("/checkout")
    assert response.status_code == 200
    assert "Checkout" in response.text

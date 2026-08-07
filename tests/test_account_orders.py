"""Account order lookup tests."""

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
async def test_orders_page_mock_mode(client):
    response = await client.get("/account/orders")
    assert response.status_code == 200
    assert "Order history" in response.text
    assert "DRU-10042" in response.text


@pytest.mark.asyncio
async def test_orders_page_shows_email_lookup_form(client):
    response = await client.get("/account/orders")
    assert response.status_code == 200
    assert 'name="email"' in response.text


@pytest.mark.asyncio
async def test_catalog_image_proxy_not_configured(client):
    response = await client.get("/api/catalog/images/product_1/test.jpg")
    assert response.status_code == 404

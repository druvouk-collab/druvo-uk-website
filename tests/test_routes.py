"""Site tests."""

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
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_homepage(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "DRUVO UK" in response.text


@pytest.mark.asyncio
async def test_privacy_route(client):
    response = await client.get("/privacy")
    assert response.status_code == 200
    assert "Privacy Policy" in response.text
    assert "druvo.uk@gmail.com" in response.text
    assert "DRUVO AI Enterprise" in response.text


@pytest.mark.asyncio
async def test_product_detail(client):
    response = await client.get("/product/navy-wool-blazer")
    assert response.status_code == 200
    assert "Navy Wool Blazer" in response.text


@pytest.mark.asyncio
async def test_search(client):
    response = await client.get("/search", params={"q": "cashmere"})
    assert response.status_code == 200
    assert "Cashmere" in response.text


@pytest.mark.asyncio
async def test_sale_page(client):
    response = await client.get("/sale")
    assert response.status_code == 200
    assert "Sale" in response.text or "sale" in response.text.lower()


@pytest.mark.asyncio
async def test_www_redirects_to_canonical(client):
    response = await client.get("/shop", headers={"Host": "www.druvo.uk"}, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "https://druvo.uk/shop"

"""Storefront public catalogue — live-only surfaces and new arrivals."""

from __future__ import annotations

from dataclasses import replace

import pytest
from httpx import ASGITransport, AsyncClient

from app.data import mock_catalog
from app.main import app
from app.services.catalog_service import CatalogFilters, CatalogService
from app.services.catalog_snapshot import CatalogSnapshot
from app.services.catalog_visibility import is_live_catalog_product
from app.types.commerce import Product, ProductVariant


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _demo_product(**overrides) -> Product:
    defaults = {
        "id": "demo-1",
        "slug": "test-t-shirt",
        "name": "Test T-ShirT",
        "description": "Development sample",
        "category_slug": "mens-clothing",
        "category_name": "Men's Clothing",
        "brand": "Test",
        "condition": "Pre-loved",
        "images": ["/static/images/catalog/products/sample.jpg"],
        "variants": [ProductVariant("TEST-001", "M", "Black", 5, 15.0)],
        "tags": ["test"],
        "catalog_status": "demo",
    }
    defaults.update(overrides)
    return Product(**defaults)


def _live_product(**overrides) -> Product:
    base = mock_catalog.get_product("cream-tracksuit")
    assert base is not None
    return replace(base, **overrides)


@pytest.fixture
def mixed_catalog(monkeypatch):
    live = _live_product(is_new_arrival=True)
    demo = _demo_product()

    async def fake_load_snapshot(self, filters=None):
        filters = filters or CatalogFilters()
        snapshot_products = [live, demo]
        filtered = self._apply_filters(snapshot_products, filters)
        return CatalogSnapshot(
            products=filtered,
            categories=mock_catalog.all_categories(),
        )

    monkeypatch.setattr(CatalogService, "load_snapshot", fake_load_snapshot)


def test_catalog_service_public_only_excludes_demo():
    service = CatalogService()
    live = _live_product()
    demo = _demo_product()
    result = service._apply_filters([demo, live], CatalogFilters())
    assert result == [live]
    assert all(is_live_catalog_product(p) for p in result)


def test_new_arrivals_filter_excludes_demo_even_if_flagged():
    service = CatalogService()
    live = _live_product(is_new_arrival=True)
    demo = _demo_product(is_new_arrival=True)
    result = service._apply_filters(
        [demo, live],
        CatalogFilters(new_arrivals_only=True),
    )
    assert result == [live]


@pytest.mark.asyncio
async def test_homepage_excludes_demo_products(client, mixed_catalog):
    response = await client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Test T-ShirT" not in html
    assert "Cream Tracksuit" in html


@pytest.mark.asyncio
async def test_shop_excludes_demo_products(client, mixed_catalog):
    response = await client.get("/shop")
    assert response.status_code == 200
    assert "Test T-ShirT" not in response.text
    assert "Cream Tracksuit" in response.text


@pytest.mark.asyncio
async def test_search_excludes_demo_products(client, mixed_catalog):
    response = await client.get("/search", params={"q": "Test"})
    assert response.status_code == 200
    assert "Test T-ShirT" not in response.text


@pytest.mark.asyncio
async def test_new_arrivals_includes_live_product(client, mixed_catalog):
    response = await client.get("/new-arrivals")
    assert response.status_code == 200
    assert "Cream Tracksuit" in response.text
    assert "Test T-ShirT" not in response.text


@pytest.mark.asyncio
async def test_new_shortcut_redirects(client):
    response = await client.get("/new", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "/new-arrivals"


@pytest.mark.asyncio
async def test_sale_page_still_works(client):
    response = await client.get("/sale")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_faq_has_customer_facing_stock_wording(client):
    response = await client.get("/faq")
    assert response.status_code == 200
    text = response.text
    assert "live inventory system" in text
    assert "When connected to DRUVO AI Enterprise" not in text
    assert "quantities will sync from master inventory" not in text


@pytest.mark.asyncio
async def test_homepage_has_broader_fashion_copy(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "Curated fashion and lifestyle products" in response.text


@pytest.mark.asyncio
async def test_chat_excludes_demo_from_purchasable_results(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Show me Test T-ShirT", "history": []},
    )
    assert response.status_code == 200
    products = response.json().get("products") or []
    assert not products or all("test t-shir" not in p.get("name", "").lower() for p in products)

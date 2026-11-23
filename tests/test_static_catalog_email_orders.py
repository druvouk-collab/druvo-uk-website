"""Static catalogue (CATALOG_SOURCE=static) and email ordering."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.data import static_catalog
from app.main import app
from app.services.catalog_service import CatalogService
from app.templating import templates

SAMPLE = {
    "categories": [
        {"slug": "mens-clothing", "name": "Men's Clothing", "description": "Menswear", "image": ""}
    ],
    "products": [
        {
            "slug": "sample-tracksuit",
            "name": "Sample Tracksuit",
            "description": "Verified sample item.",
            "category_slug": "mens-clothing",
            "brand": "SAMPLE",
            "condition": "New",
            "images": ["/static/images/placeholder-product.svg"],
            "variants": [{"sku": "S-1", "size": "L", "colour": "Cream", "stock_quantity": 1, "price_gbp": 20}],
            "catalog_status": "live",
        },
        {
            "slug": "hidden-item",
            "name": "Hidden Item",
            "category_slug": "mens-clothing",
            "variants": [{"sku": "H-1", "size": "M", "colour": "Black", "stock_quantity": 1, "price_gbp": 10}],
            "catalog_status": "demo",
        },
        {"slug": "broken-item", "name": "Broken"},
    ],
}


@pytest.fixture
def static_mode(monkeypatch, tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(SAMPLE), encoding="utf-8")
    monkeypatch.setenv("CATALOG_SOURCE", "static")
    monkeypatch.setattr(static_catalog, "CATALOG_PATH", path)
    monkeypatch.setattr(static_catalog, "_cached", lambda: static_catalog.load_catalog(path))
    monkeypatch.setitem(templates.env.globals, "email_orders", True)
    from app.config import get_settings

    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def test_shipped_catalog_file_is_valid():
    categories, products = static_catalog.load_catalog()
    assert categories
    for product in products:
        assert product.variants, product.slug


def test_load_catalog_skips_invalid_entries(static_mode):
    categories, products = static_catalog.load_catalog(static_mode)
    assert [c.slug for c in categories] == ["mens-clothing"]
    assert [p.slug for p in products] == ["sample-tracksuit", "hidden-item"]
    assert products[0].category_name == "Men's Clothing"


@pytest.mark.asyncio
async def test_static_source_lists_only_live_products(static_mode):
    snapshot = await CatalogService().load_snapshot()
    assert not snapshot.degraded
    assert [p.slug for p in snapshot.products] == ["sample-tracksuit"]


@pytest.mark.asyncio
async def test_static_product_page_mentions_email_orders(static_mode, client):
    response = await client.get("/product/sample-tracksuit")
    assert response.status_code == 200
    assert "Sample Tracksuit" in response.text
    assert "We take orders by email" in response.text


@pytest.mark.asyncio
async def test_checkout_becomes_order_by_email(static_mode, client):
    response = await client.get("/checkout")
    assert response.status_code == 200
    body = response.text
    assert "Order by email" in body
    assert "No payment is taken on this website" in body
    assert "confirm stock, the delivery cost and how to pay" in body
    assert 'id="place-order"' not in body
    assert "Stripe" not in body


@pytest.mark.asyncio
async def test_shop_has_no_degraded_banner_in_static_mode(static_mode, client):
    response = await client.get("/shop")
    assert response.status_code == 200
    assert "temporarily unavailable" not in response.text
    assert "Sample Tracksuit" in response.text


@pytest.mark.asyncio
async def test_chat_payment_answer_in_email_mode(static_mode, client):
    response = await client.post("/api/chat/message", json={"message": "How do I pay?"})
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "email" in reply.lower()
    assert "Stripe" not in reply


@pytest.mark.asyncio
async def test_faq_and_delivery_describe_email_ordering(static_mode, client):
    faq = (await client.get("/faq")).text
    assert "How do I order?" in faq
    assert "live inventory system" not in faq
    delivery = (await client.get("/delivery")).text
    assert "account order history" not in delivery
    assert "tracking number" in delivery

"""Google Merchant Center feed tests."""

from __future__ import annotations

import json
from xml.etree import ElementTree

import pytest
from httpx import ASGITransport, AsyncClient

from app.data import mock_catalog
from app.main import app
from app.services.catalog_visibility import is_live_catalog_product, is_merchant_eligible
from app.services.merchant_service import (
    build_merchant_feed_items,
    merchant_availability,
    merchant_condition,
    merchant_feed_xml,
    merchant_price_gbp,
)
from app.services.seo_service import product_json_ld
from app.types.commerce import Product, ProductVariant


def _demo_product(**overrides) -> Product:
    defaults = {
        "id": "t1",
        "slug": "test001",
        "name": "Test T-ShirT",
        "description": "Test listing",
        "category_slug": "uncategorised",
        "category_name": "Uncategorised",
        "brand": "",
        "condition": "Pre-loved",
        "images": ["/static/images/catalog/products/real.jpg"],
        "variants": [ProductVariant("TEST001", "One Size", "Default", 1, 25.0)],
        "catalog_status": "demo",
    }
    defaults.update(overrides)
    return Product(**defaults)


def test_demo_catalog_status_excluded_from_merchant_feed():
    product = _demo_product()
    assert is_live_catalog_product(product) is False
    assert is_merchant_eligible(product) is False


def test_live_product_with_real_image_is_merchant_eligible():
    product = mock_catalog.get_product("navy-wool-blazer")
    assert product is not None
    assert is_live_catalog_product(product) is True
    assert is_merchant_eligible(product) is True


def test_placeholder_only_live_product_not_merchant_eligible():
    product = _demo_product(
        slug="sample-jacket",
        name="Sample Jacket",
        catalog_status="live",
        variants=[ProductVariant("JKT-001", "M", "Navy", 1, 40.0)],
        images=["/static/images/placeholder-product.svg"],
    )
    assert is_merchant_eligible(product) is False


def test_merchant_feed_item_fields_from_catalog():
    product = mock_catalog.get_product("navy-wool-blazer")
    assert product is not None
    items = build_merchant_feed_items([product])
    assert len(items) == 3
    first = items[0]
    assert first.id == "RB-NVY-38"
    assert first.link == "https://druvo.uk/product/navy-wool-blazer"
    assert first.price_gbp.endswith(" GBP")
    assert "onrender.com" not in first.link


def test_merchant_feed_xml_structure():
    product = mock_catalog.get_product("navy-wool-blazer")
    assert product is not None
    xml = merchant_feed_xml(build_merchant_feed_items([product]))
    root = ElementTree.fromstring(xml)
    ns = {"g": "http://base.google.com/ns/1.0"}
    items = root.findall(".//item")
    assert len(items) == 3


def test_feed_price_and_availability_match_structured_data():
    product = mock_catalog.get_product("navy-wool-blazer")
    assert product is not None
    feed_items = {item.id: item for item in build_merchant_feed_items([product])}
    schema = json.loads(product_json_ld(product))
    offers = schema["offers"]
    offer_list = offers["offers"] if offers["@type"] == "AggregateOffer" else [offers]
    for offer in offer_list:
        feed = feed_items[offer["sku"]]
        assert feed.price_gbp.split()[0] == offer["price"]


def test_demo_products_excluded_from_feed_xml():
    demo = _demo_product()
    live = mock_catalog.get_product("navy-wool-blazer")
    assert live is not None
    items = build_merchant_feed_items([demo, live])
    ids = {item.id for item in items}
    assert "TEST001" not in ids
    assert "RB-NVY-38" in ids


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_merchant_feed_endpoint(client):
    response = await client.get("/google-merchant-feed.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "onrender.com" not in response.text


@pytest.mark.asyncio
async def test_sitemap_excludes_demo_catalog_products(client):
    response = await client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "/product/navy-wool-blazer" in response.text


def test_merchant_condition_mapping():
    assert merchant_condition("New with tags") == "new"
    assert merchant_condition("Pre-loved") == "used"


def test_merchant_availability_mapping():
    assert merchant_availability(ProductVariant("X", "M", "Blue", 0, 10.0)) == "out_of_stock"
    assert merchant_availability(ProductVariant("Y", "M", "Blue", 2, 10.0)) == "in_stock"


def test_sale_price_used_when_on_sale():
    product = Product(
        id="p1",
        slug="sale-item",
        name="Sale Item",
        description="Reduced item",
        category_slug="footwear",
        category_name="Footwear",
        brand="Nike",
        condition="Very Good",
        images=["/static/images/catalog/products/shoe.jpg"],
        variants=[ProductVariant("S-8", "UK 8", "White", 1, 100.0)],
        catalog_status="live",
        is_on_sale=True,
        sale_price_gbp=75.0,
    )
    assert merchant_price_gbp(product.variants[0], product) == "75.00 GBP"

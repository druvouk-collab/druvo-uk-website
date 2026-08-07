"""Catalog asset and route coverage tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.data import mock_catalog
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/shop",
        "/new-arrivals",
        "/categories",
        "/categories/womens-clothing",
        "/sale",
        "/about",
        "/search",
        "/search?q=cashmere",
        "/product/navy-wool-blazer",
        "/product/merino-crew-jumper",
        "/product/silk-midi-dress",
        "/product/designer-wool-coat",
        "/cart",
        "/checkout",
        "/account",
        "/account/orders",
        "/faq",
        "/delivery",
        "/returns",
        "/contact",
        "/privacy",
        "/terms",
    ],
)
@pytest.mark.asyncio
async def test_public_routes_ok(client, path):
    response = await client.get(path)
    assert response.status_code == 200, path


def test_mock_catalog_uses_self_hosted_images():
    for category in mock_catalog.all_categories():
        assert category.image.startswith("/static/images/catalog/")
        assert (ROOT / category.image.lstrip("/")).is_file(), category.slug
    for product in mock_catalog.all_products():
        assert product.images[0].startswith("/static/images/catalog/")
        assert (ROOT / product.images[0].lstrip("/")).is_file(), product.slug


def test_placeholder_assets_exist():
    assert (STATIC / "images/placeholder-product.svg").is_file()
    assert (STATIC / "images/placeholder-category.svg").is_file()
    assert (STATIC / "images/catalog/hero/featured.jpg").is_file()


@pytest.mark.asyncio
async def test_static_catalog_image_served(client):
    response = await client.get("/static/images/catalog/categories/womens-clothing.jpg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


@pytest.mark.asyncio
async def test_homepage_uses_local_images_not_unsplash(client):
    response = await client.get("/")
    html = response.text
    assert "/static/images/catalog/" in html
    assert "images.unsplash.com" not in html

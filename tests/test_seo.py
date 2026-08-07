"""SEO — robots.txt, sitemap, canonical URLs, metadata, structured data."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.seo_service import (
    canonical_site_url,
    canonical_url_for,
    organization_json_ld,
    product_json_ld,
    website_json_ld,
)
from app.data import mock_catalog


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def test_canonical_never_onrender(monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://druvo-uk-website.onrender.com")
    from app.config import get_settings

    get_settings.cache_clear()
    assert canonical_site_url() == "https://druvo.uk"
    assert canonical_url_for("/shop") == "https://druvo.uk/shop"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_robots_txt(client):
    response = await client.get("/robots.txt")
    assert response.status_code == 200
    text = response.text
    assert "User-agent: *" in text
    assert "Allow: /" in text
    assert "Disallow: /account/" in text
    assert "Disallow: /cart" in text
    assert "Disallow: /checkout" in text
    assert "Disallow: /search" in text
    assert "Disallow: /admin/" in text
    assert "Disallow: /api/" in text
    assert "Disallow: /health" in text
    assert "Sitemap: https://druvo.uk/sitemap.xml" in text
    assert "onrender.com" not in text


@pytest.mark.asyncio
async def test_sitemap_xml(client):
    response = await client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    text = response.text
    assert "<urlset" in text
    assert "https://druvo.uk/" in text
    assert "https://druvo.uk/shop" in text
    assert "https://druvo.uk/categories" in text
    assert "/product/" in text
    assert "/account/" not in text
    assert "/cart" not in text
    assert "/search" not in text
    assert "onrender.com" not in text


@pytest.mark.asyncio
async def test_homepage_canonical_and_indexable(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert 'rel="canonical" href="https://druvo.uk/"' in response.text
    assert 'name="robots" content="index, follow"' in response.text
    assert 'application/ld+json' in response.text
    assert "Organization" in response.text
    assert "WebSite" in response.text
    assert "onrender.com" not in response.text


@pytest.mark.asyncio
async def test_shop_page_seo(client):
    response = await client.get("/shop")
    assert response.status_code == 200
    assert 'rel="canonical" href="https://druvo.uk/shop"' in response.text
    assert 'name="robots" content="index, follow"' in response.text
    assert "Browse the full DRUVO UK shop" in response.text


@pytest.mark.asyncio
async def test_categories_page_seo(client):
    response = await client.get("/categories")
    assert response.status_code == 200
    assert 'rel="canonical" href="https://druvo.uk/categories"' in response.text
    assert 'name="robots" content="index, follow"' in response.text
    assert "Browse DRUVO UK categories" in response.text


@pytest.mark.asyncio
async def test_product_page_seo(client):
    response = await client.get("/product/navy-wool-blazer")
    assert response.status_code == 200
    assert 'rel="canonical" href="https://druvo.uk/product/navy-wool-blazer"' in response.text
    assert 'name="description"' in response.text
    assert 'property="og:type" content="product"' in response.text
    assert '"@type": "Product"' in response.text
    assert "shop Navy Wool Blazer at DRUVO UK" in response.text


@pytest.mark.asyncio
async def test_cart_noindex(client):
    response = await client.get("/cart")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, nofollow"' in response.text


@pytest.mark.asyncio
async def test_checkout_noindex(client):
    response = await client.get("/checkout")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, nofollow"' in response.text


@pytest.mark.asyncio
async def test_account_noindex(client):
    response = await client.get("/account/login")
    assert response.status_code == 200
    assert 'name="robots" content="noindex, nofollow"' in response.text


@pytest.mark.asyncio
async def test_search_noindex(client):
    response = await client.get("/search", params={"q": "nike"})
    assert response.status_code == 200
    assert 'name="robots" content="noindex, nofollow"' in response.text


def test_google_site_verification_meta(monkeypatch):
    monkeypatch.setenv("GOOGLE_SITE_VERIFICATION", "abc123verification")
    from app.config import get_settings
    from app.template_helpers import google_site_verification_token

    get_settings.cache_clear()
    assert google_site_verification_token() == "abc123verification"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_google_site_verification_renders(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_SITE_VERIFICATION", "abc123verification")
    from app.config import get_settings

    get_settings.cache_clear()
    response = await client.get("/")
    assert 'name="google-site-verification" content="abc123verification"' in response.text
    get_settings.cache_clear()


def test_structured_data_json_valid():
    org = json.loads(organization_json_ld())
    site = json.loads(website_json_ld())
    product = mock_catalog.get_product("navy-wool-blazer")
    assert product is not None
    prod = json.loads(product_json_ld(product))

    assert org["@type"] == "Organization"
    assert org["url"] == "https://druvo.uk"
    assert site["@type"] == "WebSite"
    assert site["potentialAction"]["@type"] == "SearchAction"
    assert site["potentialAction"]["target"]["@type"] == "EntryPoint"
    assert prod["@type"] == "Product"
    assert prod["url"].startswith("https://druvo.uk/product/")
    assert prod["offers"]["@type"] in {"Offer", "AggregateOffer"}

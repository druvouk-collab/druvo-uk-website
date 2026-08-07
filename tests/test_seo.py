"""SEO — robots.txt, sitemap, canonical URLs, metadata."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.seo_service import canonical_site_url, canonical_url_for


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
    assert "Disallow: /account/" in text
    assert "Disallow: /cart" in text
    assert "Disallow: /checkout" in text
    assert "Disallow: /api/" in text
    assert "Sitemap: https://druvo.uk/sitemap.xml" in text


@pytest.mark.asyncio
async def test_sitemap_xml(client):
    response = await client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    text = response.text
    assert "<urlset" in text
    assert "https://druvo.uk/" in text
    assert "https://druvo.uk/shop" in text
    assert "/product/" in text
    assert "/account/" not in text
    assert "/cart" not in text


@pytest.mark.asyncio
async def test_homepage_canonical_and_indexable(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert 'rel="canonical" href="https://druvo.uk/"' in response.text
    assert 'name="robots" content="index, follow"' in response.text
    assert 'application/ld+json' in response.text
    assert "Organization" in response.text


@pytest.mark.asyncio
async def test_product_page_seo(client):
    response = await client.get("/product/navy-wool-blazer")
    assert response.status_code == 200
    assert 'rel="canonical" href="https://druvo.uk/product/navy-wool-blazer"' in response.text
    assert 'name="description"' in response.text
    assert 'property="og:type" content="product"' in response.text
    assert '"@type": "Product"' in response.text


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

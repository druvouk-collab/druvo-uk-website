"""Advertising readiness: pixels are off by default, consent-gated when set, and the catalogue feed works."""

import csv
import io

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _set(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from app.config import get_settings

    get_settings.cache_clear()


async def test_no_pixels_or_banner_by_default(client):
    html = (await client.get("/")).text
    assert "druvo-marketing-config" not in html
    assert "consent-banner" not in html
    assert "connect.facebook.net" not in html
    privacy = (await client.get("/privacy")).text
    assert "do not currently use advertising" in privacy


async def test_pixels_configured_show_banner_and_config_only(client, monkeypatch):
    _set(monkeypatch, META_PIXEL_ID="123456789012345", TIKTOK_PIXEL_ID="CABCDEF12345", SNAP_PIXEL_ID="")
    html = (await client.get("/")).text
    assert 'id="druvo-marketing-config"' in html
    assert '"meta": "123456789012345"' in html and '"tiktok": "CABCDEF12345"' in html
    assert '"snap"' not in html
    assert 'id="consent-banner"' in html and "Meta (Facebook, Instagram)" in html and "TikTok" in html
    # Third-party scripts are only injected by marketing.js after Accept — never in the HTML.
    assert "connect.facebook.net" not in html and "analytics.tiktok.com" not in html
    assert "Cookie settings" in html
    privacy = (await client.get("/privacy")).text
    assert 'id="cookies"' in privacy and "With your permission only" in privacy


async def test_malformed_pixel_id_is_ignored(client, monkeypatch):
    _set(monkeypatch, META_PIXEL_ID='"><script>alert(1)</script>')
    html = (await client.get("/")).text
    assert "druvo-marketing-config" not in html
    assert "alert(1)" not in html


async def test_social_catalog_csv(client):
    response = await client.get("/feeds/social-catalog.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows, "catalogue should list products"
    for row in rows:
        assert row["id"] and row["title"] and row["link"].startswith("http")
        assert row["availability"] in {"in stock", "out of stock", "preorder"}
        assert row["price"].endswith(" GBP")
        assert row["image_link"].startswith("http")

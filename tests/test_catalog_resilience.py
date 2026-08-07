"""Tests for resilient catalog loading."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_home_degrades_when_druvo_api_unreachable(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "druvo_api")
    monkeypatch.setenv("DRUVO_API_BASE_URL", "https://invalid-host.example.test")
    monkeypatch.setenv("DRUVO_API_KEY", "test-key-thirty-two-characters-long")
    from app.config import get_settings

    get_settings.cache_clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
    get_settings.cache_clear()
    assert response.status_code == 200
    assert "live catalog is temporarily unavailable" in response.text.lower()


@pytest.mark.asyncio
async def test_health_druvo_reports_configuration(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "druvo_api")
    monkeypatch.setenv("DRUVO_API_BASE_URL", "https://example.com")
    monkeypatch.setenv("DRUVO_API_KEY", "abc")
    from app.config import get_settings

    get_settings.cache_clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/druvo")
    get_settings.cache_clear()
    assert response.status_code == 200
    body = response.json()
    assert body["catalog_source"] == "druvo_api"
    assert body["api_base_url_set"] is True

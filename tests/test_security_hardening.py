"""Security headers, hidden API docs and protected configuration endpoint on the live site."""

import importlib

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def _restore_app(monkeypatch):
    yield
    monkeypatch.undo()
    from app.config import get_settings

    get_settings.cache_clear()
    import app.main as main_module

    importlib.reload(main_module)


async def _client(monkeypatch, production: bool, token: str = ""):
    monkeypatch.setenv("PRODUCTION_MODE", "true" if production else "false")
    monkeypatch.setenv("ADMIN_CHECKLIST_TOKEN", token)
    from app.config import get_settings

    get_settings.cache_clear()
    import app.main as main_module

    main_module = importlib.reload(main_module)
    return AsyncClient(transport=ASGITransport(app=main_module.app), base_url="https://test")


@pytest.mark.asyncio
async def test_security_headers_on_pages(monkeypatch):
    async with await _client(monkeypatch, production=True) as client:
        response = await client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "max-age=31536000" in response.headers["strict-transport-security"]


@pytest.mark.asyncio
async def test_api_docs_hidden_in_production(monkeypatch):
    async with await _client(monkeypatch, production=True) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404, path


@pytest.mark.asyncio
async def test_api_docs_available_in_development(monkeypatch):
    async with await _client(monkeypatch, production=False) as client:
        assert (await client.get("/docs")).status_code == 200


@pytest.mark.asyncio
async def test_config_endpoint_needs_owner_token_in_production(monkeypatch):
    async with await _client(monkeypatch, production=True, token="owner-secret-token") as client:
        assert (await client.get("/health/druvo")).status_code == 404
        assert (await client.get("/health/druvo?token=wrong")).status_code == 404
        assert (await client.get("/health/druvo?token=owner-secret-token")).status_code == 200
        # The plain uptime check stays public for Render and the site monitor.
        assert (await client.get("/health")).status_code == 200


@pytest.mark.asyncio
async def test_config_endpoint_closed_when_no_token_set(monkeypatch):
    async with await _client(monkeypatch, production=True, token="") as client:
        assert (await client.get("/health/druvo")).status_code == 404

"""Production readiness endpoint tests."""

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
async def test_readiness_endpoint_returns_checks(client):
    response = await client.get("/health/readiness")
    assert response.status_code in (200, 503)
    payload = response.json()
    assert "checks" in payload
    assert "stripe_mode" in payload
    names = {check["name"] for check in payload["checks"]}
    assert "stripe_test_mode" in names
    assert "email_smtp" in names


@pytest.mark.asyncio
async def test_admin_launch_checklist_requires_token(client):
    response = await client.get("/admin/launch-checklist")
    assert response.status_code == 403

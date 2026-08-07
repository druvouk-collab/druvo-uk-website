"""DRUVO Chat API tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.chat_rate_limit import get_chat_rate_limiter


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    get_chat_rate_limiter().reset()
    yield
    get_chat_rate_limiter().reset()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_chat_status(client):
    response = await client.get("/api/chat/status")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert "welcome" in data


@pytest.mark.asyncio
async def test_chat_delivery_question(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "How much is delivery?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "£" in reply or "delivery" in reply
    assert response.json()["source"] == "rules"


@pytest.mark.asyncio
async def test_chat_product_lookup(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Do you have cashmere?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "cashmere" in reply.lower() or "druvo.uk@gmail.com" in reply


@pytest.mark.asyncio
async def test_chat_order_refusal(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Where is my order DRU-12345?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "account" in reply or "email" in reply


@pytest.mark.asyncio
async def test_chat_widget_on_homepage(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "druvo-chat-root" in response.text
    assert "DRUVO Chat" in response.text


@pytest.mark.asyncio
async def test_chat_rate_limit(client, monkeypatch):
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_HOUR", "2")
    from app.config import get_settings

    get_settings.cache_clear()
    get_chat_rate_limiter(max_requests=2, window_seconds=3600).reset()
    for _ in range(2):
        r = await client.post("/api/chat/message", json={"message": "hello", "history": []})
        assert r.status_code == 200
    r = await client.post("/api/chat/message", json={"message": "hello again", "history": []})
    assert r.status_code == 429
    get_settings.cache_clear()

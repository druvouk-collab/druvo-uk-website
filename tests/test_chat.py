"""DRUVO Chat API tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.chat_rate_limit import get_chat_rate_limiter
from app.services.chat_service import ChatService, _conversational_reply


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


@pytest.mark.parametrize(
    "message,expected_fragment",
    [
        ("good evening", "Good evening"),
        ("Good Evening!", "Good evening"),
        ("good morning", "Good morning"),
        ("good afternoon", "Good afternoon"),
        ("hi", "Welcome to DRUVO UK"),
        ("Hello", "Welcome to DRUVO UK"),
        ("Hey there", "Welcome to DRUVO UK"),
        ("how are you?", "doing well"),
        ("thank you", "welcome"),
        ("thanks!", "welcome"),
        ("bye", "Goodbye"),
        ("goodbye", "Goodbye"),
        ("who are you", "DRUVO Chat"),
        ("what can you help me with", "product availability"),
    ],
)
def test_conversational_replies(message, expected_fragment):
    reply = _conversational_reply(message)
    assert reply is not None
    assert expected_fragment.lower() in reply.lower()
    assert "unable to confirm" not in reply.lower()
    assert "live systems" not in reply.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["good evening", "Hello", "how are you?", "thanks", "who are you?"],
)
async def test_chat_greetings_via_api(client, message):
    response = await client.post(
        "/api/chat/message",
        json={"message": message, "history": []},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "rules"
    reply = data["reply"].lower()
    assert "unable to confirm" not in reply
    assert "live systems" not in reply
    assert "live product catalogue is temporarily unavailable" not in reply


@pytest.mark.asyncio
async def test_chat_status(client):
    response = await client.get("/api/chat/status")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert "welcome" in data
    assert "locale" in data


@pytest.mark.asyncio
async def test_chat_english_unchanged_with_explicit_locale(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "good evening", "history": [], "locale": "en-GB"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "Good evening" in data["reply"]
    assert data["locale"] == "en-GB"
    assert data["rtl"] is False


@pytest.mark.asyncio
async def test_chat_delivery_preserves_gbp_with_locale(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "How much is delivery?", "history": [], "locale": "en-GB"},
    )
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "£" in reply


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


@pytest.fixture
def live_account_env(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "druvo_api")
    monkeypatch.setenv("DRUVO_API_BASE_URL", "http://127.0.0.1:8790")
    monkeypatch.setenv("DRUVO_API_KEY", "d" * 43)
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_order_tracking_starts_flow(client, live_account_env):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Where is my order DRU-12345?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "order number" in reply or "order reference" in reply


@pytest.mark.asyncio
async def test_chat_unknown_question_uses_soft_fallback(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "xyzzy plugh quantum flarn", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "unable to confirm" not in reply
    assert "live systems" not in reply
    assert "druvo.uk@gmail.com" in reply or "/shop" in reply


@pytest.mark.asyncio
async def test_chat_demo_product_note(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Tell me about the navy wool blazer", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "navy wool blazer" in reply or "blazer" in reply


@pytest.mark.asyncio
async def test_chat_widget_on_homepage(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "druvo-chat-root" in response.text
    assert "DRUVO Chat" in response.text


@pytest.mark.asyncio
async def test_chat_widget_closed_by_default(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert 'id="druvo-chat-panel" hidden' in response.text.replace("\n", " ") or 'id="druvo-chat-panel"  hidden' in response.text
    assert 'aria-expanded="false"' in response.text


@pytest.mark.asyncio
async def test_chat_mobile_css_hides_closed_panel(client):
    response = await client.get("/static/css/druvo.css")
    css = response.text
    assert ".druvo-chat-panel[hidden]" in css
    assert "display: none !important" in css
    assert '.druvo-chat-panel:not([hidden])' in css
    assert ".druvo-chat-backdrop[hidden]" in css
    assert "left: auto" in css or "bottom: calc" in css


@pytest.mark.asyncio
async def test_homepage_static_assets_are_cache_busted(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "/static/css/druvo.css?v=" in response.text
    assert "/static/js/chat.js?v=" in response.text


@pytest.mark.asyncio
async def test_chat_mobile_styles_present(client):
    response = await client.get("/static/css/druvo.css")
    assert response.status_code == 200
    css = response.text
    assert ".druvo-chat-root" in css
    assert "@media" in css


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

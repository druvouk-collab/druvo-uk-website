"""Mobile DRUVO Chat drawer UI tests."""

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
async def test_chat_widget_has_backdrop_and_drawer_handle(client):
    response = await client.get("/")
    html = response.text
    assert 'id="druvo-chat-backdrop" hidden' in html.replace("\n", " ")
    assert "druvo-chat-drawer-handle" in html
    assert "Online shopping assistant" in html


@pytest.mark.asyncio
async def test_chat_panel_hidden_on_load(client):
    response = await client.get("/")
    html = response.text.replace("\n", " ")
    assert 'id="druvo-chat-panel" hidden' in html
    assert 'id="druvo-chat-backdrop" hidden' in html
    assert 'aria-expanded="false"' in html


@pytest.mark.asyncio
async def test_mobile_drawer_css_rules(client):
    response = await client.get("/static/css/druvo.css")
    css = response.text
    assert ".druvo-chat-panel[hidden]" in css
    assert "display: none !important" in css
    assert "78dvh" in css or "78vh" in css
    assert "translateY(100%)" in css
    assert "border-radius: 1.25rem 1.25rem 0 0" in css
    assert ".druvo-chat-backdrop[hidden]" in css
    assert "safe-area-inset-bottom" in css
    assert ".druvo-chat-root.druvo-chat-open .druvo-chat-launcher" in css
    assert ".druvo-chat-panel.druvo-chat-lang-open .druvo-chat-messages" in css
    assert ".druvo-chat-panel.druvo-chat-lang-open .druvo-chat-lang-screen" in css


@pytest.mark.asyncio
async def test_language_picker_markup(client):
    response = await client.get("/")
    html = response.text
    assert "druvo-chat-lang-screen" in html
    assert "Choose your language" in html
    assert "druvo-chat-lang-more" in html


@pytest.mark.asyncio
async def test_chat_languages_api(client):
    response = await client.get("/api/chat/languages")
    assert response.status_code == 200
    data = response.json()
    assert "quick" in data
    assert "languages" in data
    assert any(item["code"] == "en-GB" for item in data["languages"])


@pytest.mark.asyncio
async def test_chat_status_includes_locale_metadata(client):
    response = await client.get("/api/chat/status?locale=ur-PK")
    assert response.status_code == 200
    data = response.json()
    assert data["locale"] == "ur-PK"
    assert data["rtl"] is True

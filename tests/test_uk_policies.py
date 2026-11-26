"""UK consumer-law content on the policy pages (CCR 2013, CRA 2015, E-Commerce Regs 2002, UK GDPR)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_returns_page_states_legal_cancellation_terms(client):
    text = (await client.get("/returns")).text
    assert "14 days" in text and "within 14 days" in text
    assert "standard delivery charge" in text          # outbound delivery is refunded
    assert "Consumer Rights Act 2015" in text and "30 days" in text
    assert "Model cancellation form" in text
    assert "5–10 working days after we receive and inspect" not in text


async def test_no_express_delivery_offered_anywhere(client):
    for path in ("/delivery", "/shipping-returns", "/faq"):
        assert "£6.99" not in (await client.get(path)).text, path


async def test_delivery_page_has_cost_dispatch_and_lost_parcel_terms(client):
    text = (await client.get("/delivery")).text
    assert "£3.99" in text and "£75.00" in text and "1–2 working days" in text and "30 days" in text


async def test_privacy_lists_processors_rights_and_ico(client):
    text = (await client.get("/privacy")).text
    for word in ("Stripe", "Render", "OpenAI", "Information Commissioner", "6 years", 'id="cookies"'):
        assert word in text, word


async def test_business_identity_hidden_until_confirmed(client):
    text = (await client.get("/terms")).text
    assert "company number" not in text.lower() or "Company no." not in text


async def test_business_identity_shown_when_set(client, monkeypatch):
    monkeypatch.setenv("BUSINESS_LEGAL_NAME", "Example Shop Ltd")
    monkeypatch.setenv("COMPANY_NUMBER", "12345678")
    monkeypatch.setenv("BUSINESS_ADDRESS", "1 Example Street, Manchester, M1 1AA")
    from app.config import get_settings

    get_settings.cache_clear()
    for path in ("/terms", "/returns", "/privacy", "/"):
        text = (await client.get(path)).text
        assert "Example Shop Ltd" in text and "12345678" in text, path

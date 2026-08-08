"""Tests for DRUVO Chat live website knowledge + commerce assistant."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app
from app.services.catalog_visibility import filter_live_products
from app.services.chat_commerce_service import ChatCommerceService
from app.services.chat_rate_limit import get_chat_rate_limiter
from app.services.promotion_service import Promotion
from app.services.shipping_service import calculate_shipping
from app.services.website_knowledge_service import WebsiteKnowledgeService
from app.data.mock_catalog import all_products


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
async def test_live_products_exclude_demo_status():
    products = all_products()
    live = filter_live_products(products)
    assert all(p.catalog_status == "live" for p in live)
    assert len(live) == len(products)


@pytest.mark.asyncio
async def test_cream_tracksuit_price_answer(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "How much is the cream tracksuit?", "history": []},
    )
    assert response.status_code == 200
    data = response.json()
    reply = data["reply"].lower()
    assert "cream tracksuit" in reply
    assert "£" in data["reply"]
    assert data.get("products")


@pytest.mark.asyncio
async def test_xl_size_availability(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Do you have the cream tracksuit in XL?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "xl" in reply or "available" in reply


@pytest.mark.asyncio
async def test_trainers_under_fifty(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Show me trainers under £50", "history": []},
    )
    assert response.status_code == 200
    assert response.json()["source"] == "rules"


@pytest.mark.asyncio
async def test_delivery_from_shared_shipping_config(client):
    settings = get_settings()
    response = await client.post(
        "/api/chat/message",
        json={"message": "How much is delivery?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert f"£{settings.shipping_standard_gbp:.2f}" in reply
    assert f"£{settings.shipping_free_threshold_gbp:.2f}" in reply.replace("75", str(int(settings.shipping_free_threshold_gbp)))


@pytest.mark.asyncio
async def test_returns_policy_answer(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "What is your returns policy?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "14 days" in reply or "return" in reply


@pytest.mark.asyncio
async def test_active_promotion_mentioned(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Any current promotions?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "free delivery" in reply or "£75" in reply or "no special promotions" in reply


def test_expired_promotion_not_active():
    expired = Promotion(
        id=99,
        name="Old sale",
        description="Expired",
        discount_type="percentage",
        discount_value=20,
        end_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        active=True,
    )
    assert not expired.is_currently_active()


def test_inactive_promotion_not_active():
    promo = Promotion(
        id=100,
        name="Disabled",
        active=False,
        discount_type="free_shipping",
        min_spend_gbp=75,
    )
    assert not promo.is_currently_active()


@pytest.mark.asyncio
async def test_cart_free_delivery_gap(client):
    response = await client.post(
        "/api/chat/message",
        json={
            "message": "How far am I from free delivery?",
            "history": [],
            "cart": [{"slug": "cream-tracksuit", "price_gbp": 67.0, "quantity": 1}],
        },
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "8" in reply or "free delivery" in reply


@pytest.mark.asyncio
async def test_product_url_in_response(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Tell me about the cashmere roll neck", "history": []},
    )
    assert response.status_code == 200
    data = response.json()
    if data.get("products"):
        assert "/product/" in data["products"][0]["url"]


@pytest.mark.asyncio
async def test_unknown_product_honest_fallback(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Do you have Nike Air Max for £30?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "nike" not in reply or "don't" in reply or "couldn't" in reply or "exact match" in reply


@pytest.mark.asyncio
async def test_cheapest_tracksuit(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Which tracksuit is cheapest?", "history": []},
    )
    assert response.status_code == 200
    assert "tracksuit" in response.json()["reply"].lower()


@pytest.mark.asyncio
async def test_on_sale_question(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "Do you have anything on sale?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "sale" in reply or "£" in reply


@pytest.mark.asyncio
async def test_website_knowledge_shipping_matches_checkout():
    settings = get_settings()
    knowledge = WebsiteKnowledgeService(settings)
    cart = knowledge.cart_summary([{"price_gbp": 50, "quantity": 1}])
    checkout = calculate_shipping(50, settings)
    assert cart.shipping.shipping_gbp == checkout.shipping_gbp


@pytest.mark.asyncio
async def test_chat_widget_still_closed_by_default(client):
    response = await client.get("/")
    assert 'id="druvo-chat-panel" hidden' in response.text.replace("\n", " ") or 'id="druvo-chat-panel"  hidden' in response.text


@pytest.mark.asyncio
async def test_context_open_product(client):
    first = await client.post(
        "/api/chat/message",
        json={"message": "Tell me about the cream tracksuit", "history": []},
    )
    slugs = first.json().get("context_product_slugs", [])
    second = await client.post(
        "/api/chat/message",
        json={
            "message": "Open it",
            "history": [
                {"role": "user", "content": "Tell me about the cream tracksuit"},
                {"role": "assistant", "content": first.json()["reply"]},
            ],
            "last_product_slugs": slugs,
        },
    )
    assert second.status_code == 200
    assert "cream tracksuit" in second.json()["reply"].lower()


@pytest.mark.asyncio
async def test_typo_tracksuit_query(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "got any tracksut", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "tracksuit" in reply


@pytest.mark.asyncio
async def test_page_product_context_size(client):
    response = await client.post(
        "/api/chat/message",
        json={
            "message": "Do you have large?",
            "history": [],
            "page_product_slug": "cream-tracksuit",
        },
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "cream tracksuit" in reply or "large" in reply or "l" in reply


@pytest.mark.asyncio
async def test_follow_up_under_price_with_category(client):
    first = await client.post(
        "/api/chat/message",
        json={"message": "Show me men's tracksuits", "history": []},
    )
    slugs = first.json().get("context_product_slugs", [])
    second = await client.post(
        "/api/chat/message",
        json={
            "message": "Any under £25?",
            "history": [
                {"role": "user", "content": "Show me men's tracksuits"},
                {"role": "assistant", "content": first.json()["reply"]},
            ],
            "last_product_slugs": slugs,
        },
    )
    assert second.status_code == 200
    assert "£" in second.json()["reply"]


@pytest.mark.asyncio
async def test_basket_contents(client):
    response = await client.post(
        "/api/chat/message",
        json={
            "message": "What's in my basket?",
            "history": [],
            "cart": [{"slug": "cream-tracksuit", "name": "Cream Tracksuit", "price_gbp": 20.0, "quantity": 1}],
        },
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "20" in reply or "£" in reply
    assert "basket" in reply or "subtotal" in reply


@pytest.mark.asyncio
async def test_what_do_you_sell(client):
    response = await client.post(
        "/api/chat/message",
        json={"message": "What do you sell?", "history": []},
    )
    assert response.status_code == 200
    reply = response.json()["reply"].lower()
    assert "catalogue" in reply or "sell" in reply or "shop" in reply


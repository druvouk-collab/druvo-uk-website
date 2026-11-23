"""Shop-assistant answers in email-ordering mode (CATALOG_SOURCE=static)."""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.data import static_catalog
from app.main import app
from app.templating import templates

CATALOG = {
    "categories": [{"slug": "mens-clothing", "name": "Men's Clothing", "description": "", "image": ""}],
    "products": [
        {
            "slug": "cream-tracksuit-l",
            "name": "Men's Cream 2-Piece Sweatshirt & Jogger Tracksuit Set",
            "description": (
                "Brand new tracksuit set. Size UK 40 / Labelled L. Chest approx. 39.4–41.4 inches. "
                "Waist approx. 33.9–35.9 inches. Please check measurements before purchasing."
            ),
            "category_slug": "mens-clothing",
            "brand": "BALANCE",
            "condition": "New",
            "variants": [{"sku": "T-L", "size": "L", "colour": "Cream", "stock_quantity": 1, "price_gbp": 20}],
            "catalog_status": "live",
        }
    ],
}


@pytest.fixture(autouse=True)
def static_mode(monkeypatch, tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(CATALOG), encoding="utf-8")
    monkeypatch.setenv("CATALOG_SOURCE", "static")
    monkeypatch.setattr(static_catalog, "_cached", lambda: static_catalog.load_catalog(path))
    monkeypatch.setitem(templates.env.globals, "email_orders", True)
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def ask(client, message: str, **extra) -> dict:
    response = await client.post("/api/chat/message", json={"message": message, **extra})
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_plural_product_search_finds_item(client):
    data = await ask(client, "Do you have any tracksuits?")
    assert [p["slug"] for p in data["products"]] == ["cream-tracksuit-l"]
    assert "Order by email" in data["reply"]


@pytest.mark.asyncio
async def test_find_a_product_lists_stock(client):
    data = await ask(client, "What do you have in stock?")
    assert data["products"] and "in stock" in data["reply"].lower()


@pytest.mark.asyncio
async def test_how_to_order_steps(client):
    data = await ask(client, "How do I order?")
    reply = data["reply"]
    assert "Add to basket" in reply and "Order by email" in reply
    assert "druvo.uk@gmail.com" in reply
    assert "No payment is taken" in reply or "no payment is taken" in reply


@pytest.mark.asyncio
async def test_delivery_and_returns_combined(client):
    reply = (await ask(client, "Delivery and returns"))["reply"]
    assert "£3.99" in reply and "14 days" in reply


@pytest.mark.asyncio
async def test_measurements_from_description(client):
    reply = (await ask(client, "What are the measurements of the tracksuit?"))["reply"]
    assert "Chest approx. 39.4–41.4 inches." in reply
    assert "Waist approx. 33.9–35.9 inches." in reply


@pytest.mark.asyncio
async def test_missing_product_type_points_to_email(client):
    data = await ask(client, "Do you have any jackets?")
    assert "don't have any jackets" in data["reply"]
    assert "druvo.uk@gmail.com" in data["reply"]
    assert data["product_request"] is None


@pytest.mark.asyncio
async def test_sourcing_request_has_no_api_form(client):
    data = await ask(client, "Do you have Nike trainers size 9?")
    assert data["product_request"] is None
    assert "druvo.uk@gmail.com" in data["reply"]


@pytest.mark.asyncio
async def test_international_delivery_uses_published_policy(client):
    reply = (await ask(client, "Do you ship to Ireland?"))["reply"]
    assert "UK addresses only" in reply and "druvo.uk@gmail.com" in reply


@pytest.mark.asyncio
async def test_order_tracking_in_email_mode(client):
    reply = (await ask(client, "Where is my order?"))["reply"]
    assert "/account/orders" not in reply
    assert "druvo.uk@gmail.com" in reply


@pytest.mark.asyncio
async def test_unknown_question_says_so_and_gives_email(client):
    reply = (await ask(client, "asdfgh qwerty"))["reply"]
    assert reply.startswith("Sorry, I don't have the answer")
    assert "druvo.uk@gmail.com" in reply


@pytest.mark.asyncio
async def test_ambiguous_size_question_asks_which_item(client):
    reply = (await ask(client, "Do you have it in medium?"))["reply"]
    assert "Which item" in reply


@pytest.mark.asyncio
async def test_widget_has_quick_buttons(client):
    html = (await client.get("/")).text
    for label in ("Find a product", "Delivery &amp; returns", "How to order", "Contact us"):
        assert label in html


@pytest.mark.asyncio
async def test_unrelated_words_do_not_match_inside_other_words(client):
    data = await ask(client, "Can you knit me a scarf for my cat?")
    assert "don't have any scarves" in data["reply"]

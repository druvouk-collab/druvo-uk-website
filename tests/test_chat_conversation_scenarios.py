"""Parametrised conversation scenarios for DRUVO Chat tool layer (offline)."""

from __future__ import annotations

import pytest

from app.services.chat_tools import ChatToolExecutor
from app.services.website_knowledge_service import WebsiteKnowledgeSnapshot
from app.services.website_policies import build_website_policies
from app.types.commerce import Product, ProductVariant

SCENARIOS = [
    ("tracksuit cream large", "check_variant_stock", {"slug": "druvo-tracksuit-cream", "size": "L", "colour": "cream"}),
    ("tracksuit medium follow-up", "check_variant_stock", {"slug": "druvo-tracksuit-cream", "size": "M", "colour": "cream"}),
    ("delivery cost", "calculate_delivery", {"product_slug": "druvo-tracksuit-cream", "quantity": 1}),
    ("returns policy", "get_returns_policy", {}),
    ("delivery policy", "get_delivery_policy", {}),
    ("current offers", "get_current_offers", {}),
    ("payment info", "get_payment_information", {}),
    ("search tracksuit", "search_products", {"query": "tracksuit"}),
    ("cheaper options", "recommend_products", {"cheaper_than_gbp": 25}),
    ("business contact", "get_business_information", {"topic": "contact"}),
]


@pytest.fixture
def snapshot():
    product = Product(
        id="8",
        slug="druvo-tracksuit-cream",
        name="DRUVO Tracksuit Cream",
        description="Premium tracksuit",
        category_slug="tracksuits",
        category_name="Tracksuits",
        brand="DRUVO",
        condition="New",
        images=["/img.jpg"],
        variants=[
            ProductVariant(sku="DRUVO-0001-L-CREAM", size="L", colour="Cream", stock_quantity=1, price_gbp=20.0),
            ProductVariant(sku="DRUVO-0001-M-CREAM", size="M", colour="Cream", stock_quantity=0, price_gbp=20.0),
        ],
        catalog_status="live",
    )
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    return WebsiteKnowledgeSnapshot(
        products=[product],
        live_products=[product],
        categories=[],
        promotions=[],
        policies=build_website_policies(settings),
        shipping_standard_gbp=3.99,
        shipping_free_threshold_gbp=50.0,
        site_url="https://druvo.uk",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("label,tool,args", SCENARIOS)
async def test_conversation_tool_scenario(snapshot, label, tool, args):
    executor = ChatToolExecutor()
    result = await executor.execute(
        tool,
        args,
        snapshot=snapshot,
        last_slugs=["druvo-tracksuit-cream"],
    )
    assert result.ok, f"{label}: {result.error}"

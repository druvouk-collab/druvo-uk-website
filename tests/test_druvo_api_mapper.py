"""Tests for DRUVO AI API client mapping."""

from app.lib.druvo_api.mapper import map_order, map_product


def test_map_product_payload():
    product = map_product(
        {
            "id": "12",
            "slug": "trainer-001",
            "name": "Trainer",
            "description": "White trainers",
            "category_slug": "footwear",
            "category_name": "Footwear",
            "brand": "Common Projects",
            "condition": "Good",
            "images": ["https://example.com/trainer.jpg"],
            "variants": [
                {"sku": "TR-8", "size": "UK 8", "colour": "White", "stock_quantity": 2, "price_gbp": 80.0}
            ],
            "tags": ["Footwear"],
            "is_new_arrival": False,
            "is_on_sale": False,
            "sale_price_gbp": None,
        }
    )
    assert product.slug == "trainer-001"
    assert product.variants[0].size == "UK 8"
    assert product.in_stock is True


def test_map_order_payload():
    order = map_order(
        {
            "order_id": 42,
            "external_order_id": "web-abc123",
            "status": "confirmed",
            "created_at": "2026-08-07 12:00:00",
            "total_amount": 25.0,
            "lines": [{"sku": "HD-GRY-L", "quantity": 1, "unit_price": 25.0}],
        }
    )
    assert order.id == "web-abc123"
    assert order.total_gbp == 25.0
    assert order.lines[0].sku == "HD-GRY-L"

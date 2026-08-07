"""Tests for DRUVO AI API client mapping."""

from app.lib.druvo_api.mapper import map_product


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

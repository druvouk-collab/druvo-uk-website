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


def test_map_product_prefers_gallery_paths():
    product = map_product(
        {
            "id": "8",
            "slug": "druvo-0001-l-cream",
            "name": "Tracksuit",
            "description": "",
            "category_slug": "mens-tracksuits",
            "category_name": "Men's Tracksuits",
            "brand": "",
            "condition": "Pre-loved",
            "images": [
                "https://api.druvo.uk/api/v1/images/img_9.png",
                "https://api.druvo.uk/api/v1/images/img_10.png",
            ],
            "gallery": [
                {
                    "path": "product_8/img_9.png",
                    "url": "https://api.druvo.uk/api/v1/images/product_8/img_9.png",
                    "sort_order": 0,
                    "is_main": True,
                },
                {
                    "path": "product_8/img_11.jpg",
                    "url": "https://api.druvo.uk/api/v1/images/product_8/img_11.jpg",
                    "sort_order": 1,
                    "is_main": False,
                },
            ],
            "variants": [
                {
                    "sku": "DRUVO-001",
                    "size": "L",
                    "colour": "Cream",
                    "stock_quantity": 1,
                    "price_gbp": 20.0,
                }
            ],
            "tags": [],
            "is_new_arrival": False,
            "is_on_sale": False,
            "sale_price_gbp": None,
            "catalog_status": "live",
        }
    )
    assert product.images[0] == "/api/catalog/images/product_8/img_9.png"
    assert "/api/catalog/images/product_8/img_11.jpg" in product.images


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

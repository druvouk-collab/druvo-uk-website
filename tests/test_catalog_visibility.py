"""Catalog visibility — live vs demo product routing."""

from __future__ import annotations

from app.data import mock_catalog
from app.services.catalog_visibility import (
    filter_live_products,
    is_live_catalog_product,
    is_merchant_eligible,
    is_public_indexable_product,
)
from app.types.commerce import Product, ProductVariant


def _demo_product(**overrides) -> Product:
    defaults = {
        "id": "d1",
        "slug": "dev-sample",
        "name": "Dev Sample Hoodie",
        "description": "Development listing",
        "category_slug": "uncategorised",
        "category_name": "Uncategorised",
        "brand": "",
        "condition": "Pre-loved",
        "images": ["/static/images/catalog/products/sample.jpg"],
        "variants": [ProductVariant("DEV-001", "M", "Grey", 1, 30.0)],
        "catalog_status": "demo",
    }
    defaults.update(overrides)
    return Product(**defaults)


def test_mock_catalog_products_are_live_for_tests():
    products = mock_catalog.all_products()
    assert products
    assert all(is_live_catalog_product(p) for p in products)


def test_demo_status_excluded_from_public_surfaces():
    product = _demo_product()
    assert is_live_catalog_product(product) is False
    assert is_public_indexable_product(product) is False
    assert is_merchant_eligible(product) is False


def test_live_product_with_real_image_is_merchant_eligible():
    product = _demo_product(catalog_status="live")
    assert is_live_catalog_product(product) is True
    assert is_public_indexable_product(product) is True
    assert is_merchant_eligible(product) is True


def test_live_product_without_real_image_not_merchant_eligible():
    product = _demo_product(
        catalog_status="live",
        images=["/static/images/placeholder-product.svg"],
    )
    assert is_merchant_eligible(product) is False


def test_filter_live_products():
    live = mock_catalog.get_product("navy-wool-blazer")
    assert live is not None
    demo = _demo_product()
    result = filter_live_products([demo, live])
    assert result == [live]

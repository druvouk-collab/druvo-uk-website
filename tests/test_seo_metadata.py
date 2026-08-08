"""Unit tests for catalog-driven SEO metadata generation."""

from __future__ import annotations

from app.data import mock_catalog
from app.services.seo_metadata import (
    catalog_brands,
    home_meta_description,
    product_document_title,
    product_image_alt,
    product_meta_description,
)


def test_catalog_brands_only_from_real_data():
    products = mock_catalog.all_products()
    brands = catalog_brands(products)
    assert "Reiss" in brands
    assert "Nike" not in brands


def test_product_title_includes_real_brand():
    product = mock_catalog.get_product("navy-wool-blazer")
    assert product is not None
    title = product_document_title(product)
    assert "Reiss" in title
    assert "Navy Wool Blazer" in title


def test_product_meta_uses_description_not_invented_brand():
    product = mock_catalog.get_product("navy-wool-blazer")
    assert product is not None
    desc = product_meta_description(product)
    assert "Reiss" not in desc or "blazer" in desc.lower()
    assert "Shop online at DRUVO UK" in desc


def test_product_image_alt_descriptive():
    product = mock_catalog.get_product("navy-wool-blazer")
    assert product is not None
    alt = product_image_alt(product)
    assert "Navy Wool Blazer" in alt
    assert "Reiss" in alt


def test_home_meta_mentions_live_brands():
    products = mock_catalog.all_products()
    desc = home_meta_description(products)
    assert "Shop online at DRUVO UK" in desc
    assert "Reiss" in desc or "John Lewis" in desc

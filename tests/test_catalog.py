"""Catalog service tests."""

from __future__ import annotations

import pytest

from app.services.catalog_service import CatalogFilters, CatalogService


@pytest.mark.asyncio
async def test_list_products_default():
    service = CatalogService()
    products = await service.list_products()
    assert len(products) >= 4


@pytest.mark.asyncio
async def test_filter_on_sale():
    service = CatalogService()
    products = await service.list_products(CatalogFilters(on_sale_only=True))
    assert products
    assert all(p.is_on_sale for p in products)


@pytest.mark.asyncio
async def test_filter_in_stock():
    service = CatalogService()
    products = await service.list_products(CatalogFilters(in_stock_only=True))
    assert all(p.in_stock for p in products)


@pytest.mark.asyncio
async def test_get_product_by_slug():
    service = CatalogService()
    product = await service.get_product("navy-wool-blazer")
    assert product is not None
    assert product.slug == "navy-wool-blazer"
    assert product.sizes

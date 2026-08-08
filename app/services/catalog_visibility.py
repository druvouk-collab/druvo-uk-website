"""Catalog visibility — live vs demo/development products."""

from __future__ import annotations

import re

from app.types.commerce import Product

CATALOG_STATUS_LIVE = "live"
CATALOG_STATUS_DEMO = "demo"

_PLACEHOLDER_FRAGMENT = "placeholder-product"
_TEST_SLUG_RE = re.compile(r"^(test|demo)([-_]?(\d+|[a-z0-9]+))?$", re.I)


def is_live_catalog_product(product: Product) -> bool:
    """True when DRUVO AI marks the product as genuine live inventory."""
    status = (product.catalog_status or "").strip().lower()
    if status == CATALOG_STATUS_LIVE:
        return True
    if status == CATALOG_STATUS_DEMO:
        return False
    return not _legacy_demo_heuristic(product)


def is_public_indexable_product(product: Product) -> bool:
    """Products that may appear in sitemap, SEO indexing and Google surfaces."""
    return is_live_catalog_product(product)


def is_demo_catalog_product(product: Product) -> bool:
    return not is_live_catalog_product(product)


def has_real_product_image(product: Product) -> bool:
    return any(
        image
        and _PLACEHOLDER_FRAGMENT not in image
        and not image.endswith("placeholder-product.svg")
        for image in product.images
    )


def is_merchant_eligible(product: Product) -> bool:
    """Google Merchant feed — live products with real uploaded images only."""
    if not is_live_catalog_product(product):
        return False
    if not product.variants:
        return False
    return has_real_product_image(product)


def filter_live_products(products: list[Product]) -> list[Product]:
    return [product for product in products if is_live_catalog_product(product)]


def _legacy_demo_heuristic(product: Product) -> bool:
    """Fallback when catalog_status is missing from older API payloads."""
    slug = product.slug.strip().lower()
    if _TEST_SLUG_RE.match(slug):
        return True
    name = product.name.strip().lower()
    if name.startswith("test ") or name == "test" or "test product" in name:
        return True
    if name.startswith("demo ") or name == "demo":
        return True
    for variant in product.variants:
        sku = variant.sku.strip().upper()
        if sku.startswith("TEST") or sku.startswith("DEMO"):
            return True
    tags = {tag.strip().lower() for tag in product.tags if tag}
    return bool(tags & {"test", "demo", "sample"})

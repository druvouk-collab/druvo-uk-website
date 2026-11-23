"""Static catalogue — verified products kept in app/data/catalog.json.

Used when CATALOG_SOURCE=static so the storefront can run on free hosting
without the DRUVO AI API. Only products with "catalog_status": "live" are
shown publicly. Edit catalog.json and redeploy to add, update or remove stock.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from app.types.commerce import Category, Product, ProductVariant

logger = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"


def _load_raw(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Static catalogue file missing: %s", path)
    except json.JSONDecodeError as exc:
        logger.error("Static catalogue file is not valid JSON (%s): %s", path, exc)
    return {}


def _category(raw: dict) -> Category:
    return Category(
        slug=str(raw["slug"]),
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        image=str(raw.get("image") or "/static/images/placeholder-category.svg"),
    )


def _product(raw: dict, categories: dict[str, Category]) -> Product:
    category_slug = str(raw.get("category_slug", ""))
    category = categories.get(category_slug)
    variants = [
        ProductVariant(
            sku=str(v.get("sku", "")),
            size=str(v.get("size", "")),
            colour=str(v.get("colour", "")),
            stock_quantity=int(v.get("stock_quantity", 0)),
            price_gbp=float(v["price_gbp"]),
        )
        for v in raw.get("variants", [])
    ]
    if not variants:
        raise ValueError("product needs at least one variant with a price")
    images = [str(i) for i in raw.get("images", []) if i] or ["/static/images/placeholder-product.svg"]
    return Product(
        id=str(raw.get("id") or raw["slug"]),
        slug=str(raw["slug"]),
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        category_slug=category_slug,
        category_name=category.name if category else str(raw.get("category_name", "")),
        brand=str(raw.get("brand", "")),
        condition=str(raw.get("condition", "")),
        images=images,
        variants=variants,
        tags=[str(t) for t in raw.get("tags", [])],
        is_new_arrival=bool(raw.get("is_new_arrival", False)),
        is_on_sale=bool(raw.get("is_on_sale", False)),
        sale_price_gbp=raw.get("sale_price_gbp"),
        compare_at_price_gbp=raw.get("compare_at_price_gbp"),
        gtin=str(raw.get("gtin", "")),
        mpn=str(raw.get("mpn", "")),
        catalog_status=str(raw.get("catalog_status", "demo")),
    )


def load_catalog(path: Path = CATALOG_PATH) -> tuple[list[Category], list[Product]]:
    raw = _load_raw(path)
    categories: list[Category] = []
    for entry in raw.get("categories", []):
        try:
            categories.append(_category(entry))
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Skipping invalid static category %r: %s", entry, exc)
    by_slug = {c.slug: c for c in categories}
    products: list[Product] = []
    for entry in raw.get("products", []):
        try:
            products.append(_product(entry, by_slug))
        except (KeyError, TypeError, ValueError) as exc:
            logger.error("Skipping invalid static product %r: %s", entry.get("slug"), exc)
    return categories, products


@lru_cache(maxsize=1)
def _cached() -> tuple[list[Category], list[Product]]:
    return load_catalog()


def all_categories() -> list[Category]:
    return list(_cached()[0])


def all_products() -> list[Product]:
    return list(_cached()[1])


def get_product(slug: str) -> Product | None:
    return next((p for p in all_products() if p.slug == slug), None)

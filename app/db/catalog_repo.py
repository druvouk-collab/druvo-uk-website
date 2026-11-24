"""Database-backed catalogue (CATALOG_SOURCE=db).

Exposes the same interface as app.data.static_catalog (all_categories,
all_products, get_product) and returns the shared commerce dataclasses, so
templates, SEO, chat and the Merchant feed work unchanged.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select

from app.db import models
from app.db.base import session_scope
from app.types.commerce import Category, Product, ProductVariant

logger = logging.getLogger(__name__)

PLACEHOLDER_PRODUCT = "/static/images/placeholder-product.svg"
PLACEHOLDER_CATEGORY = "/static/images/placeholder-category.svg"


def pence(gbp: float | int | str | None) -> int | None:
    if gbp is None or gbp == "":
        return None
    return int(round(float(gbp) * 100))


def gbp(amount_pence: int | None) -> float | None:
    return None if amount_pence is None else amount_pence / 100


# Public catalogue maps DB status → existing catalog_status vocabulary.
_STATUS_TO_CATALOG = {"live": "live", "draft": "draft", "archived": "archived"}


def _to_category(row: models.Category) -> Category:
    return Category(
        slug=row.slug,
        name=row.name,
        description=row.description,
        image=row.image or PLACEHOLDER_CATEGORY,
    )


def _to_product(row: models.Product) -> Product:
    variants = [
        ProductVariant(
            sku=v.sku,
            size=v.size,
            colour=v.colour,
            stock_quantity=v.stock_quantity,
            price_gbp=v.price_pence / 100,
            variant_id=v.id,
        )
        for v in row.variants
    ]
    images = [img.url for img in row.images if img.url] or [PLACEHOLDER_PRODUCT]
    return Product(
        id=row.external_id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        category_slug=row.category.slug if row.category else "",
        category_name=row.category.name if row.category else "",
        brand=row.brand,
        condition=row.condition,
        images=images,
        variants=variants,
        tags=list(row.tags or []),
        is_new_arrival=row.is_new_arrival,
        is_on_sale=row.is_on_sale,
        sale_price_gbp=gbp(row.sale_price_pence),
        compare_at_price_gbp=gbp(row.compare_at_price_pence),
        gtin=row.gtin,
        mpn=row.mpn,
        catalog_status=_STATUS_TO_CATALOG.get(row.status, "draft"),
    )


def all_categories() -> list[Category]:
    with session_scope() as session:
        rows = session.scalars(select(models.Category).order_by(models.Category.sort_order, models.Category.name))
        return [_to_category(r) for r in rows]


def all_products() -> list[Product]:
    """Products visible to the storefront (live only; sold-out live items still show as out of stock)."""
    with session_scope() as session:
        rows = session.scalars(
            select(models.Product).where(models.Product.status == "live").order_by(models.Product.created_at.desc())
        ).unique()
        products = []
        for row in rows:
            if not row.variants:
                continue
            products.append(_to_product(row))
        return products


def get_product(slug: str) -> Product | None:
    with session_scope() as session:
        row = session.scalars(
            select(models.Product).where(models.Product.slug == slug, models.Product.status == "live")
        ).first()
        if row is None or not row.variants:
            return None
        return _to_product(row)


# --------------------------------------------------------------------------- import


def import_catalog_json(path: Path, *, session_url: str | None = None) -> dict[str, int]:
    """Idempotently upsert categories/products/variants from catalog.json.

    Existing stock levels are NOT overwritten for variants that already exist —
    the database is the source of truth for stock once imported.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    counts = {"categories": 0, "products": 0, "variants_created": 0, "variants_updated": 0}
    with session_scope(session_url) as session:
        cats: dict[str, models.Category] = {}
        for index, entry in enumerate(raw.get("categories", [])):
            row = session.scalar(select(models.Category).where(models.Category.slug == entry["slug"]))
            if row is None:
                row = models.Category(slug=entry["slug"])
                session.add(row)
            row.name = entry["name"]
            row.description = entry.get("description", "")
            row.image = entry.get("image", "")
            row.sort_order = index
            cats[row.slug] = row
            counts["categories"] += 1
        session.flush()

        for entry in raw.get("products", []):
            slug = entry["slug"]
            row = session.scalar(select(models.Product).where(models.Product.slug == slug))
            if row is None:
                row = models.Product(slug=slug, external_id=str(entry.get("id") or slug))
                session.add(row)
            row.name = entry["name"]
            row.description = entry.get("description", "")
            row.category = cats.get(entry.get("category_slug", ""))
            row.brand = entry.get("brand", "")
            row.condition = entry.get("condition", "")
            row.tags = list(entry.get("tags", []))
            row.is_new_arrival = bool(entry.get("is_new_arrival", False))
            row.is_on_sale = bool(entry.get("is_on_sale", False))
            row.sale_price_pence = pence(entry.get("sale_price_gbp"))
            row.compare_at_price_pence = pence(entry.get("compare_at_price_gbp"))
            row.gtin = entry.get("gtin", "")
            row.mpn = entry.get("mpn", "")
            status = str(entry.get("catalog_status", "draft"))
            row.status = status if status in ("live", "draft", "archived") else "draft"

            row.images.clear()
            session.flush()
            for pos, url in enumerate(i for i in entry.get("images", []) if i):
                row.images.append(models.ProductImage(url=url, position=pos, alt=row.name))

            for v in entry.get("variants", []):
                variant = session.scalar(select(models.Variant).where(models.Variant.sku == v["sku"]))
                if variant is None:
                    variant = models.Variant(sku=v["sku"], stock_quantity=int(v.get("stock_quantity", 0)))
                    row.variants.append(variant)
                    counts["variants_created"] += 1
                else:
                    counts["variants_updated"] += 1
                variant.size = v.get("size", "")
                variant.colour = v.get("colour", "")
                variant.price_pence = pence(v["price_gbp"]) or 0
            counts["products"] += 1
    logger.info("Catalogue import complete: %s", counts)
    return counts


def main() -> None:  # pragma: no cover - CLI
    import argparse

    from app.data.static_catalog import CATALOG_PATH

    parser = argparse.ArgumentParser(description="Import catalog.json into the DRUVO database")
    parser.add_argument("path", nargs="?", default=str(CATALOG_PATH))
    args = parser.parse_args()
    print(import_catalog_json(Path(args.path)))


if __name__ == "__main__":  # pragma: no cover
    main()

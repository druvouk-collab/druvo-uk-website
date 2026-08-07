"""Map DRUVO AI API payloads to website commerce types."""

from __future__ import annotations

from app.types.commerce import Category, Product, ProductVariant


def map_product(payload: dict) -> Product:
    variants = [
        ProductVariant(
            sku=v["sku"],
            size=v["size"],
            colour=v["colour"],
            stock_quantity=int(v["stock_quantity"]),
            price_gbp=float(v["price_gbp"]),
        )
        for v in payload.get("variants", [])
    ]
    return Product(
        id=str(payload["id"]),
        slug=payload["slug"],
        name=payload["name"],
        description=payload.get("description", ""),
        category_slug=payload.get("category_slug", "uncategorised"),
        category_name=payload.get("category_name", "Uncategorised"),
        brand=payload.get("brand", ""),
        condition=payload.get("condition", "Pre-loved"),
        images=list(payload.get("images") or [""]),
        variants=variants,
        tags=list(payload.get("tags") or []),
        is_new_arrival=bool(payload.get("is_new_arrival")),
        is_on_sale=bool(payload.get("is_on_sale")),
        sale_price_gbp=payload.get("sale_price_gbp"),
    )


def map_category(payload: dict) -> Category:
    return Category(
        slug=payload["slug"],
        name=payload["name"],
        description=payload.get("description", ""),
        image=payload.get("image", ""),
    )

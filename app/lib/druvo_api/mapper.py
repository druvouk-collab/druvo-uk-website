"""Map DRUVO AI API payloads to website commerce types."""

from __future__ import annotations

from app.types.commerce import Category, Order, OrderLine, Product, ProductVariant


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


def map_order(payload: dict) -> Order:
    lines = [
        OrderLine(
            product_slug=line.get("sku", ""),
            product_name=line.get("sku", "Item"),
            sku=line.get("sku", ""),
            size=line.get("size", "—"),
            colour=line.get("colour", "—"),
            quantity=int(line.get("quantity", 1)),
            unit_price_gbp=float(line.get("unit_price_gbp", line.get("unit_price", 0))),
        )
        for line in payload.get("lines", [])
    ]
    subtotal = sum(line.quantity * line.unit_price_gbp for line in lines)
    return Order(
        id=str(payload.get("external_order_id") or payload.get("order_id")),
        placed_at=str(payload.get("created_at", "")),
        status=str(payload.get("status", "received")).title(),
        tracking_number=None,
        lines=lines,
        subtotal_gbp=subtotal,
        shipping_gbp=0.0,
        total_gbp=float(payload.get("total_amount", subtotal)),
    )

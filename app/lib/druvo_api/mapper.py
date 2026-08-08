"""Map DRUVO AI API payloads to website commerce types."""



from __future__ import annotations

from app.lib.druvo_api.image_proxy import to_website_proxy_path, to_website_proxy_url
from app.types.commerce import Category, Order, OrderLine, Product, ProductVariant

_PLACEHOLDER_PRODUCT = "/static/images/placeholder-product.svg"

_PLACEHOLDER_CATEGORY = "/static/images/placeholder-category.svg"


def _map_product_images(payload: dict) -> list[str]:
    """Prefer structured gallery paths so product folders are preserved."""
    images: list[str] = []
    seen: set[str] = set()

    gallery = payload.get("gallery") or []
    if gallery:
        for entry in sorted(
            gallery,
            key=lambda row: (not row.get("is_main"), row.get("sort_order", 0)),
        ):
            path = str(entry.get("path") or "").strip()
            if path:
                proxy = to_website_proxy_path(path)
            else:
                proxy = to_website_proxy_url(str(entry.get("url") or "").strip())
            if proxy and proxy not in seen:
                images.append(proxy)
                seen.add(proxy)

    for url in payload.get("images") or []:
        proxy = to_website_proxy_url(str(url).strip())
        if proxy and proxy not in seen and "placeholder-product" not in proxy:
            images.append(proxy)
            seen.add(proxy)

    return images or [_PLACEHOLDER_PRODUCT]


def map_product(payload: dict) -> Product:

    variants = [

        ProductVariant(

            sku=v["sku"],

            size=v["size"],

            colour=v["colour"],

            stock_quantity=int(v["stock_quantity"]),

            price_gbp=float(v["price_gbp"]),

            variant_id=v.get("variant_id"),

        )

        for v in payload.get("variants", [])

    ]

    images = _map_product_images(payload)

    return Product(

        id=str(payload["id"]),

        slug=payload["slug"],

        name=payload["name"],

        description=payload.get("description", ""),

        category_slug=payload.get("category_slug", "uncategorised"),

        category_name=payload.get("category_name", "Uncategorised"),

        brand=payload.get("brand", ""),

        condition=payload.get("condition", "Pre-loved"),

        images=images,

        variants=variants,

        tags=list(payload.get("tags") or []),

        is_new_arrival=bool(payload.get("is_new_arrival")),

        is_on_sale=bool(payload.get("is_on_sale")),

        sale_price_gbp=payload.get("sale_price_gbp"),

        compare_at_price_gbp=payload.get("compare_at_price_gbp"),

        gtin=(payload.get("gtin") or payload.get("barcode") or "").strip(),

        mpn=(payload.get("mpn") or "").strip(),

        catalog_status=(payload.get("catalog_status") or "demo").strip().lower(),

    )





def map_category(payload: dict) -> Category:

    image = payload.get("image", "") or _PLACEHOLDER_CATEGORY

    return Category(

        slug=payload["slug"],

        name=payload["name"],

        description=payload.get("description", ""),

        image=image,

    )





def map_order(payload: dict) -> Order:

    lines = [

        OrderLine(

            product_slug=line.get("sku", ""),

            product_name=line.get("product_name") or line.get("sku", "Item"),

            sku=line.get("sku", ""),

            size=line.get("size", "—"),

            colour=line.get("colour", "—"),

            quantity=int(line.get("quantity", 1)),

            unit_price_gbp=float(line.get("unit_price_gbp", line.get("unit_price", 0))),

        )

        for line in payload.get("lines", [])

    ]

    subtotal = sum(line.quantity * line.unit_price_gbp for line in lines)

    tracking = payload.get("tracking_number")

    carrier = payload.get("carrier")

    shipping_gbp = float(payload.get("shipping_gbp") or 0)

    return Order(

        id=str(payload.get("external_order_id") or payload.get("order_id")),

        placed_at=str(payload.get("created_at", "")),

        status=str(payload.get("status_label") or payload.get("status", "received")).title(),

        tracking_number=tracking if tracking else None,

        carrier=carrier if carrier else None,

        lines=lines,

        subtotal_gbp=subtotal,

        shipping_gbp=shipping_gbp,

        total_gbp=float(payload.get("total_amount", subtotal + shipping_gbp)),

    )


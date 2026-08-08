"""Catalog-driven SEO titles, descriptions, alt text and breadcrumbs."""

from __future__ import annotations

import json
import re
from typing import Iterable

from app.services.seo_service import canonical_url_for, meta_description
from app.types.commerce import Category, Product

_SITE = "DRUVO UK"
_UNCATEGORISED = {"uncategorised", "uncategorized"}


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def _valid_brand(brand: str) -> str:
    cleaned = _clean(brand)
    return cleaned if cleaned else ""


def catalog_brands(products: Iterable[Product], limit: int = 4) -> list[str]:
    seen: set[str] = set()
    brands: list[str] = []
    for product in products:
        brand = _valid_brand(product.brand)
        key = brand.lower()
        if brand and key not in seen:
            seen.add(key)
            brands.append(brand)
        if len(brands) >= limit:
            break
    return brands


def _brand_phrase(brands: list[str]) -> str:
    if not brands:
        return "leading brands"
    if len(brands) == 1:
        return brands[0]
    if len(brands) == 2:
        return f"{brands[0]} and {brands[1]}"
    return f"{', '.join(brands[:-1])} and {brands[-1]}"


def _category_label(category_name: str) -> str:
    cleaned = _clean(category_name)
    if not cleaned or cleaned.lower() in _UNCATEGORISED:
        return "fashion"
    return cleaned


def _audience_hint(product: Product) -> str:
    cat = product.category_name.lower()
    if "women" in cat:
        return "women's"
    if "men" in cat and "women" not in cat:
        return "men's"
    return ""


def _stock_phrase(product: Product) -> str:
    if not product.in_stock:
        return "Currently out of stock online."
    colours = product.colours[:3]
    sizes = product.sizes[:4]
    parts: list[str] = []
    if colours:
        parts.append(f"colours: {', '.join(colours)}")
    if sizes:
        parts.append(f"sizes: {', '.join(sizes)}")
    if parts:
        return f"In stock online UK — {'; '.join(parts)}."
    return "In stock online at DRUVO UK."


def _price_phrase(product: Product) -> str:
    if product.min_price == product.max_price:
        return f"£{product.min_price:,.2f}"
    return f"from £{product.min_price:,.2f}"


def home_document_title(products: list[Product]) -> str:
    brands = catalog_brands(products, limit=3)
    if brands:
        return f"Shop Pre-Loved Fashion & Resale Online UK | {_SITE}"
    return f"Premium UK Resale Fashion & Footwear | {_SITE}"


def home_meta_description(products: list[Product]) -> str:
    brands = catalog_brands(products, limit=4)
    brand_text = _brand_phrase(brands)
    count = len(products)
    listing = f"{count} live listings" if count else "curated listings"
    return meta_description(
        f"Shop online at DRUVO UK for premium pre-loved and new-with-tags fashion, footwear and accessories. "
        f"Browse {brand_text} with {listing} and UK delivery."
    )


def shop_document_title(products: list[Product]) -> str:
    brands = catalog_brands(products, limit=2)
    if brands:
        return f"Shop All | {_brand_phrase(brands)} & More | {_SITE}"
    return f"Shop All Clothing, Footwear & Accessories | {_SITE}"


def shop_meta_description(products: list[Product]) -> str:
    brands = catalog_brands(products, limit=4)
    types = sorted({tag for p in products for tag in p.tags if tag})[:3]
    type_hint = f" including {', '.join(types)}" if types else ""
    return meta_description(
        f"Browse the full DRUVO UK shop — pre-loved and new-with-tags pieces from {_brand_phrase(brands)}{type_hint}. "
        f"Shop online with live UK stock."
    )


def categories_document_title() -> str:
    return f"Shop by Category | Clothing, Footwear & Accessories | {_SITE}"


def categories_meta_description(products: list[Product]) -> str:
    categories = sorted({_category_label(p.category_name) for p in products if _category_label(p.category_name) != "fashion"})
    if categories:
        cat_text = ", ".join(categories[:4])
        return meta_description(
            f"Browse DRUVO UK categories — shop {cat_text} and more. Premium resale fashion with live stock, available to shop online in the UK."
        )
    return meta_description(
        "Browse DRUVO UK categories — premium pre-loved and new-with-tags clothing, footwear and accessories. Shop online in the UK."
    )


def category_document_title(category: Category) -> str:
    return f"{category.name} | Shop Online UK | {_SITE}"


def category_meta_description(category: Category, products: list[Product]) -> str:
    brands = catalog_brands(products, limit=3)
    brand_text = _brand_phrase(brands) if brands else "quality brands"
    desc = _clean(category.description)
    intro = desc if desc else f"Shop {category.name.lower()} at DRUVO UK."
    return meta_description(f"{intro} Browse {brand_text} with live UK stock — shop online today.")


def product_document_title(product: Product) -> str:
    brand = _valid_brand(product.brand)
    category = _category_label(product.category_name)
    if brand:
        return f"{product.name} | {brand} {category} | {_SITE}"
    return f"{product.name} | {category.title()} | {_SITE}"


def product_meta_description(product: Product) -> str:
    brand = _valid_brand(product.brand)
    condition = _clean(product.condition)
    lead = _clean(product.description)
    opener = f"{brand} {product.name}" if brand else product.name
    core = f"{opener} — {_price_phrase(product)}."
    if condition:
        core += f" {condition} condition."
    stock = _stock_phrase(product)
    cta = "Shop online at DRUVO UK."
    reserved = len(f"{core} {stock} {cta}")
    lead_room = max(0, 155 - reserved - 2)
    snippet = meta_description(lead, lead_room) if lead and lead_room >= 24 else ""
    combined = " ".join(part for part in (core, snippet, stock, cta) if part)
    return meta_description(combined, 155)


def product_image_alt(product: Product, index: int = 0) -> str:
    brand = _valid_brand(product.brand)
    colour = product.colours[0] if product.colours else ""
    bits = [product.name]
    if brand:
        bits.append(f"by {brand}")
    if colour:
        bits.append(f"in {colour}")
    bits.append(_category_label(product.category_name))
    if index:
        bits.append(f"image {index + 1}")
    return " — ".join(bits)


def product_breadcrumbs(product: Product) -> list[dict[str, str]]:
    crumbs = [
        {"name": "Home", "path": "/"},
        {"name": "Shop", "path": "/shop"},
    ]
    if product.category_slug and product.category_slug.lower() not in _UNCATEGORISED:
        crumbs.append({"name": product.category_name, "path": f"/categories/{product.category_slug}"})
    crumbs.append({"name": product.name, "path": f"/product/{product.slug}"})
    return crumbs


def breadcrumb_json_ld(crumbs: list[dict[str, str]]) -> str:
    items = []
    for index, crumb in enumerate(crumbs, start=1):
        items.append(
            {
                "@type": "ListItem",
                "position": index,
                "name": crumb["name"],
                "item": canonical_url_for(crumb["path"]),
            }
        )
    payload = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }
    return json.dumps(payload, ensure_ascii=False)


def _schema_condition(condition: str) -> str:
    lowered = condition.lower()
    if any(word in lowered for word in ("new", "tags", "unworn", "bnwt")):
        return "https://schema.org/NewCondition"
    return "https://schema.org/UsedCondition"


def about_document_title() -> str:
    return f"About DRUVO UK | Premium UK Resale Fashion | {_SITE}"


def about_meta_description() -> str:
    return meta_description(
        "Learn about DRUVO UK — premium pre-loved and new-with-tags fashion, footwear and accessories. "
        "Curated UK resale powered by DRUVO AI Enterprise."
    )


def contact_document_title() -> str:
    return f"Contact DRUVO UK | Customer Support | {_SITE}"


def contact_meta_description() -> str:
    return meta_description(
        "Contact DRUVO UK for order enquiries, product questions and customer support. "
        "We respond to UK customers by email during business hours."
    )


def faq_document_title() -> str:
    return f"FAQ | Shipping, Returns & Authenticity | {_SITE}"


def faq_meta_description() -> str:
    return meta_description(
        "DRUVO UK FAQ — answers about authenticity, UK delivery times, returns, live stock "
        "and how we grade pre-loved and new-with-tags fashion."
    )


def delivery_document_title() -> str:
    return f"UK Delivery Information | Tracked Shipping | {_SITE}"


def delivery_meta_description() -> str:
    return meta_description(
        "DRUVO UK delivery — standard UK tracked shipping in 2–4 working days (£3.99, free over £75) "
        "and express 1–2 day delivery. Order tracking by email."
    )


def shipping_returns_document_title() -> str:
    return f"Shipping & Returns | UK Delivery & Refunds | {_SITE}"


def shipping_returns_meta_description() -> str:
    return meta_description(
        "DRUVO UK shipping and returns — tracked UK delivery options plus 14-day returns on eligible items. "
        "Read delivery times, costs and refund policy."
    )


def returns_document_title() -> str:
    return f"Returns Policy | 14-Day UK Returns | {_SITE}"


def returns_meta_description() -> str:
    return meta_description(
        "DRUVO UK returns policy — return eligible unworn items within 14 days of delivery. "
        "How to start a return, postage and refund timelines explained."
    )


def terms_document_title() -> str:
    return f"Terms & Conditions | DRUVO UK Online Shop | {_SITE}"


def terms_meta_description() -> str:
    return meta_description(
        "DRUVO UK terms and conditions for online purchases — ordering, payment, delivery, "
        "returns and your consumer rights when shopping with us."
    )


def privacy_document_title() -> str:
    return f"Privacy Policy | How DRUVO UK Uses Your Data | {_SITE}"


def privacy_meta_description() -> str:
    return meta_description(
        "DRUVO UK privacy policy — how we collect, use and protect personal data for orders, "
        "accounts and customer communications under UK GDPR."
    )


def item_list_json_ld(products: list[Product], list_name: str, path: str) -> str:
    base_items = []
    for index, product in enumerate(products[:12], start=1):
        base_items.append(
            {
                "@type": "ListItem",
                "position": index,
                "url": canonical_url_for(f"/product/{product.slug}"),
                "name": product.name,
            }
        )
    payload = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": list_name,
        "url": canonical_url_for(path),
        "itemListElement": base_items,
    }
    return json.dumps(payload, ensure_ascii=False)

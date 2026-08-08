"""SEO helpers — canonical URLs, sitemap, structured data."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from app.config import PRODUCTION_SITE_URL, Settings, get_settings
from app.services.catalog_service import CatalogService
from app.types.commerce import Product

# Paths that must never appear in the sitemap or be indexed.
NOINDEX_PATH_PREFIXES = (
    "/account",
    "/cart",
    "/checkout",
    "/admin",
    "/search",
    "/api/",
    "/webhooks/",
    "/health",
)

PUBLIC_STATIC_PATHS = [
    "/",
    "/shop",
    "/new-arrivals",
    "/sale",
    "/categories",
    "/about",
    "/contact",
    "/faq",
    "/delivery",
    "/shipping-returns",
    "/returns",
    "/terms",
    "/privacy",
]


def canonical_site_url(settings: Settings | None = None) -> str:
    """Always prefer https://druvo.uk — never onrender.com as canonical."""
    cfg = settings or get_settings()
    url = cfg.public_site_url.rstrip("/")
    if "onrender.com" in url or cfg._is_local_url(url):
        return PRODUCTION_SITE_URL
    return url


def canonical_url_for(path: str, settings: Settings | None = None) -> str:
    base = canonical_site_url(settings)
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


def is_indexable_path(path: str) -> bool:
    normalized = path.split("?")[0].rstrip("/") or "/"
    for prefix in NOINDEX_PATH_PREFIXES:
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
            return False
    return True


def robots_txt(settings: Settings | None = None) -> str:
    base = canonical_site_url(settings)
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /account/",
        "Disallow: /cart",
        "Disallow: /checkout",
        "Disallow: /admin/",
        "Disallow: /search",
        "Disallow: /api/",
        "Disallow: /webhooks/",
        "Disallow: /health",
        "",
        f"Sitemap: {base}/sitemap.xml",
    ]
    return "\n".join(lines) + "\n"


async def build_sitemap_urls() -> list[dict[str, str]]:
    settings = get_settings()
    base = canonical_site_url(settings)
    catalog = CatalogService(settings)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(path: str, priority: str = "0.7", changefreq: str = "weekly") -> None:
        if path in seen or not is_indexable_path(path):
            return
        seen.add(path)
        entries.append(
            {
                "loc": f"{base}{path}",
                "lastmod": now,
                "changefreq": changefreq,
                "priority": priority,
            }
        )

    for path in PUBLIC_STATIC_PATHS:
        pri = "1.0" if path == "/" else "0.8" if path in {"/shop", "/categories"} else "0.6"
        add(path, priority=pri)

    categories = await catalog.list_categories()
    for category in categories:
        add(f"/categories/{category.slug}", priority="0.7")

    products = await catalog.list_products()
    for product in products:
        add(f"/product/{product.slug}", priority="0.8", changefreq="daily")

    return entries


def sitemap_xml(urls: list[dict[str, str]]) -> str:
    urlset = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for item in urls:
        url_el = SubElement(urlset, "url")
        SubElement(url_el, "loc").text = item["loc"]
        SubElement(url_el, "lastmod").text = item["lastmod"]
        SubElement(url_el, "changefreq").text = item["changefreq"]
        SubElement(url_el, "priority").text = item["priority"]
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(urlset, encoding="unicode")


def meta_description(text: str, max_len: int = 155) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def organization_json_ld(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    base = canonical_site_url(cfg)
    payload = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": cfg.site_name,
        "url": base,
        "email": cfg.contact_email,
        "description": (
            "DRUVO UK is a premium UK resale store for pre-loved and new-with-tags "
            "clothing, footwear and accessories."
        ),
        "areaServed": {
            "@type": "Country",
            "name": "United Kingdom",
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def website_json_ld(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    base = canonical_site_url(cfg)
    payload = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": cfg.site_name,
        "url": base,
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{base}/search?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
    }
    return json.dumps(payload, ensure_ascii=False)


def _product_item_condition(condition: str) -> str:
    lowered = (condition or "").lower()
    if any(word in lowered for word in ("new", "tags", "unworn", "bnwt")):
        return "https://schema.org/NewCondition"
    return "https://schema.org/UsedCondition"


def _absolute_image_url(image: str, base: str) -> str:
    if image.startswith("/"):
        return f"{base}{image}"
    if image.startswith("http"):
        return image
    return f"{base}/{image.lstrip('/')}"


def _product_images(product: Product, base: str) -> list[str]:
    images = [_absolute_image_url(img, base) for img in product.images if img]
    if not images:
        images = [f"{base}/static/images/placeholder-product.svg"]
    return images


def _seller_organization(cfg: Settings, base: str) -> dict:
    return {
        "@type": "Organization",
        "name": cfg.site_name,
        "url": base,
    }


def _product_schema_description(product: Product) -> str:
    desc = " ".join((product.description or "").split())
    if len(desc) >= 20:
        return meta_description(desc, 500)
    parts = [product.name]
    brand = (product.brand or "").strip()
    if brand:
        parts.insert(0, brand)
    condition = (product.condition or "").strip()
    if condition:
        parts.append(f"{condition} condition")
    return meta_description(". ".join(parts), 500)


def _variant_offer(
    variant,
    product: Product,
    base: str,
    condition_url: str,
    seller: dict,
) -> dict:
    availability = (
        "https://schema.org/InStock"
        if variant.stock_quantity > 0
        else "https://schema.org/OutOfStock"
    )
    offer: dict = {
        "@type": "Offer",
        "priceCurrency": "GBP",
        "price": f"{variant.price_gbp:.2f}",
        "availability": availability,
        "sku": variant.sku,
        "url": f"{base}/product/{product.slug}",
        "itemCondition": condition_url,
        "seller": seller,
    }
    if variant.colour:
        offer["color"] = variant.colour
    if variant.size:
        offer["size"] = variant.size
    return offer


def product_json_ld(product: Product, settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    base = canonical_site_url(cfg)
    images = _product_images(product, base)
    condition_url = _product_item_condition(product.condition)
    seller = _seller_organization(cfg, base)

    offers = [
        _variant_offer(variant, product, base, condition_url, seller)
        for variant in product.variants
    ]

    product_url = f"{base}/product/{product.slug}"
    colours = sorted({v.colour for v in product.variants if v.colour})
    sizes = sorted({v.size for v in product.variants if v.size})
    payload: dict = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.name,
        "description": _product_schema_description(product),
        "image": images if len(images) > 1 else images[0],
        "url": product_url,
        "sku": product.variants[0].sku if product.variants else product.slug,
        "itemCondition": condition_url,
    }
    if product.category_name and product.category_name.lower() not in {"uncategorised", "uncategorized"}:
        payload["category"] = product.category_name
    brand = (product.brand or "").strip()
    if brand:
        payload["brand"] = {"@type": "Brand", "name": brand}
    if colours:
        payload["color"] = colours if len(colours) > 1 else colours[0]
    if sizes:
        payload["size"] = sizes if len(sizes) > 1 else sizes[0]
    if len(offers) > 1:
        prices = [variant.price_gbp for variant in product.variants]
        payload["offers"] = {
            "@type": "AggregateOffer",
            "priceCurrency": "GBP",
            "lowPrice": f"{min(prices):.2f}",
            "highPrice": f"{max(prices):.2f}",
            "offerCount": len(offers),
            "offers": offers,
        }
    elif len(offers) == 1:
        payload["offers"] = offers[0]
    return json.dumps(payload, ensure_ascii=False)

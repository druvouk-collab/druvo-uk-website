"""Google Merchant Center feed generation from live DRUVO AI catalogue."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from xml.etree.ElementTree import Element, SubElement, tostring

from app.config import Settings, get_settings
from app.services.catalog_service import CatalogService
from app.services.catalog_visibility import has_real_product_image, is_merchant_eligible
from app.services.seo_service import _absolute_image_url, _product_item_condition, canonical_site_url, meta_description
from app.types.commerce import Product, ProductVariant

GOOGLE_NS = "http://base.google.com/ns/1.0"


@dataclass(frozen=True)
class MerchantFeedItem:
    id: str
    item_group_id: str
    title: str
    description: str
    link: str
    image_link: str
    availability: str
    price_gbp: str
    condition: str
    brand: str
    color: str
    size: str
    gtin: str
    mpn: str
    shipping_country: str
    shipping_service: str
    shipping_price_gbp: str


def merchant_availability(variant: ProductVariant) -> str:
    return "in_stock" if variant.stock_quantity > 0 else "out_of_stock"


def merchant_condition(condition: str) -> str:
    schema = _product_item_condition(condition)
    if schema.endswith("NewCondition"):
        return "new"
    return "used"


def merchant_price_gbp(variant: ProductVariant, product: Product) -> str:
    price = variant.price_gbp
    if product.is_on_sale and product.sale_price_gbp is not None:
        price = product.sale_price_gbp
    return f"{price:.2f} GBP"


def merchant_description(product: Product) -> str:
    desc = " ".join((product.description or "").split())
    if len(desc) >= 20:
        return meta_description(desc, 5000)
    parts = [product.name]
    brand = (product.brand or "").strip()
    if brand:
        parts.insert(0, brand)
    condition = (product.condition or "").strip()
    if condition:
        parts.append(f"{condition} condition")
    return meta_description(". ".join(parts), 5000)


def _primary_image(product: Product, base: str) -> str:
    for image in product.images:
        if (
            image
            and "placeholder-product" not in image
            and not image.endswith("placeholder-product.svg")
        ):
            return _absolute_image_url(image, base)
    return ""


def build_merchant_feed_items(
    products: list[Product],
    settings: Settings | None = None,
) -> list[MerchantFeedItem]:
    cfg = settings or get_settings()
    base = canonical_site_url(cfg)
    items: list[MerchantFeedItem] = []

    for product in products:
        if not is_merchant_eligible(product):
            continue

        image_link = _primary_image(product, base)
        if not image_link:
            continue

        description = merchant_description(product)
        link = f"{base}/product/{product.slug}"
        brand = (product.brand or "").strip()
        condition = merchant_condition(product.condition)
        gtin = (product.gtin or "").strip()
        mpn = (product.mpn or "").strip()

        for variant in product.variants:
            items.append(
                MerchantFeedItem(
                    id=variant.sku,
                    item_group_id=product.slug,
                    title=product.name[:150],
                    description=description,
                    link=link,
                    image_link=image_link,
                    availability=merchant_availability(variant),
                    price_gbp=merchant_price_gbp(variant, product),
                    condition=condition,
                    brand=brand,
                    color=variant.colour or "",
                    size=variant.size or "",
                    gtin=gtin,
                    mpn=mpn,
                    shipping_country="GB",
                    shipping_service="Standard UK delivery",
                    shipping_price_gbp=f"{cfg.shipping_standard_gbp:.2f} GBP",
                )
            )

    return items


def merchant_feed_xml(items: list[MerchantFeedItem], settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    base = canonical_site_url(cfg)
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rss = Element("rss", version="2.0")
    rss.set("xmlns:g", GOOGLE_NS)
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = cfg.site_name
    SubElement(channel, "link").text = base
    SubElement(
        channel,
        "description",
    ).text = (
        "DRUVO UK Google Merchant product feed — live inventory synced from DRUVO AI. "
        "Demo/development products are excluded until marked live. "
        f"Returns: {base}/returns · Shipping: {base}/delivery"
    )
    SubElement(channel, "lastBuildDate").text = updated

    for item in items:
        entry = SubElement(channel, "item")
        _g(entry, "id", item.id)
        _g(entry, "item_group_id", item.item_group_id)
        _g(entry, "title", item.title)
        _g(entry, "description", item.description)
        _g(entry, "link", item.link)
        _g(entry, "image_link", item.image_link)
        _g(entry, "availability", item.availability)
        _g(entry, "price", item.price_gbp)
        _g(entry, "condition", item.condition)
        if item.brand:
            _g(entry, "brand", item.brand)
        if item.color:
            _g(entry, "color", item.color)
        if item.size:
            _g(entry, "size", item.size)
        if item.gtin:
            _g(entry, "gtin", item.gtin)
        if item.mpn:
            _g(entry, "mpn", item.mpn)

        shipping = SubElement(entry, f"{{{GOOGLE_NS}}}shipping")
        _g(shipping, "country", item.shipping_country)
        _g(shipping, "service", item.shipping_service)
        _g(shipping, "price", item.shipping_price_gbp)

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(rss, encoding="unicode")


async def build_merchant_feed_xml(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    catalog = CatalogService(cfg)
    products = await catalog.list_products()
    items = build_merchant_feed_items(products, cfg)
    return merchant_feed_xml(items, cfg)


def _g(parent: Element, tag: str, text: str) -> None:
    SubElement(parent, f"{{{GOOGLE_NS}}}{tag}").text = text

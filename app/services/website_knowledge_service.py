"""Single source of truth for live website knowledge consumed by DRUVO Chat."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import Settings, get_settings
from app.services.website_policies import WebsitePolicies, build_website_policies
from app.services.catalog_service import CatalogFilters, CatalogService
from app.services.catalog_snapshot import CatalogSnapshot
from app.services.catalog_visibility import filter_live_products, is_live_catalog_product
from app.services.promotion_service import Promotion, PromotionService
from app.services.shipping_service import ShippingQuote, calculate_shipping
from app.types.commerce import Category, Product


@dataclass(frozen=True)
class WebsiteKnowledgeSnapshot:
    products: list[Product]
    live_products: list[Product]
    categories: list[Category]
    promotions: list[Promotion]
    policies: WebsitePolicies
    shipping_standard_gbp: float
    shipping_free_threshold_gbp: float
    site_url: str
    degraded: bool = False
    notice: str = ""


@dataclass(frozen=True)
class CartSummary:
    subtotal_gbp: float
    item_count: int
    shipping: ShippingQuote
    amount_to_free_delivery_gbp: float | None


class WebsiteKnowledgeService:
    """Aggregate live catalogue, promotions, shipping and policies for chat + storefront."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._catalog = CatalogService(self._settings)
        self._promotions = PromotionService(self._settings)

    @property
    def settings(self) -> Settings:
        return self._settings

    async def load(self) -> WebsiteKnowledgeSnapshot:
        snapshot = await self._catalog.load_snapshot()
        promotions = await self._promotions.list_active()
        policies = build_website_policies(self._settings)
        live = filter_live_products(snapshot.products)
        return WebsiteKnowledgeSnapshot(
            products=snapshot.products,
            live_products=live,
            categories=snapshot.categories,
            promotions=promotions,
            policies=policies,
            shipping_standard_gbp=float(self._settings.shipping_standard_gbp),
            shipping_free_threshold_gbp=float(self._settings.shipping_free_threshold_gbp),
            site_url=self._settings.public_site_url.rstrip("/"),
            degraded=snapshot.degraded,
            notice=snapshot.notice,
        )

    async def search_live_products(
        self,
        query: str = "",
        *,
        category_slug: str | None = None,
        size: str | None = None,
        colour: str | None = None,
        min_price: float | None = None,
        max_price: float | None = None,
        on_sale_only: bool = False,
        in_stock_only: bool = False,
        sort: str = "featured",
    ) -> list[Product]:
        filters = CatalogFilters(
            query=query,
            category_slug=category_slug,
            size=size,
            colour=colour,
            min_price=min_price,
            max_price=max_price,
            on_sale_only=on_sale_only,
            in_stock_only=in_stock_only,
            sort=sort,
        )
        snapshot = await self._catalog.load_snapshot(filters)
        return filter_live_products(snapshot.products)

    def cart_summary(self, cart_items: list[dict]) -> CartSummary:
        subtotal = sum(float(item.get("price_gbp", 0)) * int(item.get("quantity", 1)) for item in cart_items)
        item_count = sum(int(item.get("quantity", 1)) for item in cart_items)
        shipping = calculate_shipping(subtotal, self._settings)
        threshold = float(self._settings.shipping_free_threshold_gbp)
        gap = None if shipping.free_shipping else round(max(0.0, threshold - subtotal), 2)
        return CartSummary(
            subtotal_gbp=round(subtotal, 2),
            item_count=item_count,
            shipping=shipping,
            amount_to_free_delivery_gbp=gap,
        )

    def product_by_slug(self, snapshot: WebsiteKnowledgeSnapshot, slug: str) -> Product | None:
        for product in snapshot.products:
            if product.slug == slug:
                return product
        return None

    def active_free_delivery_promotion(self, snapshot: WebsiteKnowledgeSnapshot) -> Promotion | None:
        for promo in snapshot.promotions:
            if promo.discount_type == "free_shipping" and promo.is_currently_active():
                return promo
        return None

    def promotion_lines(self, snapshot: WebsiteKnowledgeSnapshot) -> list[str]:
        lines: list[str] = []
        for promo in snapshot.promotions:
            if not promo.is_currently_active():
                continue
            text = promo.description.strip() or promo.name
            if promo.min_spend_gbp and promo.discount_type == "free_shipping":
                text = (
                    f"{promo.name}: {text} (orders over £{promo.min_spend_gbp:.2f})"
                    if promo.name not in text
                    else text
                )
            lines.append(text)
        return lines

    def build_ai_context(self, snapshot: WebsiteKnowledgeSnapshot, cart: CartSummary | None = None) -> str:
        lines = [
            f"Store: DRUVO UK ({snapshot.site_url})",
            f"Contact: {snapshot.policies.contact_email}",
            snapshot.policies.delivery_summary,
            snapshot.policies.returns_summary,
            snapshot.policies.payment_methods,
            f"Standard shipping £{snapshot.shipping_standard_gbp:.2f}; "
            f"free delivery from £{snapshot.shipping_free_threshold_gbp:.2f}.",
        ]
        promo_lines = self.promotion_lines(snapshot)
        if promo_lines:
            lines.append("ACTIVE PROMOTIONS (only mention these — never invent others):")
            lines.extend(f"- {p}" for p in promo_lines)
        else:
            lines.append("ACTIVE PROMOTIONS: none currently configured.")

        if cart and cart.item_count:
            lines.append(
                f"CUSTOMER BASKET: £{cart.subtotal_gbp:.2f} subtotal ({cart.item_count} items). "
                f"Shipping would be £{cart.shipping.shipping_gbp:.2f}."
            )
            if cart.amount_to_free_delivery_gbp is not None and cart.amount_to_free_delivery_gbp > 0:
                lines.append(
                    f"Customer is £{cart.amount_to_free_delivery_gbp:.2f} away from free delivery "
                    f"(threshold £{snapshot.shipping_free_threshold_gbp:.2f})."
                )

        if snapshot.degraded:
            lines.append("CATALOG: temporarily unavailable — do not quote prices or stock.")
        else:
            lines.append(f"LIVE PRODUCTS ({len(snapshot.live_products)} for sale):")
            for product in snapshot.live_products[:50]:
                lines.append(self._product_context_line(product, snapshot.site_url))
            demo_count = len(snapshot.products) - len(snapshot.live_products)
            if demo_count:
                lines.append(
                    f"Note: {demo_count} demo/development products exist but must NOT be offered for sale."
                )
        lines.append(
            "Never invent products, prices, stock, offers, coupon codes, or policies. "
            "If unsure, say you cannot confirm and suggest contacting support or browsing /shop."
        )
        return "\n".join(lines)

    @staticmethod
    def _product_context_line(product: Product, site_url: str) -> str:
        if not is_live_catalog_product(product):
            return f"- {product.name} [DEMO — NOT FOR SALE]"
        variants = []
        for v in product.variants:
            status = "in stock" if v.stock_quantity > 0 else "out"
            variants.append(f"{v.size}/{v.colour} £{v.price_gbp:.2f} qty={v.stock_quantity} ({status})")
        price_bit = f"£{product.display_price_gbp:.2f}"
        if product.is_on_sale and product.compare_at_price_gbp:
            price_bit = f"£{product.display_price_gbp:.2f} (was £{product.compare_at_price_gbp:.2f})"
        return (
            f"- {product.name} | {product.brand} | {product.category_name} | {price_bit} | "
            f"stock={product.total_stock} | {product.condition} | "
            f"URL: {site_url}/product/{product.slug} | variants: {'; '.join(variants) or 'none'}"
        )

"""Secure commerce tools for DRUVO Chat OpenAI function calling."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.services.catalog_visibility import is_live_catalog_product
from app.services.chat_commerce_service import ChatCommerceService, ChatProductCard
from app.services.shipping_service import calculate_shipping
from app.services.website_knowledge_service import CartSummary, WebsiteKnowledgeService, WebsiteKnowledgeSnapshot
from app.types.commerce import Product


_INJECTION_PATTERNS = (
    r"ignore (all )?(previous|prior|above) instructions",
    r"system prompt",
    r"you are now",
    r"reveal (the )?(api|secret|password|margin|supplier|wholesale)",
    r"manager report",
    r"internal (database|infra)",
)


@dataclass
class ChatToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    products: list[ChatProductCard] = field(default_factory=list)
    context_product_slugs: list[str] = field(default_factory=list)
    error: str = ""


class ChatToolExecutor:
    """Execute read-only customer-safe commerce tools."""

    MAX_SEARCH = 8
    MAX_COMPARE = 4

    def __init__(
        self,
        knowledge: WebsiteKnowledgeService | None = None,
        commerce: ChatCommerceService | None = None,
    ) -> None:
        self._knowledge = knowledge or WebsiteKnowledgeService()
        self._commerce = commerce or ChatCommerceService(self._knowledge)

    @staticmethod
    def tool_schemas() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_products",
                    "description": "Search live DRUVO products by keywords, size, colour, price range.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search text e.g. tracksuit cream"},
                            "size": {"type": "string"},
                            "colour": {"type": "string"},
                            "max_price_gbp": {"type": "number"},
                            "in_stock_only": {"type": "boolean"},
                            "sort": {"type": "string", "enum": ["featured", "price_asc", "price_desc", "newest"]},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_product_details",
                    "description": "Get full details for one live product by slug or name hint.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slug": {"type": "string"},
                            "name_hint": {"type": "string"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_variant_stock",
                    "description": "Check if a specific size/colour variant is in stock for a product.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slug": {"type": "string"},
                            "size": {"type": "string"},
                            "colour": {"type": "string"},
                        },
                        "required": ["slug"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compare_products",
                    "description": "Compare up to 4 live products side by side.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "slugs": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["slugs"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "recommend_products",
                    "description": "Recommend live in-stock products, optionally cheaper alternatives.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "cheaper_than_gbp": {"type": "number"},
                            "limit": {"type": "integer"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_offers",
                    "description": "List active promotions and offers configured on DRUVO UK.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_delivery_policy",
                    "description": "UK delivery policy summary and free-delivery threshold.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "calculate_delivery",
                    "description": "Calculate shipping for a basket subtotal or product price.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "subtotal_gbp": {"type": "number"},
                            "product_slug": {"type": "string"},
                            "quantity": {"type": "integer"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_returns_policy",
                    "description": "Returns and refund policy summary.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_payment_information",
                    "description": "Accepted payment methods and checkout security summary.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_basket_context",
                    "description": "Summarise the customer's current basket from session cart data.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_business_information",
                    "description": "General DRUVO UK store information (contact, hours-style FAQs). No private data.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string", "enum": ["contact", "about", "hours", "location"]},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "initiate_order_lookup",
                    "description": (
                        "Start secure order tracking — customer must provide order reference and checkout email. "
                        "Never returns order details directly."
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    @staticmethod
    def looks_like_injection(text: str) -> bool:
        lower = text.lower()
        return any(re.search(p, lower) for p in _INJECTION_PATTERNS)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict] | None = None,
        last_slugs: list[str] | None = None,
    ) -> ChatToolResult:
        if snapshot.degraded and name not in {
            "get_delivery_policy",
            "get_returns_policy",
            "get_payment_information",
            "get_business_information",
            "initiate_order_lookup",
        }:
            return ChatToolResult(
                ok=False,
                error="Our live catalogue is temporarily unavailable. Policies and contact info still apply.",
            )

        handlers = {
            "search_products": self._search_products,
            "get_product_details": self._get_product_details,
            "check_variant_stock": self._check_variant_stock,
            "compare_products": self._compare_products,
            "recommend_products": self._recommend_products,
            "get_current_offers": self._get_current_offers,
            "get_delivery_policy": self._get_delivery_policy,
            "calculate_delivery": self._calculate_delivery,
            "get_returns_policy": self._get_returns_policy,
            "get_payment_information": self._get_payment_information,
            "get_basket_context": self._get_basket_context,
            "get_business_information": self._get_business_information,
            "initiate_order_lookup": self._initiate_order_lookup,
        }
        fn = handlers.get(name)
        if not fn:
            return ChatToolResult(ok=False, error=f"Unknown tool: {name}")
        return await fn(arguments, snapshot=snapshot, cart_items=cart_items or [], last_slugs=last_slugs or [])

    def _cards(self, products: list[Product], site_url: str) -> tuple[list[ChatProductCard], list[str]]:
        cards = [self._commerce.product_card(p, site_url) for p in products if is_live_catalog_product(p)]
        slugs = [p.slug for p in products if is_live_catalog_product(p)]
        return cards, slugs

    def _resolve_slug(
        self,
        snapshot: WebsiteKnowledgeSnapshot,
        slug: str = "",
        name_hint: str = "",
        last_slugs: list[str] | None = None,
    ) -> Product | None:
        if slug:
            p = self._knowledge.product_by_slug(snapshot, slug.strip())
            if p and is_live_catalog_product(p):
                return p
        if name_hint:
            hint = name_hint.lower()
            for p in snapshot.live_products:
                if hint in p.name.lower() or hint in p.slug.replace("-", " "):
                    return p
        if last_slugs:
            p = self._knowledge.product_by_slug(snapshot, last_slugs[0])
            if p and is_live_catalog_product(p):
                return p
        return None

    def _filter_live_products(
        self,
        snapshot: WebsiteKnowledgeSnapshot,
        *,
        query: str = "",
        size: str | None = None,
        colour: str | None = None,
        max_price: float | None = None,
        in_stock_only: bool = False,
    ) -> list[Product]:
        items = list(snapshot.live_products)
        q = (query or "").lower()
        if q:
            items = [
                p for p in items
                if q in p.name.lower()
                or q in p.slug.replace("-", " ")
                or q in (p.brand or "").lower()
                or q in (p.category_name or "").lower()
            ]
        if size:
            s = size.lower()
            items = [p for p in items if any(v.size.lower() == s or s in v.size.lower() for v in p.variants)]
        if colour:
            c = colour.lower()
            items = [p for p in items if any(c in v.colour.lower() for v in p.variants)]
        if max_price is not None:
            items = [p for p in items if p.display_price_gbp <= float(max_price)]
        if in_stock_only:
            items = [p for p in items if p.in_stock]
        return items

    async def _search_products(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        products = self._filter_live_products(
            snapshot,
            query=args.get("query") or "",
            size=args.get("size"),
            colour=args.get("colour"),
            max_price=args.get("max_price_gbp"),
            in_stock_only=bool(args.get("in_stock_only", False)),
        )
        if not products and (args.get("query") or args.get("size") or args.get("colour")):
            products = await self._knowledge.search_live_products(
                args.get("query") or "",
                size=args.get("size"),
                colour=args.get("colour"),
                max_price=args.get("max_price_gbp"),
                in_stock_only=bool(args.get("in_stock_only", False)),
                sort=args.get("sort") or "featured",
            )
        products = products[: self.MAX_SEARCH]
        cards, slugs = self._cards(products, snapshot.site_url)
        items = [
            {
                "slug": p.slug,
                "name": p.name,
                "price_gbp": p.display_price_gbp,
                "in_stock": p.in_stock,
                "sizes": p.sizes,
                "colours": p.colours,
                "url": f"{snapshot.site_url}/product/{p.slug}",
            }
            for p in products
        ]
        return ChatToolResult(ok=True, data={"count": len(items), "products": items}, products=cards, context_product_slugs=slugs)

    async def _get_product_details(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        product = self._resolve_slug(snapshot, args.get("slug", ""), args.get("name_hint", ""), last_slugs)
        if not product:
            return ChatToolResult(ok=False, error="Product not found in live catalogue.")
        card = self._commerce.product_card(product, snapshot.site_url)
        variants = [
            {
                "size": v.size,
                "colour": v.colour,
                "sku": v.sku,
                "price_gbp": v.price_gbp,
                "stock_quantity": v.stock_quantity,
                "in_stock": v.in_stock,
            }
            for v in product.variants
        ]
        return ChatToolResult(
            ok=True,
            data={
                "slug": product.slug,
                "name": product.name,
                "description": product.description[:500],
                "brand": product.brand,
                "price_gbp": product.display_price_gbp,
                "compare_at_price_gbp": product.compare_at_price_gbp,
                "is_on_sale": product.is_on_sale,
                "in_stock": product.in_stock,
                "variants": variants,
                "url": f"{snapshot.site_url}/product/{product.slug}",
            },
            products=[card],
            context_product_slugs=[product.slug],
        )

    async def _check_variant_stock(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        product = self._resolve_slug(snapshot, args.get("slug", ""), "", last_slugs)
        if not product:
            return ChatToolResult(ok=False, error="Product not found.")
        size = (args.get("size") or "").strip().lower()
        colour = (args.get("colour") or "").strip().lower()
        matches = []
        for v in product.variants:
            if size and v.size.lower() != size and size not in v.size.lower():
                continue
            if colour and colour not in v.colour.lower():
                continue
            matches.append(v)
        if not matches and (size or colour):
            return ChatToolResult(
                ok=True,
                data={
                    "slug": product.slug,
                    "name": product.name,
                    "available": False,
                    "message": f"No matching variant for size={size or 'any'} colour={colour or 'any'}",
                    "other_sizes": sorted({v.size for v in product.variants if v.in_stock}),
                    "other_colours": sorted({v.colour for v in product.variants if v.in_stock}),
                },
                context_product_slugs=[product.slug],
            )
        in_stock = [v for v in (matches or product.variants) if v.in_stock]
        return ChatToolResult(
            ok=True,
            data={
                "slug": product.slug,
                "name": product.name,
                "available": bool(in_stock),
                "variants": [
                    {"size": v.size, "colour": v.colour, "price_gbp": v.price_gbp, "stock": v.stock_quantity}
                    for v in (in_stock or matches or product.variants[:5])
                ],
            },
            context_product_slugs=[product.slug],
        )

    async def _compare_products(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        slugs = (args.get("slugs") or [])[: self.MAX_COMPARE]
        compared = []
        cards: list[ChatProductCard] = []
        for slug in slugs:
            p = self._knowledge.product_by_slug(snapshot, slug)
            if p and is_live_catalog_product(p):
                compared.append(
                    {
                        "slug": p.slug,
                        "name": p.name,
                        "price_gbp": p.display_price_gbp,
                        "in_stock": p.in_stock,
                        "sizes": p.sizes,
                        "colours": p.colours,
                        "condition": p.condition,
                    }
                )
                cards.append(self._commerce.product_card(p, snapshot.site_url))
        return ChatToolResult(ok=True, data={"products": compared}, products=cards, context_product_slugs=slugs)

    async def _recommend_products(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        limit = min(int(args.get("limit") or 3), 5)
        cheaper = args.get("cheaper_than_gbp")
        products = self._filter_live_products(
            snapshot,
            query=args.get("query") or "",
            max_price=float(cheaper) - 0.01 if cheaper is not None else None,
            in_stock_only=True,
        )
        if cheaper is not None:
            products = [p for p in products if p.display_price_gbp < float(cheaper)]
        if not products:
            products = await self._knowledge.search_live_products(
                args.get("query") or "",
                in_stock_only=True,
                sort="price_asc" if cheaper else "featured",
            )
            if cheaper is not None:
                products = [p for p in products if p.display_price_gbp < float(cheaper)]
        products = products[:limit]
        cards, slugs = self._cards(products, snapshot.site_url)
        return ChatToolResult(
            ok=True,
            data={
                "recommendations": [
                    {"slug": p.slug, "name": p.name, "price_gbp": p.display_price_gbp, "in_stock": p.in_stock}
                    for p in products
                ]
            },
            products=cards,
            context_product_slugs=slugs,
        )

    async def _get_current_offers(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        lines = self._knowledge.promotion_lines(snapshot)
        return ChatToolResult(ok=True, data={"offers": lines or ["No active promotions right now."]})

    async def _get_delivery_policy(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        return ChatToolResult(
            ok=True,
            data={
                "summary": snapshot.policies.delivery_summary,
                "standard_shipping_gbp": snapshot.shipping_standard_gbp,
                "free_delivery_from_gbp": snapshot.shipping_free_threshold_gbp,
            },
        )

    async def _calculate_delivery(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        subtotal = float(args.get("subtotal_gbp") or 0)
        slug = args.get("product_slug")
        qty = int(args.get("quantity") or 1)
        if slug and not subtotal:
            p = self._resolve_slug(snapshot, slug, "", last_slugs)
            if p:
                subtotal = p.display_price_gbp * qty
        elif cart_items and not subtotal:
            subtotal = sum(float(i.get("price_gbp", 0)) * int(i.get("quantity", 1)) for i in cart_items)
        quote = calculate_shipping(subtotal, self._knowledge.settings)
        return ChatToolResult(
            ok=True,
            data={
                **quote.as_dict(),
                "delivered_total_gbp": round(subtotal + quote.shipping_gbp, 2),
                "free_delivery_threshold_gbp": snapshot.shipping_free_threshold_gbp,
            },
        )

    async def _get_returns_policy(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        return ChatToolResult(ok=True, data={"summary": snapshot.policies.returns_summary})

    async def _get_payment_information(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        return ChatToolResult(ok=True, data={"summary": snapshot.policies.payment_methods})

    async def _get_basket_context(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        if not cart_items:
            return ChatToolResult(ok=True, data={"empty": True, "message": "Basket is empty."})
        cart = self._knowledge.cart_summary(cart_items)
        return ChatToolResult(
            ok=True,
            data={
                "subtotal_gbp": cart.subtotal_gbp,
                "item_count": cart.item_count,
                "shipping_gbp": cart.shipping.shipping_gbp,
                "total_gbp": cart.shipping.total_gbp,
                "amount_to_free_delivery_gbp": cart.amount_to_free_delivery_gbp,
            },
        )

    async def _get_business_information(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        topic = (args.get("topic") or "contact").lower()
        email = snapshot.policies.contact_email
        if topic == "contact":
            text = f"Contact DRUVO UK at {email} or use the contact form on druvo.uk."
        elif topic == "location":
            text = "DRUVO UK is an online store serving customers throughout the United Kingdom."
        else:
            text = f"DRUVO UK is an online fashion retailer. For help, contact {email}."
        return ChatToolResult(ok=True, data={"topic": topic, "summary": text})

    async def _initiate_order_lookup(
        self,
        args: dict,
        *,
        snapshot: WebsiteKnowledgeSnapshot,
        cart_items: list[dict],
        last_slugs: list[str],
    ) -> ChatToolResult:
        return ChatToolResult(
            ok=True,
            data={
                "action": "order_lookup_flow",
                "message": (
                    "To track an order securely, please provide your order reference (e.g. WEB-...) "
                    f"and the email address used at checkout. You can also sign in at /account/login."
                ),
            },
        )

    @staticmethod
    def slim_system_context(snapshot: WebsiteKnowledgeSnapshot) -> str:
        """Policies-only context — products fetched via tools."""
        lines = [
            f"Store: DRUVO UK ({snapshot.site_url})",
            f"Contact: {snapshot.policies.contact_email}",
            f"Live products available: {len(snapshot.live_products)}",
            snapshot.policies.delivery_summary,
            snapshot.policies.returns_summary,
            "Use tools to retrieve product/stock/price facts. Never invent catalogue data.",
            "Never reveal supplier costs, margins, internal systems, or other customers' orders.",
        ]
        if snapshot.degraded:
            lines.append("CATALOG STATUS: temporarily unavailable — do not quote products until tools succeed.")
        return "\n".join(lines)

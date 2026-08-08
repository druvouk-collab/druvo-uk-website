"""DRUVO Chat commerce intelligence — product search, policies, promotions, basket."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.catalog_visibility import is_live_catalog_product
from app.services.website_knowledge_service import CartSummary, WebsiteKnowledgeService, WebsiteKnowledgeSnapshot
from app.types.commerce import Product, ProductVariant


@dataclass(frozen=True)
class ChatProductCard:
    slug: str
    name: str
    image: str
    price_gbp: float
    compare_at_price_gbp: float | None
    is_on_sale: bool
    in_stock: bool
    sizes: list[str]
    colours: list[str]
    url: str
    brand: str = ""
    sku: str = ""
    variant_id: int | None = None
    stock_total: int = 0

    def as_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "image": self.image,
            "price_gbp": self.price_gbp,
            "compare_at_price_gbp": self.compare_at_price_gbp,
            "is_on_sale": self.is_on_sale,
            "in_stock": self.in_stock,
            "sizes": self.sizes,
            "colours": self.colours,
            "url": self.url,
            "brand": self.brand,
            "sku": self.sku,
            "variant_id": self.variant_id,
            "stock_total": self.stock_total,
        }


@dataclass
class ChatCommerceReply:
    text: str
    products: list[ChatProductCard] = field(default_factory=list)
    context_product_slugs: list[str] = field(default_factory=list)
    add_to_cart: dict | None = None


class ChatCommerceService:
    def __init__(self, knowledge: WebsiteKnowledgeService | None = None) -> None:
        self._knowledge = knowledge or WebsiteKnowledgeService()

    async def load_snapshot(self) -> WebsiteKnowledgeSnapshot:
        return await self._knowledge.load()

    def product_card(self, product: Product, site_url: str) -> ChatProductCard:
        variant = product.first_in_stock_variant()
        in_stock_sizes = sorted({v.size for v in product.variants if v.stock_quantity > 0})
        in_stock_colours = sorted({v.colour for v in product.variants if v.stock_quantity > 0})
        return ChatProductCard(
            slug=product.slug,
            name=product.name,
            image=product.images[0] if product.images else "/static/images/placeholder-product.svg",
            price_gbp=product.display_price_gbp,
            compare_at_price_gbp=product.compare_at_price_gbp if product.is_on_sale else None,
            is_on_sale=product.is_on_sale,
            in_stock=product.in_stock,
            sizes=in_stock_sizes,
            colours=in_stock_colours,
            url=f"{site_url}/product/{product.slug}",
            brand=product.brand,
            sku=variant.sku if variant else "",
            variant_id=variant.variant_id if variant else None,
            stock_total=product.total_stock,
        )

    def resolve_context_product(
        self,
        message: str,
        snapshot: WebsiteKnowledgeSnapshot,
        last_slugs: list[str],
    ) -> Product | None:
        lower = message.lower().strip()
        if re.search(r"\b(open it|take me there|show me that|that one|the second one|the first one)\b", lower):
            if "second" in lower and len(last_slugs) >= 2:
                return self._knowledge.product_by_slug(snapshot, last_slugs[1])
            if last_slugs:
                return self._knowledge.product_by_slug(snapshot, last_slugs[0])
        return None

    async def answer(
        self,
        message: str,
        snapshot: WebsiteKnowledgeSnapshot,
        *,
        cart_items: list[dict] | None = None,
        last_slugs: list[str] | None = None,
    ) -> ChatCommerceReply | None:
        cart = self._knowledge.cart_summary(cart_items or []) if cart_items else None
        lower = message.lower()
        email = snapshot.policies.contact_email

        context_product = self.resolve_context_product(message, snapshot, last_slugs or [])
        if context_product and is_live_catalog_product(context_product):
            card = self.product_card(context_product, snapshot.site_url)
            return ChatCommerceReply(
                text=self._format_product_detail(context_product, snapshot.site_url),
                products=[card],
                context_product_slugs=[context_product.slug],
            )

        if any(w in lower for w in ("delivery", "shipping", "postage", "dispatch")):
            return ChatCommerceReply(text=self._delivery_answer(snapshot, cart))

        if any(w in lower for w in ("return", "refund", "exchange")):
            return ChatCommerceReply(text=snapshot.policies.returns_summary)

        if any(w in lower for w in ("payment", "stripe", "checkout", "pay", "card")):
            return ChatCommerceReply(text=snapshot.policies.payment_methods)

        if any(w in lower for w in ("contact", "email", "support", "human")):
            return ChatCommerceReply(text=f"You can reach DRUVO UK at {email}.")

        if snapshot.degraded:
            return ChatCommerceReply(
                text=(
                    "Our live product catalogue is temporarily unavailable, so I can't check stock or prices right now. "
                    f"Please try again shortly, or email {email}."
                )
            )

        if self._is_free_delivery_gap_question(lower) and cart and cart.item_count:
            return ChatCommerceReply(text=self._free_delivery_gap_answer(snapshot, cart))

        if self._is_promotion_question(lower):
            return ChatCommerceReply(text=self._promotion_answer(snapshot))

        if self._is_sale_question(lower):
            return self._sale_products_answer(snapshot)

        if self._is_cheapest_question(lower):
            return self._cheapest_answer(message, snapshot)

        if price_cap := self._extract_max_price(lower):
            return self._under_price_answer(price_cap, snapshot)

        matched = self._match_products(message, snapshot.live_products)
        if matched:
            return self._products_answer(message, matched, snapshot)

        if any(w in lower for w in ("product", "stock", "available", "size", "colour", "color", "price", "left")):
            if snapshot.live_products:
                names = ", ".join(p.name for p in snapshot.live_products[:5])
                return ChatCommerceReply(
                    text=(
                        f"I couldn't find an exact match in our live catalogue. Browse /shop or try a product name. "
                        f"Live items include: {names}. For help, email {email}."
                    )
                )

        return None

    def _delivery_answer(self, snapshot: WebsiteKnowledgeSnapshot, cart: CartSummary | None) -> str:
        base = snapshot.policies.delivery_summary
        promo = self._knowledge.active_free_delivery_promotion(snapshot)
        if promo and promo.description and promo.description not in base:
            base = f"{base} {promo.description}"
        if cart and cart.amount_to_free_delivery_gbp is not None and cart.amount_to_free_delivery_gbp > 0:
            base += (
                f" Your basket is £{cart.subtotal_gbp:.2f} — "
                f"you're £{cart.amount_to_free_delivery_gbp:.2f} away from free delivery."
            )
        elif cart and cart.shipping.free_shipping and cart.item_count:
            base += " Your current basket qualifies for free delivery."
        return base

    @staticmethod
    def _free_delivery_gap_answer(snapshot: WebsiteKnowledgeSnapshot, cart: CartSummary) -> str:
        if cart.shipping.free_shipping:
            return "Your current basket already qualifies for free UK delivery."
        gap = cart.amount_to_free_delivery_gbp or 0
        if gap <= 0:
            return f"Free delivery applies on orders over £{snapshot.shipping_free_threshold_gbp:.2f}."
        return (
            f"You're £{gap:.2f} away from free delivery "
            f"(free on orders over £{snapshot.shipping_free_threshold_gbp:.2f}). "
            "Would you like me to show you something to help reach the threshold?"
        )

    def _promotion_answer(self, snapshot: WebsiteKnowledgeSnapshot) -> str:
        lines = self._knowledge.promotion_lines(snapshot)
        if not lines:
            return (
                "We don't have any special promotions active on druvo.uk right now. "
                "Browse /shop for our current live catalogue."
            )
        return "Current offers on DRUVO UK:\n\n" + "\n".join(f"• {line}" for line in lines)

    def _sale_products_answer(self, snapshot: WebsiteKnowledgeSnapshot) -> ChatCommerceReply:
        on_sale = [p for p in snapshot.live_products if p.is_on_sale and p.in_stock]
        if not on_sale:
            return ChatCommerceReply(
                text="We don't currently have any items marked on sale in our live catalogue.",
            )
        cards = [self.product_card(p, snapshot.site_url) for p in on_sale[:3]]
        parts = [self._format_product_detail(p, snapshot.site_url) for p in on_sale[:3]]
        suffix = "" if len(on_sale) <= 3 else f"\n\n({len(on_sale) - 3} more on sale — see /sale)"
        return ChatCommerceReply(
            text="\n\n".join(parts) + suffix,
            products=cards,
            context_product_slugs=[p.slug for p in on_sale[:3]],
        )

    def _cheapest_answer(self, message: str, snapshot: WebsiteKnowledgeSnapshot) -> ChatCommerceReply:
        products = snapshot.live_products
        tokens = self._category_tokens(message)
        if tokens:
            products = [
                p for p in products
                if any(t in p.category_name.lower() or t in p.name.lower() for t in tokens)
            ]
        in_stock = [p for p in products if p.in_stock]
        if not in_stock:
            return ChatCommerceReply(
                text="I couldn't find any in-stock live products matching that category right now.",
            )
        cheapest = min(in_stock, key=lambda p: p.display_price_gbp)
        card = self.product_card(cheapest, snapshot.site_url)
        return ChatCommerceReply(
            text=(
                f"The cheapest matching item we have live right now is **{cheapest.name}** "
                f"at £{cheapest.display_price_gbp:.2f}."
                + (
                    f" (Reduced from £{cheapest.compare_at_price_gbp:.2f}.)"
                    if cheapest.is_on_sale and cheapest.compare_at_price_gbp
                    else ""
                )
                + f"\n\n{self._format_product_detail(cheapest, snapshot.site_url)}"
            ),
            products=[card],
            context_product_slugs=[cheapest.slug],
        )

    def _under_price_answer(self, max_price: float, snapshot: WebsiteKnowledgeSnapshot) -> ChatCommerceReply:
        matches = [
            p for p in snapshot.live_products
            if p.in_stock and p.display_price_gbp <= max_price
        ]
        matches.sort(key=lambda p: p.display_price_gbp)
        if not matches:
            return ChatCommerceReply(
                text=f"We don't currently have any in-stock live items at or under £{max_price:.2f}.",
            )
        cards = [self.product_card(p, snapshot.site_url) for p in matches[:3]]
        parts = [self._format_product_detail(p, snapshot.site_url) for p in matches[:3]]
        suffix = "" if len(matches) <= 3 else f"\n\n({len(matches) - 3} more under £{max_price:.0f} — try /shop)"
        return ChatCommerceReply(
            text="\n\n".join(parts) + suffix,
            products=cards,
            context_product_slugs=[p.slug for p in matches[:3]],
        )

    def _products_answer(
        self,
        message: str,
        matched: list[Product],
        snapshot: WebsiteKnowledgeSnapshot,
    ) -> ChatCommerceReply:
        live_matched = [p for p in matched if is_live_catalog_product(p)]
        demo_matched = [p for p in matched if not is_live_catalog_product(p)]

        if not live_matched and demo_matched:
            return ChatCommerceReply(
                text=(
                    f"I found **{demo_matched[0].name}** on the website, but it's a development/demo sample "
                    "and is not available to purchase. Browse /shop for live items."
                ),
            )

        target = live_matched[:3]
        size = self._extract_size(message)
        colour = self._extract_colour(message, target[0] if target else None)

        if len(target) == 1:
            product = target[0]
            if any(w in message.lower() for w in ("how much", "price", "cost")):
                return ChatCommerceReply(
                    text=self._price_answer(product, size, colour),
                    products=[self.product_card(product, snapshot.site_url)],
                    context_product_slugs=[product.slug],
                )
            if any(w in message.lower() for w in ("how many", "left", "stock", "available")):
                return ChatCommerceReply(
                    text=self._stock_answer(product, size, colour),
                    products=[self.product_card(product, snapshot.site_url)],
                    context_product_slugs=[product.slug],
                )
            if size or colour:
                return ChatCommerceReply(
                    text=self._variant_answer(product, size, colour),
                    products=[self.product_card(product, snapshot.site_url)],
                    context_product_slugs=[product.slug],
                )

        cards = [self.product_card(p, snapshot.site_url) for p in target]
        parts = [self._format_product_detail(p, snapshot.site_url) for p in target]
        suffix = "" if len(live_matched) <= 3 else f"\n\n({len(live_matched) - 3} more matches — try /search)"
        return ChatCommerceReply(
            text="\n\n".join(parts) + suffix,
            products=cards,
            context_product_slugs=[p.slug for p in target],
        )

    @staticmethod
    def _format_product_detail(product: Product, site_url: str) -> str:
        card_url = f"{site_url}/product/{product.slug}"
        price_line = f"**{product.name}** — £{product.display_price_gbp:.2f}"
        if product.is_on_sale and product.compare_at_price_gbp:
            price_line += f" (was £{product.compare_at_price_gbp:.2f})"
        stock = "In stock" if product.in_stock else "Out of stock"
        lines = [f"{price_line} ({stock})."]
        if product.brand:
            lines.append(f"Brand: {product.brand}.")
        lines.append(f"Category: {product.category_name}. Condition: {product.condition}.")
        sizes = sorted({v.size for v in product.variants if v.stock_quantity > 0})
        colours = sorted({v.colour for v in product.variants if v.stock_quantity > 0})
        if sizes:
            lines.append(f"Sizes in stock: {', '.join(sizes)}.")
        if colours:
            lines.append(f"Colours in stock: {', '.join(colours)}.")
        lines.append(f"View product: {card_url}")
        return "\n".join(lines)

    @staticmethod
    def _price_answer(product: Product, size: str, colour: str) -> str:
        variant = ChatCommerceService._find_variant(product, size, colour)
        if variant:
            return (
                f"**{product.name}** ({variant.size}/{variant.colour}) is £{variant.price_gbp:.2f}. "
                f"{'In stock' if variant.in_stock else 'Out of stock'} ({variant.stock_quantity} left)."
            )
        if product.is_on_sale and product.compare_at_price_gbp:
            return (
                f"**{product.name}** is currently £{product.display_price_gbp:.2f} "
                f"(reduced from £{product.compare_at_price_gbp:.2f})."
            )
        return f"**{product.name}** is £{product.display_price_gbp:.2f}."

    @staticmethod
    def _stock_answer(product: Product, size: str, colour: str) -> str:
        variant = ChatCommerceService._find_variant(product, size, colour)
        if variant:
            if variant.stock_quantity <= 0:
                return f"Sorry, **{product.name}** in {variant.size}/{variant.colour} is out of stock."
            return (
                f"We have **{variant.stock_quantity}** of **{product.name}** "
                f"({variant.size}/{variant.colour}) in stock."
            )
        if product.total_stock <= 0:
            return f"**{product.name}** is currently out of stock across all variants."
        return f"**{product.name}** has **{product.total_stock}** units in stock across available variants."

    @staticmethod
    def _variant_answer(product: Product, size: str, colour: str) -> str:
        if size and colour:
            variant = product.variant_for(size, colour)
            if not variant:
                return f"**{product.name}** isn't listed in {size}/{colour}."
            if variant.stock_quantity <= 0:
                return f"Sorry, **{product.name}** in {size}/{colour} is out of stock."
            return f"Yes — **{product.name}** is available in {size}/{colour} (£{variant.price_gbp:.2f}, {variant.stock_quantity} left)."
        if size:
            colours = product.colours_for_size(size)
            if not colours:
                return f"Sorry, we don't have **{product.name}** in size {size} in stock right now."
            return f"**{product.name}** in size {size} is available in: {', '.join(colours)}."
        if colour:
            sizes = product.sizes_for_colour(colour)
            if not sizes:
                return f"Sorry, we don't have **{product.name}** in {colour} in stock right now."
            return f"**{product.name}** in {colour} is available in sizes: {', '.join(sizes)}."
        return ChatCommerceService._format_product_detail(product, "")

    @staticmethod
    def _find_variant(product: Product, size: str, colour: str) -> ProductVariant | None:
        if size and colour:
            return product.variant_for(size, colour)
        if size:
            for v in product.variants:
                if v.size.lower() == size.lower() and v.in_stock:
                    return v
        if colour:
            for v in product.variants:
                if v.colour.lower() == colour.lower() and v.in_stock:
                    return v
        return product.first_in_stock_variant()

    @staticmethod
    def _match_products(message: str, products: list[Product]) -> list[Product]:
        tokens = [t for t in re.findall(r"[a-z0-9]+", message.lower()) if len(t) > 2]
        stop = {"have", "much", "what", "does", "this", "that", "with", "your", "about", "show", "tell", "the", "you", "are"}
        tokens = [t for t in tokens if t not in stop]
        if not tokens:
            return []
        scored: list[tuple[int, Product]] = []
        for product in products:
            hay = " ".join(
                [product.name, product.brand, product.description, product.category_name, *product.tags]
            ).lower()
            score = sum(1 for token in tokens if token in hay)
            if score:
                scored.append((score, product))
        scored.sort(key=lambda x: (-x[0], x[1].name.lower()))
        return [p for _, p in scored[:5]]

    @staticmethod
    def _extract_max_price(lower: str) -> float | None:
        match = re.search(r"under\s*£?\s*(\d+(?:\.\d+)?)", lower)
        if match:
            return float(match.group(1))
        match = re.search(r"below\s*£?\s*(\d+(?:\.\d+)?)", lower)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _extract_size(message: str) -> str:
        match = re.search(r"\b(XXS|XS|S|M|L|XL|XXL|XXXL|\d{1,2})\b", message, re.I)
        return match.group(1).upper() if match else ""

    @staticmethod
    def _extract_colour(message: str, product: Product | None) -> str:
        lower = message.lower()
        known = {"black", "white", "navy", "blue", "red", "green", "grey", "gray", "cream", "beige", "brown", "pink"}
        if product:
            known.update(c.lower() for c in product.colours)
        for colour in sorted(known, key=len, reverse=True):
            if colour in lower:
                return colour.title() if colour != "gray" else "Grey"
        return ""

    @staticmethod
    def _category_tokens(message: str) -> list[str]:
        lower = message.lower()
        for word in ("cheapest", "cheap", "lowest", "price", "which", "what"):
            lower = lower.replace(word, "")
        return [t for t in re.findall(r"[a-z]+", lower) if len(t) > 3]

    @staticmethod
    def _is_sale_question(lower: str) -> bool:
        return any(w in lower for w in ("on sale", "special offer", "reduced", "discount", "any offers"))

    @staticmethod
    def _is_promotion_question(lower: str) -> bool:
        return any(w in lower for w in ("promotion", "promo", "current offer", "any deals"))

    @staticmethod
    def _is_cheapest_question(lower: str) -> bool:
        return "cheapest" in lower or "lowest price" in lower

    @staticmethod
    def _is_free_delivery_gap_question(lower: str) -> bool:
        return "free delivery" in lower and any(w in lower for w in ("away", "how much more", "need to spend", "basket", "cart"))

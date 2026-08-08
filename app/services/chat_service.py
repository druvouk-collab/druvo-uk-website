"""DRUVO Chat — customer assistant with live catalog context."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings
from app.services.catalog_service import CatalogService
from app.services.catalog_visibility import is_live_catalog_product
from app.services.shipping_service import calculate_shipping
from app.types.commerce import Product

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LEN = 500
_MAX_HISTORY = 8
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_CONTACT_FALLBACK = (
    "I'm not sure about that one. Try browsing /shop, or email us at {email} "
    "and our team will be happy to help."
)

_CATALOG_UNAVAILABLE = (
    "Our live product catalogue is temporarily unavailable, so I can't check stock or prices right now. "
    "Please try again shortly, or email us at {email}."
)

_WELCOME = (
    "Hello! Welcome to DRUVO UK 👋 How can I help you today?"
)


def _conversational_reply(message: str) -> str | None:
    """Friendly replies for greetings and small talk — never catalogue fallbacks."""
    lower = message.lower().strip()

    if re.search(r"\bgood evening\b", lower):
        return "Good evening! Welcome to DRUVO UK 👋 How can I help you today?"
    if re.search(r"\bgood morning\b", lower):
        return "Good morning! Welcome to DRUVO UK 👋 How can I help you today?"
    if re.search(r"\bgood afternoon\b", lower):
        return "Good afternoon! Welcome to DRUVO UK 👋 How can I help you today?"
    if re.match(r"^(hi|hello|hey|hiya|howdy|yo)( there| druvo| uk)?[!.?\s]*$", lower):
        return _WELCOME
    if re.search(r"\b(thank you|thanks|cheers|much appreciated)\b", lower):
        return "You're welcome! Is there anything else I can help you with?"
    if re.match(r"^(bye|goodbye|good bye|see you|take care)[!.?\s]*$", lower) or re.search(
        r"\b(bye for now|goodbye)\b", lower
    ):
        return "Goodbye! Thanks for visiting DRUVO UK — we'd love to see you again soon."
    if re.search(r"\bhow are you\b", lower):
        return (
            "I'm doing well, thank you! I'm here to help with DRUVO UK products, delivery, "
            "returns and orders. What can I help you with?"
        )
    if re.search(r"\b(who are you|what are you)\b", lower):
        return (
            "I'm DRUVO Chat, the DRUVO UK shopping assistant. I can help with products, sizes, "
            "stock, delivery, returns and finding your orders."
        )
    if re.search(r"\b(what can you help|what do you do|how can you help|what can i ask)\b", lower):
        return (
            "I can help with product availability, sizes, colours, prices, UK delivery, returns, "
            "and how to find your orders. Just ask!"
        )
    return None


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatReply:
    reply: str
    source: str  # "openai" | "rules"


class ChatService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._catalog = CatalogService(self._settings)

    @property
    def welcome_message(self) -> str:
        return _WELCOME

    async def reply(self, message: str, history: list[ChatMessage] | None = None) -> ChatReply:
        cleaned = self._sanitize_message(message)
        if not cleaned:
            return ChatReply(
                reply="Please type a question and I'll do my best to help.",
                source="rules",
            )

        snapshot = await self._catalog.load_snapshot()
        products = snapshot.products
        context = self._build_context(products, snapshot.degraded)

        conversational = _conversational_reply(cleaned)
        if conversational:
            return ChatReply(reply=conversational, source="rules")

        if self._settings.openai_api_key:
            try:
                text = await self._ask_openai(cleaned, history or [], context)
                return ChatReply(reply=text, source="openai")
            except Exception as exc:
                logger.warning("OpenAI chat failed, falling back to rules: %s", type(exc).__name__)

        return ChatReply(reply=self._rules_reply(cleaned, products, snapshot.degraded), source="rules")

    def _sanitize_message(self, message: str) -> str:
        text = (message or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text[:_MAX_MESSAGE_LEN]

    def _build_context(self, products: list[Product], degraded: bool) -> str:
        shipping = calculate_shipping(0, self._settings)
        free_threshold = self._settings.shipping_free_threshold_gbp
        standard = self._settings.shipping_standard_gbp

        lines = [
            "DRUVO UK is a premium UK resale store for clothing, footwear, and accessories.",
            f"Contact email: {self._settings.contact_email}",
            f"Standard UK delivery: £{standard:.2f}. Free delivery on orders over £{free_threshold:.2f}.",
            "Delivery information page: /delivery",
            "Returns policy page: /returns",
            "Order lookup: customers can view orders at /account/login using their checkout email.",
            "Do NOT invent stock levels, prices, delivery dates, or order statuses.",
            "If catalog data is unavailable, say you cannot verify live stock and direct to contact email.",
        ]
        if degraded:
            lines.append("CATALOG STATUS: live catalog temporarily unavailable — do not quote product stock or prices.")
        else:
            live_count = sum(1 for p in products if is_live_catalog_product(p))
            lines.append(
                f"CATALOG STATUS: connected ({len(products)} products total, {live_count} live for sale). "
                "Use ONLY this data for products:"
            )
            for product in products[:40]:
                lines.append(self._product_summary(product))

        lines.append(
            f"Example shipping quote for £50 basket: £{calculate_shipping(50, self._settings).shipping_gbp:.2f} shipping."
        )
        lines.append(
            f"Example shipping quote for £{free_threshold:.0f}+ basket: free shipping."
        )
        return "\n".join(lines)

    @staticmethod
    def _product_summary(product: Product) -> str:
        variants = []
        for v in product.variants:
            stock = "in stock" if v.stock_quantity > 0 else "out of stock"
            variants.append(f"{v.size}/{v.colour}: £{v.price_gbp:.2f}, qty {v.stock_quantity} ({stock})")
        variant_text = "; ".join(variants) if variants else "no variants listed"
        sale = f", sale price £{product.sale_price_gbp:.2f}" if product.is_on_sale and product.sale_price_gbp else ""
        status = "LIVE FOR SALE" if is_live_catalog_product(product) else "DEMO/DEVELOPMENT — NOT FOR SALE"
        return (
            f"- {product.name} [{status}] (slug: {product.slug}, brand: {product.brand}, "
            f"category: {product.category_name}{sale}). Variants: {variant_text}. "
            f"URL: /product/{product.slug}"
        )

    async def _ask_openai(
        self,
        message: str,
        history: list[ChatMessage],
        catalog_context: str,
    ) -> str:
        system = f"""You are DRUVO Chat, the friendly customer assistant for DRUVO UK (https://druvo.uk).
You help shoppers with products, sizes, colours, availability, delivery, returns, and general store questions.

STRICT RULES:
- Never invent stock, prices, delivery promises, tracking, or order information.
- Only state product facts that appear in the LIVE CATALOG DATA below.
- If asked about a specific order, tell the customer to use /account/login with their checkout email, or contact {self._settings.contact_email}.
- If you cannot answer confidently from the provided data, direct the customer to {self._settings.contact_email}.
- Keep replies concise, warm, and professional (2–4 short paragraphs max).
- Use GBP (£) for prices.
- Do not mention OpenAI, APIs, or internal systems.

LIVE CATALOG DATA:
{catalog_context}
"""
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        for item in history[-_MAX_HISTORY:]:
            if item.role in {"user", "assistant"} and item.content.strip():
                messages.append({"role": item.role, "content": item.content.strip()})
        messages.append({"role": "user", "content": message})

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                _OPENAI_URL,
                headers={
                    "Authorization": f"Bearer {self._settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._settings.chat_model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 500,
                },
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

    def _rules_reply(self, message: str, products: list[Product], degraded: bool) -> str:
        lower = message.lower()
        email = self._settings.contact_email
        free_threshold = self._settings.shipping_free_threshold_gbp
        standard = self._settings.shipping_standard_gbp

        if any(w in lower for w in ("delivery", "shipping", "postage", "dispatch", "ship")):
            return (
                f"Standard UK delivery is £{standard:.2f}. Orders over £{free_threshold:.2f} qualify for free delivery. "
                f"See full details at /delivery. For a specific order status, use /account/login or email {email}."
            )

        if any(w in lower for w in ("return", "refund", "exchange")):
            return (
                f"Our returns policy is on /returns. If you need help with a return, email {email} with your order details."
            )

        if any(w in lower for w in ("order", "tracking", "where is my")):
            return (
                f"I can't look up individual orders in chat. Visit /account/login and enter your checkout email, "
                f"or contact us at {email}."
            )

        if any(w in lower for w in ("contact", "email", "support", "human", "speak to")):
            return f"You can reach DRUVO UK at {email}. We aim to reply as soon as we can."

        if any(w in lower for w in ("payment", "stripe", "checkout", "pay")):
            return (
                "We accept secure card payments via Stripe at checkout. "
                f"If checkout fails, try again or email {email}."
            )

        if degraded:
            return _CATALOG_UNAVAILABLE.format(email=email)

        matched = self._match_products(message, products)
        if matched:
            parts = []
            for product in matched[:3]:
                parts.append(self._format_product_answer(product))
            suffix = "" if len(matched) <= 3 else f"\n\n({len(matched) - 3} more matches — try /search?q=...)"
            return "\n\n".join(parts) + suffix

        if any(w in lower for w in ("product", "stock", "available", "size", "colour", "price")):
            if products:
                names = ", ".join(p.name for p in products[:5])
                return (
                    f"I couldn't find an exact match. Browse /shop or search our catalog. "
                    f"Current listings include: {names}. For more help, email {email}."
                )

        return _CONTACT_FALLBACK.format(email=email)

    @staticmethod
    def _match_products(message: str, products: list[Product]) -> list[Product]:
        tokens = [t for t in re.findall(r"[a-z0-9]+", message.lower()) if len(t) > 2]
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
    def _format_product_answer(product: Product) -> str:
        in_stock_sizes = sorted({v.size for v in product.variants if v.stock_quantity > 0})
        in_stock_colours = sorted({v.colour for v in product.variants if v.stock_quantity > 0})
        price = product.min_price
        stock_text = "In stock" if product.in_stock else "Out of stock"
        lines = [f"**{product.name}** — from £{price:.2f} ({stock_text})."]
        if not is_live_catalog_product(product):
            lines.append(
                "Note: this is a development sample on the website — not currently available to purchase."
            )
        else:
            if product.brand:
                lines.append(f"Brand: {product.brand}.")
            lines.append(f"Category: {product.category_name}.")
            if in_stock_sizes:
                lines.append(f"Sizes with stock: {', '.join(in_stock_sizes)}.")
            if in_stock_colours:
                lines.append(f"Colours with stock: {', '.join(in_stock_colours)}.")
        lines.append(f"View: /product/{product.slug}")
        return "\n".join(lines)

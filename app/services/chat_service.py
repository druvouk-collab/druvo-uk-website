"""DRUVO Chat — customer assistant with live website knowledge."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.config import Settings, get_settings
from app.services.chat_commerce_service import ChatCommerceReply, ChatCommerceService, ChatProductCard
from app.services.website_knowledge_service import WebsiteKnowledgeService

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LEN = 500
_MAX_HISTORY = 8
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_CONTACT_FALLBACK = (
    "I'm not sure about that one. Try browsing /shop, or email us at {email} "
    "and our team will be happy to help."
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
            "current offers, and how to find your orders. Just ask!"
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
    products: list[dict] = field(default_factory=list)
    context_product_slugs: list[str] = field(default_factory=list)
    add_to_cart: dict | None = None


class ChatService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._knowledge = WebsiteKnowledgeService(self._settings)
        self._commerce = ChatCommerceService(self._knowledge)

    @property
    def welcome_message(self) -> str:
        return _WELCOME

    async def reply(
        self,
        message: str,
        history: list[ChatMessage] | None = None,
        *,
        cart_items: list[dict] | None = None,
        last_product_slugs: list[str] | None = None,
    ) -> ChatReply:
        cleaned = self._sanitize_message(message)
        if not cleaned:
            return ChatReply(
                reply="Please type a question and I'll do my best to help.",
                source="rules",
            )

        snapshot = await self._knowledge.load()
        cart = self._knowledge.cart_summary(cart_items or []) if cart_items else None
        context = self._knowledge.build_ai_context(snapshot, cart)

        conversational = _conversational_reply(cleaned)
        if conversational:
            return ChatReply(reply=conversational, source="rules")

        commerce = await self._commerce.answer(
            cleaned,
            snapshot,
            cart_items=cart_items,
            last_slugs=last_product_slugs,
        )

        if self._settings.openai_api_key and not self._should_prefer_rules(cleaned, commerce):
            try:
                text = await self._ask_openai(cleaned, history or [], context)
                return self._merge_commerce(ChatReply(reply=text, source="openai"), commerce)
            except Exception as exc:
                logger.warning("OpenAI chat failed, falling back to rules: %s", type(exc).__name__)

        if commerce:
            return self._commerce_to_reply(commerce, source="rules")

        return ChatReply(
            reply=_CONTACT_FALLBACK.format(email=self._settings.contact_email),
            source="rules",
        )

    @staticmethod
    def _should_prefer_rules(message: str, commerce: ChatCommerceReply | None) -> bool:
        if commerce and commerce.products:
            return True
        lower = message.lower()
        return any(
            w in lower
            for w in (
                "delivery", "shipping", "return", "refund", "price", "stock", "available",
                "sale", "offer", "cheapest", "under £", "basket", "cart", "free delivery",
            )
        )

    @staticmethod
    def _commerce_to_reply(commerce: ChatCommerceReply, source: str) -> ChatReply:
        return ChatReply(
            reply=commerce.text,
            source=source,
            products=[p.as_dict() for p in commerce.products],
            context_product_slugs=commerce.context_product_slugs,
            add_to_cart=commerce.add_to_cart,
        )

    @staticmethod
    def _merge_commerce(base: ChatReply, commerce: ChatCommerceReply | None) -> ChatReply:
        if not commerce or not commerce.products:
            return base
        return ChatReply(
            reply=base.reply,
            source=base.source,
            products=[p.as_dict() for p in commerce.products],
            context_product_slugs=commerce.context_product_slugs,
            add_to_cart=commerce.add_to_cart,
        )

    def _sanitize_message(self, message: str) -> str:
        text = (message or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text[:_MAX_MESSAGE_LEN]

    async def _ask_openai(
        self,
        message: str,
        history: list[ChatMessage],
        catalog_context: str,
    ) -> str:
        system = f"""You are DRUVO Chat, the friendly customer assistant for DRUVO UK (https://druvo.uk).
You help shoppers with products, sizes, colours, availability, delivery, returns, promotions, and general store questions.

STRICT RULES:
- Never invent stock, prices, delivery promises, tracking, coupon codes, discounts, or order information.
- Only state product facts that appear in the LIVE WEBSITE DATA below.
- Only mention promotions listed as ACTIVE — never invent offers.
- Demo/development products are NOT for sale — never suggest purchasing them.
- If asked about a specific order, tell the customer to use /account/login with their checkout email, or contact {self._settings.contact_email}.
- If you cannot answer confidently from the provided data, say so and direct the customer to {self._settings.contact_email}.
- Keep replies concise, warm, and professional (2–4 short paragraphs max).
- Use GBP (£) for prices.
- Do not mention OpenAI, APIs, or internal systems.

LIVE WEBSITE DATA:
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

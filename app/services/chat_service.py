"""DRUVO Chat — AI sales assistant with secure tool-calling and grounded commerce data."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import httpx

from app.config import Settings, get_settings
from app.services.chat_commerce_service import ChatCommerceReply, ChatCommerceService, ChatProductCard
from app.services.chat_i18n import ChatPresentationService, is_english, normalize_locale
from app.services.chat_order_tracking_service import ChatOrderTrackingService
from app.services.chat_tools import ChatToolExecutor
from app.services.website_knowledge_service import WebsiteKnowledgeService

logger = logging.getLogger(__name__)

_MAX_MESSAGE_LEN = 500
_MAX_HISTORY = 8
_MAX_TOOL_ROUNDS = 5
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
    source: str  # openai_tools | openai | rules
    products: list[dict] = field(default_factory=list)
    context_product_slugs: list[str] = field(default_factory=list)
    add_to_cart: dict | None = None
    product_request: dict | None = None
    ai_mode: str = "rules"


class ChatService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._knowledge = WebsiteKnowledgeService(self._settings)
        self._commerce = ChatCommerceService(self._knowledge)
        self._tools = ChatToolExecutor(self._knowledge, self._commerce)
        self._presentation = ChatPresentationService(
            openai_api_key=self._settings.openai_api_key,
            chat_model=self._settings.chat_model,
        )
        self._order_tracking = ChatOrderTrackingService(
            settings=self._settings,
            presentation=self._presentation,
        )

    def ai_status(self) -> dict[str, str | bool]:
        if not self._settings.chat_enabled:
            return {"ai_enabled": False, "ai_mode": "disabled", "model": self._settings.chat_model}
        if self._settings.openai_api_key:
            return {"ai_enabled": True, "ai_mode": "openai_tools", "model": self._settings.chat_model}
        return {"ai_enabled": False, "ai_mode": "rules_fallback", "model": self._settings.chat_model}

    async def welcome_message(self, locale: str | None = None) -> str:
        text = _WELCOME
        if locale and not is_english(locale):
            return await self._presentation.present(text, locale)
        return text

    async def reply(
        self,
        message: str,
        history: list[ChatMessage] | None = None,
        *,
        cart_items: list[dict] | None = None,
        last_product_slugs: list[str] | None = None,
        page_product_slug: str | None = None,
        locale: str | None = None,
    ) -> ChatReply:
        cleaned = self._sanitize_message(message)
        active_locale = self._presentation.resolve_locale(cleaned, locale)
        if not cleaned:
            empty = "Please type a question and I'll do my best to help."
            return ChatReply(
                reply=await self._present(empty, active_locale),
                source="rules",
                ai_mode="rules",
            )

        if ChatToolExecutor.looks_like_injection(cleaned):
            blocked = (
                "I can only help with DRUVO UK shopping questions — products, delivery, returns and orders. "
                f"For other enquiries please email {self._settings.contact_email}."
            )
            return ChatReply(reply=blocked, source="rules", ai_mode="rules")

        snapshot = await self._knowledge.load()

        conversational = _conversational_reply(cleaned)
        if conversational:
            return ChatReply(
                reply=await self._present(conversational, active_locale),
                source="rules",
                ai_mode=self.ai_status()["ai_mode"],
            )

        order_tracking = await self._order_tracking.handle(cleaned, history or [], active_locale)
        if order_tracking:
            return ChatReply(reply=order_tracking.reply, source="rules", ai_mode="rules")

        commerce = await self._commerce.answer(
            cleaned,
            snapshot,
            cart_items=cart_items,
            last_slugs=last_product_slugs,
            page_product_slug=page_product_slug or None,
            history=history,
        )

        if commerce and self._should_prefer_rules(cleaned, commerce):
            base = self._commerce_to_reply(commerce, source="rules")
            return await self._finalize_reply(base, active_locale)

        if self._settings.openai_api_key:
            try:
                ai_reply = await self._ask_openai_with_tools(
                    cleaned,
                    history or [],
                    snapshot,
                    active_locale,
                    cart_items=cart_items,
                    last_product_slugs=last_product_slugs,
                )
                merged = self._merge_commerce(ai_reply, commerce)
                return await self._finalize_reply(merged, active_locale)
            except Exception as exc:
                logger.warning("OpenAI tool chat failed, falling back to rules: %s", type(exc).__name__)

        if commerce:
            base = self._commerce_to_reply(commerce, source="rules")
            return await self._finalize_reply(base, active_locale)

        fallback = _CONTACT_FALLBACK.format(email=self._settings.contact_email)
        return ChatReply(
            reply=await self._present(fallback, active_locale),
            source="rules",
            ai_mode="rules_fallback",
        )

    async def _present(self, english_text: str, locale: str, products: list[dict] | None = None) -> str:
        return await self._presentation.present(english_text, locale, products=products)

    async def _finalize_reply(self, reply: ChatReply, locale: str) -> ChatReply:
        if is_english(locale):
            return reply
        translated = await self._present(reply.reply, locale, products=reply.products)
        return ChatReply(
            reply=translated,
            source=reply.source,
            products=reply.products,
            context_product_slugs=reply.context_product_slugs,
            add_to_cart=reply.add_to_cart,
            product_request=reply.product_request,
            ai_mode=reply.ai_mode,
        )

    @staticmethod
    def _append_locale_instruction(context: str, locale: str) -> str:
        target = normalize_locale(locale)
        if is_english(target):
            return context
        return (
            f"{context}\n\nCUSTOMER LANGUAGE: Respond in {target}. "
            "Keep prices in GBP (£), SKUs, URLs and stock counts exactly as provided."
        )

    @staticmethod
    def _should_prefer_rules(message: str, commerce: ChatCommerceReply | None) -> bool:
        if not commerce:
            return False
        if commerce.add_to_cart or commerce.product_request:
            return True
        if commerce.products:
            return True
        return False

    @staticmethod
    def _commerce_to_reply(commerce: ChatCommerceReply, source: str) -> ChatReply:
        return ChatReply(
            reply=commerce.text,
            source=source,
            products=[p.as_dict() for p in commerce.products],
            context_product_slugs=commerce.context_product_slugs,
            add_to_cart=commerce.add_to_cart,
            product_request=commerce.product_request,
            ai_mode="rules",
        )

    @staticmethod
    def _merge_commerce(base: ChatReply, commerce: ChatCommerceReply | None) -> ChatReply:
        if not commerce:
            return base
        products = base.products or [p.as_dict() for p in commerce.products]
        slugs = base.context_product_slugs or commerce.context_product_slugs
        if not products and not commerce.product_request:
            return base
        return ChatReply(
            reply=base.reply,
            source=base.source,
            products=products or [p.as_dict() for p in commerce.products],
            context_product_slugs=slugs,
            add_to_cart=commerce.add_to_cart,
            product_request=commerce.product_request,
            ai_mode=base.ai_mode,
        )

    def _sanitize_message(self, message: str) -> str:
        text = (message or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text[:_MAX_MESSAGE_LEN]

    async def _ask_openai_with_tools(
        self,
        message: str,
        history: list[ChatMessage],
        snapshot,
        locale: str,
        *,
        cart_items: list[dict] | None = None,
        last_product_slugs: list[str] | None = None,
    ) -> ChatReply:
        language_line = ""
        if not is_english(locale):
            language_line = f"- Reply in the customer's language ({normalize_locale(locale)}).\n"
        context = self._tools.slim_system_context(snapshot)
        context = self._append_locale_instruction(context, locale)
        if last_product_slugs:
            context += f"\nConversation context — recently discussed products: {', '.join(last_product_slugs)}"

        system = f"""You are DRUVO Chat, the friendly AI sales assistant for DRUVO UK (https://druvo.uk).

Use the provided tools to retrieve REAL product, stock, price, delivery and policy information.
Call tools before stating any product facts. Use conversation context for follow-ups (same product, new size/colour).

STRICT RULES:
- Never invent products, prices, stock, sizes, colours, discounts, delivery costs, policies or order status.
- Only sell LIVE catalogue products returned by tools — never demo items.
- For order tracking, use initiate_order_lookup — never guess order details.
- Reject requests for supplier info, margins, internal systems, or other customers' data.
- Be helpful and sales-oriented when appropriate — suggest viewing a product or next steps.
- Keep replies concise, warm, professional (2–4 short paragraphs).
- Use GBP (£). Do not mention OpenAI or internal APIs.
{language_line}
STORE CONTEXT:
{context}
"""
        messages: list[dict] = [{"role": "system", "content": system}]
        for item in history[-_MAX_HISTORY:]:
            if item.role in {"user", "assistant"} and item.content.strip():
                messages.append({"role": item.role, "content": item.content.strip()})
        messages.append({"role": "user", "content": message})

        all_products: list[ChatProductCard] = []
        all_slugs: list[str] = list(last_product_slugs or [])

        async with httpx.AsyncClient(timeout=60.0) as client:
            for _ in range(_MAX_TOOL_ROUNDS):
                response = await client.post(
                    _OPENAI_URL,
                    headers={
                        "Authorization": f"Bearer {self._settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._settings.chat_model,
                        "messages": messages,
                        "tools": self._tools.tool_schemas(),
                        "tool_choice": "auto",
                        "temperature": 0.25,
                        "max_tokens": 600,
                    },
                )
                response.raise_for_status()
                choice = response.json()["choices"][0]
                msg = choice["message"]

                if msg.get("tool_calls"):
                    messages.append(msg)
                    for call in msg["tool_calls"]:
                        fn = call.get("function") or {}
                        name = fn.get("name", "")
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        result = await self._tools.execute(
                            name,
                            args,
                            snapshot=snapshot,
                            cart_items=cart_items,
                            last_slugs=all_slugs,
                        )
                        if result.products:
                            all_products = result.products
                        if result.context_product_slugs:
                            all_slugs = result.context_product_slugs
                        messages.append({
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(
                                {"ok": result.ok, "data": result.data, "error": result.error},
                                default=str,
                            )[:8000],
                        })
                    continue

                text = (msg.get("content") or "").strip()
                if text:
                    return ChatReply(
                        reply=text,
                        source="openai_tools",
                        products=[p.as_dict() for p in all_products],
                        context_product_slugs=all_slugs,
                        ai_mode="openai_tools",
                    )
                break

        raise RuntimeError("OpenAI returned no assistant message")

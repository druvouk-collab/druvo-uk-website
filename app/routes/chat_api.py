"""DRUVO Chat API — server-side assistant (no secrets exposed to browser)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.chat_i18n import QUICK_LANGUAGES, is_rtl, language_catalog, normalize_locale
from app.services.chat_rate_limit import get_chat_rate_limiter
from app.services.chat_service import ChatMessage, ChatService

router = APIRouter(prefix="/api/chat", tags=["chat"])


class HistoryItem(BaseModel):
    role: str
    content: str


class CartItemPayload(BaseModel):
    slug: str = ""
    sku: str = ""
    name: str = ""
    size: str = ""
    colour: str = ""
    price_gbp: float = 0.0
    quantity: int = Field(default=1, ge=1)
    variant_id: int | None = None


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    history: list[HistoryItem] = Field(default_factory=list, max_length=8)
    cart: list[CartItemPayload] = Field(default_factory=list, max_length=20)
    last_product_slugs: list[str] = Field(default_factory=list, max_length=5)
    page_product_slug: str = Field(default="", max_length=120)
    locale: str = Field(default="", max_length=16)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


@router.get("/status")
async def chat_status(locale: str = "en-GB") -> JSONResponse:
    settings = get_settings()
    service = ChatService(settings)
    return JSONResponse(
        {
            "enabled": settings.chat_enabled,
            "ai_enabled": bool(settings.openai_api_key),
            "welcome": await service.welcome_message(locale),
            "locale": normalize_locale(locale),
            "rtl": is_rtl(locale),
        }
    )


@router.get("/languages")
async def chat_languages() -> JSONResponse:
    return JSONResponse(
        {
            "quick": QUICK_LANGUAGES,
            "languages": language_catalog(),
        }
    )


@router.post("/message")
async def chat_message(request: Request, body: ChatRequest) -> JSONResponse:
    settings = get_settings()
    if not settings.chat_enabled:
        return JSONResponse({"detail": "Chat is temporarily unavailable."}, status_code=503)

    limiter = get_chat_rate_limiter(
        max_requests=settings.chat_rate_limit_per_hour,
        window_seconds=3600,
    )
    client_key = _client_ip(request)
    allowed, retry_after = limiter.allow(client_key)
    if not allowed:
        return JSONResponse(
            {"detail": "Too many messages. Please try again later.", "retry_after": retry_after},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )

    history = [
        ChatMessage(role=item.role, content=item.content)
        for item in body.history
        if item.role in {"user", "assistant"} and item.content.strip()
    ]

    cart_items = [item.model_dump() for item in body.cart]
    locale = normalize_locale(body.locale)

    service = ChatService(settings)
    result = await service.reply(
        body.message,
        history,
        cart_items=cart_items,
        last_product_slugs=body.last_product_slugs,
        page_product_slug=body.page_product_slug.strip() or None,
        locale=locale,
    )
    return JSONResponse(
        {
            "reply": result.reply,
            "source": result.source,
            "products": result.products,
            "context_product_slugs": result.context_product_slugs,
            "add_to_cart": result.add_to_cart,
            "locale": locale,
            "rtl": is_rtl(locale),
        }
    )

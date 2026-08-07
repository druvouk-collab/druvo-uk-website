"""DRUVO Chat API — server-side assistant (no secrets exposed to browser)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.chat_rate_limit import get_chat_rate_limiter
from app.services.chat_service import ChatMessage, ChatService

router = APIRouter(prefix="/api/chat", tags=["chat"])


class HistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    history: list[HistoryItem] = Field(default_factory=list, max_length=8)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


@router.get("/status")
async def chat_status() -> JSONResponse:
    settings = get_settings()
    return JSONResponse(
        {
            "enabled": settings.chat_enabled,
            "ai_enabled": bool(settings.openai_api_key),
            "welcome": ChatService(settings).welcome_message,
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

    service = ChatService(settings)
    result = await service.reply(body.message, history)
    return JSONResponse({"reply": result.reply, "source": result.source})

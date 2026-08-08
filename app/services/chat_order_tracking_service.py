"""DRUVO Chat order tracking — verified lookup against live DRUVO API orders."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from app.config import Settings, get_settings
from app.services.account_order_service import AccountOrderService
from app.services.chat_i18n import ChatPresentationService
from app.types.commerce import Order

ORDER_REF_PROMPT = (
    "Please enter your DRUVO order number or order reference "
    "(for example web-abc123…)."
)
EMAIL_VERIFY_PROMPT = (
    "Thanks. Please enter the email address you used at checkout so I can verify this order."
)
VERIFY_FAILED = (
    "I couldn't find an order matching that reference and email. "
    "Please double-check both details and try again, or contact {email} for help."
)
NOT_ENABLED = (
    "Order tracking isn't available right now. "
    "You can look up orders at /account/orders or email {email}."
)
INVALID_ORDER_REF = (
    "That doesn't look like a valid order reference. "
    "Please enter your DRUVO order number (for example web-abc123…)."
)
INVALID_EMAIL = (
    "Please enter a valid checkout email address so I can verify your order."
)

_TRACK_INTENT = re.compile(
    r"\b("
    r"track\s+my\s+order|track\s+order|order\s+status|where\s+is\s+my\s+order|"
    r"where\s+is\s+my\s+package|track\s+my\s+package|my\s+order\s+status"
    r")\b",
    re.I,
)
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_ORDER_REF_RE = re.compile(r"^[a-z0-9][a-z0-9\-_.]{3,}$", re.I)

_CUSTOMER_STATUS = {
    "received": "Order confirmed",
    "confirmed": "Order confirmed",
    "processing": "Preparing",
    "shipped": "Dispatched",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
    "failed": "Failed",
}


class _HistoryItem(Protocol):
    role: str
    content: str


@dataclass(frozen=True)
class ChatOrderTrackingResult:
    reply: str
    handled: bool = True


class ChatOrderTrackingService:
    """Multi-step order lookup with checkout email verification."""

    def __init__(
        self,
        settings: Settings | None = None,
        orders: AccountOrderService | None = None,
        presentation: ChatPresentationService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._orders = orders or AccountOrderService()
        self._presentation = presentation or ChatPresentationService(
            openai_api_key=self._settings.openai_api_key,
            chat_model=self._settings.chat_model,
        )

    async def handle(
        self,
        message: str,
        history: list[_HistoryItem],
        locale: str,
    ) -> ChatOrderTrackingResult | None:
        cleaned = (message or "").strip()
        if not cleaned:
            return None

        if self._last_assistant_contains(history, EMAIL_VERIFY_PROMPT):
            return await self._handle_email_step(cleaned, history, locale)

        if self._last_assistant_contains(history, ORDER_REF_PROMPT):
            return await self._handle_order_ref_step(cleaned, locale)

        if _TRACK_INTENT.search(cleaned):
            return await self._start_flow(locale)

        return None

    async def _start_flow(self, locale: str) -> ChatOrderTrackingResult:
        if not self._orders.live_orders_enabled:
            text = NOT_ENABLED.format(email=self._settings.contact_email)
            return ChatOrderTrackingResult(reply=await self._present(text, locale))
        return ChatOrderTrackingResult(reply=await self._present(ORDER_REF_PROMPT, locale))

    async def _handle_order_ref_step(self, order_ref: str, locale: str) -> ChatOrderTrackingResult:
        normalized = order_ref.strip()
        if not _ORDER_REF_RE.match(normalized):
            return ChatOrderTrackingResult(reply=await self._present(INVALID_ORDER_REF, locale))
        return ChatOrderTrackingResult(reply=await self._present(EMAIL_VERIFY_PROMPT, locale))

    async def _handle_email_step(
        self,
        email: str,
        history: list[_HistoryItem],
        locale: str,
    ) -> ChatOrderTrackingResult:
        order_ref = self._pending_order_ref(history)
        normalized_email = email.strip().lower()
        if not _EMAIL_RE.match(normalized_email):
            return ChatOrderTrackingResult(reply=await self._present(INVALID_EMAIL, locale))
        if not order_ref:
            return await self._start_flow(locale)

        order = await self._orders.get_order(order_ref, normalized_email)
        if not order:
            text = VERIFY_FAILED.format(email=self._settings.contact_email)
            return ChatOrderTrackingResult(reply=await self._present(text, locale))
        return ChatOrderTrackingResult(
            reply=await self._present(self._format_order_status(order), locale),
        )

    def _format_order_status(self, order: Order) -> str:
        status_code = (order.status_code or order.status).strip().lower()
        customer_status = _CUSTOMER_STATUS.get(status_code, order.status)
        lines = [
            f"**Order {order.id}**",
            f"Status: **{customer_status}**",
        ]
        if order.placed_at:
            lines.append(f"Placed: {order.placed_at}")
        if order.status_updated_at and order.status_updated_at != order.placed_at:
            lines.append(f"Last updated: {order.status_updated_at}")

        item_bits = []
        for line in order.lines:
            item_bits.append(
                f"{line.product_name} ({line.colour} / {line.size}) × {line.quantity}"
            )
        if item_bits:
            lines.append("Items: " + "; ".join(item_bits))

        if status_code in {"shipped", "delivered"}:
            if order.shipped_at:
                lines.append(f"Dispatched: {order.shipped_at}")
            if status_code == "shipped":
                lines.append("Your order is on its way.")
            if order.delivered_at:
                lines.append(f"Delivered: {order.delivered_at}")
            if order.has_tracking:
                tracking_line = f"Tracking: {order.tracking_number}"
                if order.carrier:
                    tracking_line = f"Courier: {order.carrier} · {tracking_line}"
                lines.append(tracking_line)
                link = self._tracking_link(order.carrier, order.tracking_number)
                if link:
                    lines.append(f"Track online: {link}")
        elif status_code in {"received", "confirmed", "processing"}:
            lines.append(
                "We'll email you when your order is dispatched with tracking details."
            )

        lines.append(f"Order total: £{order.total_gbp:.2f}")
        return "\n".join(lines)

    @staticmethod
    def _tracking_link(carrier: str | None, tracking_number: str | None) -> str | None:
        if not tracking_number or not tracking_number.strip():
            return None
        number = tracking_number.strip()
        carrier_lower = (carrier or "").lower()
        if "royal mail" in carrier_lower:
            return f"https://www.royalmail.com/track-your-item#/tracking-results/{number}"
        if "evri" in carrier_lower or "hermes" in carrier_lower:
            return f"https://www.evri.com/track-a-parcel/parcel/{number}"
        return None

    @staticmethod
    def _last_assistant_contains(history: list[_HistoryItem], phrase: str) -> bool:
        for item in reversed(history):
            if item.role == "assistant":
                return phrase in item.content
        return False

    @staticmethod
    def _pending_order_ref(history: list[_HistoryItem]) -> str:
        for index in range(len(history) - 1, -1, -1):
            item = history[index]
            if item.role == "assistant" and EMAIL_VERIFY_PROMPT in item.content:
                for prev in range(index - 1, -1, -1):
                    if history[prev].role == "user":
                        return history[prev].content.strip()
                return ""
        return ""

    async def _present(self, english_text: str, locale: str) -> str:
        return await self._presentation.present(english_text, locale)

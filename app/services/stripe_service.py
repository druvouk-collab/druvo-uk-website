"""Stripe Checkout Session creation and webhook fulfillment."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

import stripe

from app.config import Settings, get_settings
from app.lib.druvo_api.errors import CatalogApiError
from app.services.order_service import CheckoutLine, CheckoutRequest, WebsiteOrderService
from app.services.shipping_service import calculate_shipping
from app.storage.checkout_store import (
    PendingCheckout,
    attach_session,
    get_pending,
    get_pending_by_session,
    mark_status,
    save_pending,
)

logger = logging.getLogger(__name__)
_LINE_NAME_RE = re.compile(r"^(?P<sku>.+?) × (?P<quantity>\d+)$")


class StripeCheckoutService:
    """Create Stripe test-mode sessions and fulfill paid orders in DRUVO AI."""

    def __init__(
        self,
        settings: Settings | None = None,
        order_service: WebsiteOrderService | None = None,
    ) -> None:
        self._settings_override = settings
        self._orders = order_service or WebsiteOrderService()

    @property
    def _settings(self) -> Settings:
        return self._settings_override or get_settings()

    @property
    def enabled(self) -> bool:
        return self._settings.payments_enabled

    def _configure_stripe(self) -> None:
        stripe.api_key = self._settings.stripe_secret_key

    async def create_checkout_session(
        self,
        *,
        customer_email: str,
        customer_name: str,
        lines: list[CheckoutLine],
        external_order_id: str | None = None,
    ) -> dict[str, str]:
        if not self.enabled:
            raise RuntimeError("Stripe payments are not configured.")
        if not lines:
            raise ValueError("Basket is empty.")

        order_ref = external_order_id.strip() if external_order_id else f"web-{uuid.uuid4().hex[:16]}"
        stock = await self._orders.validate_stock(lines)
        if not stock.get("ok"):
            raise ValueError("Some items are no longer in stock.")

        line_payloads = [
            {
                "sku": line.sku,
                "quantity": line.quantity,
                "unit_price_gbp": line.unit_price_gbp,
                **({"variant_id": line.variant_id} if line.variant_id is not None else {}),
            }
            for line in lines
        ]
        subtotal = sum(line.quantity * line.unit_price_gbp for line in lines)
        shipping_quote = calculate_shipping(subtotal, self._settings)
        save_pending(order_ref, customer_email, customer_name, line_payloads)
        lines_json = json.dumps(line_payloads, separators=(",", ":"))
        if len(lines_json) > 500:
            raise ValueError("Checkout basket is too large for Stripe metadata backup.")

        stripe_line_items = [
            {
                "price_data": {
                    "currency": "gbp",
                    "unit_amount": self._to_pence(line.unit_price_gbp),
                    "product_data": {"name": f"{line.sku} × {line.quantity}"},
                },
                "quantity": line.quantity,
            }
            for line in lines
        ]
        if shipping_quote.shipping_gbp > 0:
            stripe_line_items.append(
                {
                    "price_data": {
                        "currency": "gbp",
                        "unit_amount": self._to_pence(shipping_quote.shipping_gbp),
                        "product_data": {"name": "UK standard shipping"},
                    },
                    "quantity": 1,
                }
            )

        self._configure_stripe()
        session = stripe.checkout.Session.create(
            mode="payment",
            currency="gbp",
            customer_email=customer_email.strip(),
            client_reference_id=order_ref,
            metadata={
                "external_order_id": order_ref,
                "customer_email": customer_email.strip()[:500],
                "customer_name": customer_name.strip()[:500],
                "lines_json": lines_json,
                "shipping_gbp": str(shipping_quote.shipping_gbp),
            },
            line_items=stripe_line_items,
            success_url=f"{self._settings.public_site_url}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{self._settings.public_site_url}/checkout/cancel?external_order_id={order_ref}",
        )
        attach_session(order_ref, session.id)
        return {
            "checkout_url": session.url,
            "session_id": session.id,
            "external_order_id": order_ref,
        }

    async def handle_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        if not self._settings.stripe_webhook_secret:
            raise RuntimeError("Stripe webhook secret is not configured.")
        self._configure_stripe()
        try:
            event = stripe.Webhook.construct_event(
                payload,
                signature,
                self._settings.stripe_webhook_secret,
            )
        except stripe.error.SignatureVerificationError as exc:
            raise ValueError("Invalid Stripe webhook signature.") from exc

        event_type = event["type"]
        if event_type == "checkout.session.completed":
            return await self._fulfill_completed_session(event["data"]["object"])
        if event_type == "checkout.session.expired":
            return self._mark_expired(event["data"]["object"])
        return {"handled": False, "event_type": event_type}

    async def _fulfill_completed_session(self, session: Any) -> dict[str, Any]:
        if self._session_field(session, "payment_status") != "paid":
            return {"handled": False, "reason": "payment_not_paid"}

        external_order_id = self._external_order_id(session)
        if not external_order_id:
            raise ValueError("Missing external_order_id on Stripe session.")

        pending = await self._resolve_checkout(session, external_order_id)

        if pending.status == "paid":
            order = await self._orders.get_by_external_id(external_order_id)
            return {"handled": True, "duplicate": True, "order": order}

        try:
            result = await self._orders.submit_after_payment(
                CheckoutRequest(
                    customer_email=pending.customer_email,
                    customer_name=pending.customer_name,
                    lines=[self._line_from_dict(item) for item in pending.lines],
                ),
                external_order_id=external_order_id,
                stripe_session_id=self._session_field(session, "id"),
                stripe_payment_intent_id=self._payment_intent_id(session),
                shipping_gbp=self._shipping_gbp(session, pending.lines),
            )
        except CatalogApiError as exc:
            logger.warning(
                "DRUVO order submission failed for %s (%s)",
                external_order_id,
                exc.cause or type(exc).__name__,
            )
            raise RuntimeError("DRUVO master order system could not accept the paid order.") from exc

        mark_status(external_order_id, "paid")
        return {"handled": True, "duplicate": bool(result.get("duplicate")), "order": result}

    async def _resolve_checkout(self, session: Any, external_order_id: str) -> PendingCheckout:
        pending = get_pending(external_order_id)
        if pending:
            return pending

        metadata = self._metadata_dict(session)
        lines_json = metadata.get("lines_json", "")
        if lines_json:
            try:
                lines = json.loads(lines_json)
            except json.JSONDecodeError as exc:
                raise ValueError("Stored checkout lines in Stripe metadata are invalid.") from exc
            return PendingCheckout(
                external_order_id=external_order_id,
                customer_email=metadata.get("customer_email", ""),
                customer_name=metadata.get("customer_name", ""),
                lines=lines,
                stripe_session_id=self._session_field(session, "id"),
                status="pending",
            )

        session_id = self._session_field(session, "id")
        if session_id:
            logger.info("Rebuilding checkout context from Stripe session %s", session_id)
            return await self._checkout_from_stripe_session(session_id, external_order_id)

        raise ValueError(f"No pending checkout for {external_order_id}.")

    async def _checkout_from_stripe_session(self, session_id: str, external_order_id: str) -> PendingCheckout:
        self._configure_stripe()
        full = stripe.checkout.Session.retrieve(session_id, expand=["line_items"])
        lines = self._lines_from_stripe_session(full)
        if not lines:
            raise ValueError(f"No pending checkout for {external_order_id}.")
        customer_email = self._session_field(full, "customer_email") or self._nested_field(
            full, "customer_details", "email"
        )
        return PendingCheckout(
            external_order_id=external_order_id,
            customer_email=customer_email,
            customer_name="",
            lines=lines,
            stripe_session_id=session_id,
            status="pending",
        )

    def _mark_expired(self, session: Any) -> dict[str, Any]:
        external_order_id = self._external_order_id(session)
        if external_order_id:
            mark_status(external_order_id, "expired")
        return {"handled": True, "status": "expired"}

    async def get_success_context(self, session_id: str) -> dict[str, Any]:
        self._configure_stripe()
        session = stripe.checkout.Session.retrieve(session_id)
        pending = get_pending_by_session(session_id)
        external_order_id = self._external_order_id(session) or (pending.external_order_id if pending else "")
        order = None
        if external_order_id:
            order = await self._orders.get_by_external_id(external_order_id)
        customer_email = self._nested_field(session, "customer_details", "email") or (
            pending.customer_email if pending else ""
        )
        return {
            "session_id": session_id,
            "payment_status": self._session_field(session, "payment_status"),
            "external_order_id": external_order_id,
            "customer_email": customer_email,
            "order": order,
            "paid": self._session_field(session, "payment_status") == "paid",
        }

    @staticmethod
    def _line_from_dict(item: dict) -> CheckoutLine:
        return CheckoutLine(
            sku=item["sku"],
            quantity=int(item["quantity"]),
            unit_price_gbp=float(item["unit_price_gbp"]),
            variant_id=item.get("variant_id"),
        )

    @staticmethod
    def _to_pence(amount_gbp: float) -> int:
        return int(round(amount_gbp * 100))

    @classmethod
    def _session_field(cls, session: Any, key: str, default: str = "") -> str:
        if session is None:
            return default
        if isinstance(session, dict):
            value = session.get(key, default)
        elif hasattr(session, "get"):
            value = session.get(key, default)
        else:
            value = getattr(session, key, default)
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip()
        if hasattr(value, "id") and key.endswith("_id"):
            return str(getattr(value, "id", default) or default)
        return str(value).strip() if value else default

    @classmethod
    def _nested_field(cls, session: Any, parent_key: str, child_key: str, default: str = "") -> str:
        if isinstance(session, dict):
            parent = session.get(parent_key) or {}
        elif hasattr(session, "get"):
            parent = session.get(parent_key) or {}
        else:
            parent = getattr(session, parent_key, {}) or {}
        if isinstance(parent, dict):
            value = parent.get(child_key, default)
        elif hasattr(parent, "get"):
            value = parent.get(child_key, default)
        else:
            value = getattr(parent, child_key, default)
        return str(value or default).strip()

    @classmethod
    def _metadata_dict(cls, session: Any) -> dict[str, str]:
        if isinstance(session, dict):
            raw = session.get("metadata") or {}
        elif hasattr(session, "get"):
            raw = session.get("metadata") or {}
        else:
            raw = getattr(session, "metadata", {}) or {}
        if not raw:
            return {}
        if isinstance(raw, dict):
            return {str(key): str(value) for key, value in raw.items()}
        try:
            return {str(key): str(value) for key, value in dict(raw).items()}
        except Exception:
            return {}

    @classmethod
    def _external_order_id(cls, session: Any) -> str:
        metadata = cls._metadata_dict(session)
        return (
            metadata.get("external_order_id")
            or cls._session_field(session, "client_reference_id")
            or ""
        ).strip()

    @classmethod
    def _payment_intent_id(cls, session: Any) -> str:
        value = None
        if isinstance(session, dict):
            value = session.get("payment_intent")
        elif hasattr(session, "get"):
            value = session.get("payment_intent")
        else:
            value = getattr(session, "payment_intent", None)
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return str(value.get("id") or "")
        if hasattr(value, "id"):
            return str(value.id)
        return str(value)

    @classmethod
    def _shipping_gbp(cls, session: Any, lines: list[dict]) -> float:
        metadata = cls._metadata_dict(session)
        raw = metadata.get("shipping_gbp", "")
        if raw:
            try:
                return float(raw)
            except ValueError:
                pass
        subtotal = sum(int(item.get("quantity", 1)) * float(item.get("unit_price_gbp", 0)) for item in lines)
        return calculate_shipping(subtotal).shipping_gbp

    @classmethod
    def _lines_from_stripe_session(cls, session: Any) -> list[dict]:
        line_items = None
        if isinstance(session, dict):
            line_items = (session.get("line_items") or {}).get("data")
        elif hasattr(session, "get"):
            items = session.get("line_items") or {}
            line_items = items.get("data") if isinstance(items, dict) else getattr(items, "data", None)
        if not line_items:
            return []

        parsed: list[dict] = []
        for item in line_items:
            if isinstance(item, dict):
                name = (((item.get("price") or {}).get("product") or {}).get("name")) or (
                    (item.get("price_data") or {}).get("product_data") or {}
                ).get("name", "")
                quantity = int(item.get("quantity") or 1)
                unit_amount = int(((item.get("price") or {}).get("unit_amount")) or 0)
            else:
                price = getattr(item, "price", None)
                name = getattr(getattr(price, "product", None), "name", "") if price else ""
                quantity = int(getattr(item, "quantity", 1) or 1)
                unit_amount = int(getattr(price, "unit_amount", 0) or 0)
            match = _LINE_NAME_RE.match(str(name).strip())
            if not match:
                continue
            parsed.append(
                {
                    "sku": match.group("sku"),
                    "quantity": int(match.group("quantity")),
                    "unit_price_gbp": unit_amount / 100.0,
                }
            )
        return parsed

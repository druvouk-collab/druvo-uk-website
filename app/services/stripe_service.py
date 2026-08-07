"""Stripe Checkout Session creation and webhook fulfillment."""

from __future__ import annotations

import uuid
from typing import Any

import stripe

from app.config import Settings, get_settings
from app.services.order_service import CheckoutLine, CheckoutRequest, WebsiteOrderService
from app.storage.checkout_store import (
    PendingCheckout,
    attach_session,
    get_pending,
    get_pending_by_session,
    mark_status,
    save_pending,
)


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
        save_pending(order_ref, customer_email, customer_name, line_payloads)

        self._configure_stripe()
        session = stripe.checkout.Session.create(
            mode="payment",
            currency="gbp",
            customer_email=customer_email.strip(),
            client_reference_id=order_ref,
            metadata={"external_order_id": order_ref},
            line_items=[
                {
                    "price_data": {
                        "currency": "gbp",
                        "unit_amount": self._to_pence(line.unit_price_gbp),
                        "product_data": {"name": f"{line.sku} × {line.quantity}"},
                    },
                    "quantity": line.quantity,
                }
                for line in lines
            ],
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

    async def _fulfill_completed_session(self, session: dict[str, Any]) -> dict[str, Any]:
        if session.get("payment_status") != "paid":
            return {"handled": False, "reason": "payment_not_paid"}

        external_order_id = (
            (session.get("metadata") or {}).get("external_order_id")
            or session.get("client_reference_id")
            or ""
        ).strip()
        if not external_order_id:
            raise ValueError("Missing external_order_id on Stripe session.")

        pending = get_pending(external_order_id)
        if not pending:
            raise ValueError(f"No pending checkout for {external_order_id}.")

        if pending.status == "paid":
            order = await self._orders.get_by_external_id(external_order_id)
            return {"handled": True, "duplicate": True, "order": order}

        result = await self._orders.submit_after_payment(
            CheckoutRequest(
                customer_email=pending.customer_email,
                customer_name=pending.customer_name,
                lines=[self._line_from_dict(item) for item in pending.lines],
            ),
            external_order_id=external_order_id,
            stripe_session_id=session.get("id", ""),
            stripe_payment_intent_id=str(session.get("payment_intent") or ""),
        )
        mark_status(external_order_id, "paid")
        return {"handled": True, "duplicate": bool(result.get("duplicate")), "order": result}

    def _mark_expired(self, session: dict[str, Any]) -> dict[str, Any]:
        external_order_id = (
            (session.get("metadata") or {}).get("external_order_id")
            or session.get("client_reference_id")
            or ""
        ).strip()
        if external_order_id:
            mark_status(external_order_id, "expired")
        return {"handled": True, "status": "expired"}

    async def get_success_context(self, session_id: str) -> dict[str, Any]:
        self._configure_stripe()
        session = stripe.checkout.Session.retrieve(session_id)
        pending = get_pending_by_session(session_id)
        external_order_id = (
            (session.get("metadata") or {}).get("external_order_id")
            or session.get("client_reference_id")
            or (pending.external_order_id if pending else "")
        )
        order = None
        if external_order_id:
            order = await self._orders.get_by_external_id(external_order_id)
        return {
            "session_id": session_id,
            "payment_status": session.get("payment_status"),
            "external_order_id": external_order_id,
            "customer_email": session.get("customer_details", {}).get("email") or (pending.customer_email if pending else ""),
            "order": order,
            "paid": session.get("payment_status") == "paid",
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

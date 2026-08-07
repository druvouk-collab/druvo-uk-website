"""Submit website basket orders to DRUVO AI master inventory."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.config import get_settings
from app.lib.druvo_api.client import DruvoApiClient


@dataclass
class CheckoutLine:
    sku: str
    quantity: int
    unit_price_gbp: float
    variant_id: int | None = None


@dataclass
class CheckoutRequest:
    customer_email: str
    customer_name: str
    lines: list[CheckoutLine]


class WebsiteOrderService:
    """Forward validated checkout payloads to DRUVO AI when API mode is enabled."""

    def __init__(self, client: DruvoApiClient | None = None) -> None:
        self._client_override = client

    @property
    def _settings(self):
        return get_settings()

    @property
    def _client(self) -> DruvoApiClient | None:
        if self._client_override is not None:
            return self._client_override
        settings = self._settings
        if settings.catalog_source != "druvo_api":
            return None
        return DruvoApiClient.from_settings(settings)

    @property
    def orders_enabled(self) -> bool:
        settings = self._settings
        return (
            settings.catalog_source == "druvo_api"
            and bool(settings.druvo_api_base_url)
            and bool(settings.druvo_api_key)
        )

    async def validate_stock(self, lines: list[CheckoutLine]) -> dict:
        client = self._client
        if client is None:
            raise RuntimeError("Stock validation requires DRUVO API configuration.")
        return await client.check_stock(
            [
                {
                    "sku": line.sku,
                    "quantity": line.quantity,
                    **({"variant_id": line.variant_id} if line.variant_id is not None else {}),
                }
                for line in lines
            ]
        )

    async def submit_after_payment(
        self,
        request: CheckoutRequest,
        *,
        external_order_id: str,
        stripe_session_id: str = "",
        stripe_payment_intent_id: str = "",
        shipping_gbp: float = 0.0,
    ) -> dict:
        """Create a DRUVO order after Stripe confirms payment (webhook-only path)."""
        client = self._client
        if client is None:
            raise RuntimeError(
                "Order submission requires CATALOG_SOURCE=druvo_api with DRUVO_API_BASE_URL and DRUVO_API_KEY."
            )
        if not request.lines:
            raise ValueError("Basket is empty.")
        stock = await self.validate_stock(request.lines)
        if not stock.get("ok"):
            insufficient = [
                line["sku"] for line in stock.get("lines", []) if not line.get("sufficient")
            ]
            raise ValueError(f"Insufficient stock for: {', '.join(insufficient)}")
        payload = {
            "external_order_id": external_order_id.strip(),
            "customer_email": request.customer_email.strip(),
            "customer_name": request.customer_name.strip(),
            "stripe_session_id": stripe_session_id,
            "stripe_payment_intent_id": stripe_payment_intent_id,
            "payment_provider": "stripe",
            "shipping_gbp": round(float(shipping_gbp), 2),
            "lines": [
                {
                    "sku": line.sku,
                    "quantity": line.quantity,
                    "unit_price_gbp": line.unit_price_gbp,
                }
                for line in request.lines
            ],
        }
        return await client.submit_order(payload)

    async def get_by_external_id(self, external_order_id: str) -> dict | None:
        client = self._client
        if client is None or not external_order_id.strip():
            return None
        return await client.get_order(external_order_id.strip())

    async def submit(
        self,
        request: CheckoutRequest,
        *,
        external_order_id: str | None = None,
    ) -> dict:
        """Legacy direct submit — blocked when Stripe payments are enabled."""
        if self._settings.payments_enabled:
            raise RuntimeError("Direct order submission is disabled when Stripe payments are enabled.")
        order_id = external_order_id or f"web-{uuid.uuid4().hex[:16]}"
        return await self.submit_after_payment(request, external_order_id=order_id)

    async def list_orders(self, customer_email: str) -> list[dict]:
        if not self.orders_enabled or self._client is None:
            return []
        return await self._client.list_orders_for_email(customer_email.strip())

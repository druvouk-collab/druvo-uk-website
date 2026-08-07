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


@dataclass
class CheckoutRequest:
    customer_email: str
    customer_name: str
    lines: list[CheckoutLine]


class WebsiteOrderService:
    """Forward validated checkout payloads to DRUVO AI when API mode is enabled."""

    def __init__(self, client: DruvoApiClient | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = client or (
            DruvoApiClient.from_settings(settings) if settings.catalog_source == "druvo_api" else None
        )

    @property
    def orders_enabled(self) -> bool:
        settings = self._settings
        return (
            settings.catalog_source == "druvo_api"
            and bool(settings.druvo_api_base_url)
            and bool(settings.druvo_api_key)
        )

    async def validate_stock(self, lines: list[CheckoutLine]) -> dict:
        if not self.orders_enabled or self._client is None:
            raise RuntimeError("Stock validation requires DRUVO API configuration.")
        return await self._client.check_stock(
            [{"sku": line.sku, "quantity": line.quantity} for line in lines]
        )

    async def submit(
        self,
        request: CheckoutRequest,
        *,
        external_order_id: str | None = None,
    ) -> dict:
        if not self.orders_enabled or self._client is None:
            raise RuntimeError(
                "Order submission requires CATALOG_SOURCE=druvo_api with DRUVO_API_BASE_URL and DRUVO_API_KEY."
            )
        if not request.lines:
            raise ValueError("Basket is empty.")
        stock = await self.validate_stock(request.lines)
        if not stock.get("ok"):
            insufficient = [
                line["sku"]
                for line in stock.get("lines", [])
                if not line.get("sufficient")
            ]
            raise ValueError(f"Insufficient stock for: {', '.join(insufficient)}")
        order_id = external_order_id or f"web-{uuid.uuid4().hex[:16]}"
        payload = {
            "external_order_id": order_id,
            "customer_email": request.customer_email.strip(),
            "customer_name": request.customer_name.strip(),
            "lines": [
                {
                    "sku": line.sku,
                    "quantity": line.quantity,
                    "unit_price_gbp": line.unit_price_gbp,
                }
                for line in request.lines
            ],
        }
        return await self._client.submit_order(payload)

    async def list_orders(self, customer_email: str) -> list[dict]:
        if not self.orders_enabled or self._client is None:
            return []
        return await self._client.list_orders_for_email(customer_email.strip())

"""Account order history from DRUVO AI when API mode is enabled."""

from __future__ import annotations

from app.config import get_settings
from app.lib.druvo_api.client import DruvoApiClient
from app.lib.druvo_api.mapper import map_order
from app.types.commerce import Order


class AccountOrderService:
    def __init__(self) -> None:
        pass

    @property
    def _settings(self):
        return get_settings()

    @property
    def live_orders_enabled(self) -> bool:
        settings = self._settings
        return (
            settings.catalog_source == "druvo_api"
            and bool(settings.druvo_api_base_url)
            and bool(settings.druvo_api_key)
        )

    def _client(self) -> DruvoApiClient:
        return DruvoApiClient.from_settings(self._settings)

    async def list_orders_for_email(self, email: str) -> list[Order]:
        if not self.live_orders_enabled or not email.strip():
            return []
        rows = await self._client().list_orders_for_email(email.strip())
        return [map_order(row) for row in rows]

    async def get_order(self, order_id: str, email: str = "") -> Order | None:
        if not self.live_orders_enabled:
            return None
        client = self._client()
        row = await client.get_order(order_id)
        if row:
            if email.strip() and row.get("customer_email", "").lower() != email.strip().lower():
                return None
            return map_order(row)
        if email.strip():
            for order in await self.list_orders_for_email(email):
                if order.id == order_id:
                    return order
        return None

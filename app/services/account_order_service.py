"""Account order history from DRUVO AI when API mode is enabled."""

from __future__ import annotations

from app.config import get_settings
from app.lib.druvo_api.client import DruvoApiClient
from app.lib.druvo_api.mapper import map_order
from app.types.commerce import Order


class AccountOrderService:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def live_orders_enabled(self) -> bool:
        return (
            self._settings.catalog_source == "druvo_api"
            and bool(self._settings.druvo_api_base_url)
            and bool(self._settings.druvo_api_key)
        )

    async def list_orders_for_email(self, email: str) -> list[Order]:
        if not self.live_orders_enabled or not email.strip():
            return []
        client = DruvoApiClient.from_settings(self._settings)
        rows = await client.list_orders_for_email(email.strip())
        return [map_order(row) for row in rows]

    async def get_order(self, order_id: str, email: str = "") -> Order | None:
        orders = await self.list_orders_for_email(email) if email else []
        if not orders and self.live_orders_enabled and email:
            orders = await self.list_orders_for_email(email)
        for order in orders:
            if order.id == order_id:
                return order
        return None

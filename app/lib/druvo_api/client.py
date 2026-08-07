"""Future DRUVO AI Enterprise API client — not wired to live data yet."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Settings
from app.types.commerce import Order, Product


@dataclass
class DruvoApiClient:
    """HTTP client for DRUVO AI as master inventory / order backend."""

    base_url: str
    api_key: str
    timeout: float = 30.0

    @classmethod
    def from_settings(cls, settings: Settings) -> DruvoApiClient:
        return cls(
            base_url=settings.druvo_api_base_url.rstrip("/"),
            api_key=settings.druvo_api_key,
            timeout=float(settings.druvo_api_timeout_seconds),
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "DRUVO-UK-Website/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def list_products(self) -> list[Product]:
        """Fetch master catalog from DRUVO AI (future endpoint)."""
        if not self.base_url:
            raise RuntimeError("DRUVO_API_BASE_URL is not configured")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/v1/products", headers=self._headers())
            response.raise_for_status()
            # Mapping will be implemented when DRUVO AI exposes a stable REST API.
            raise NotImplementedError("DRUVO AI catalog API mapping is not yet available")

    async def get_product(self, slug: str) -> Product | None:
        if not self.base_url:
            raise RuntimeError("DRUVO_API_BASE_URL is not configured")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/products/{slug}", headers=self._headers()
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            raise NotImplementedError("DRUVO AI product API mapping is not yet available")

    async def list_orders_for_customer(self, customer_id: str) -> list[Order]:
        if not self.base_url:
            raise RuntimeError("DRUVO_API_BASE_URL is not configured")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/customers/{customer_id}/orders",
                headers=self._headers(),
            )
            response.raise_for_status()
            raise NotImplementedError("DRUVO AI orders API mapping is not yet available")

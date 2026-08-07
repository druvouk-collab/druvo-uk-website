"""DRUVO AI Enterprise API client for master inventory sync."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Settings
from app.lib.druvo_api.key_sanitize import bearer_auth_header
from app.lib.druvo_api.mapper import map_category, map_product
from app.types.commerce import Category, Order, Product


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
        headers.update(bearer_auth_header(self.api_key))
        return headers

    async def list_products(self) -> list[Product]:
        if not self.base_url:
            raise RuntimeError("DRUVO_API_BASE_URL is not configured")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/v1/products", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            return [map_product(item) for item in payload.get("products", [])]

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
            return map_product(response.json())

    async def list_categories(self) -> list[Category]:
        if not self.base_url:
            raise RuntimeError("DRUVO_API_BASE_URL is not configured")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/api/v1/categories", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            return [map_category(item) for item in payload.get("categories", [])]

    async def submit_order(self, payload: dict) -> dict:
        if not self.base_url:
            raise RuntimeError("DRUVO_API_BASE_URL is not configured")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/orders",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def check_stock(self, lines: list[dict]) -> dict:
        if not self.base_url:
            raise RuntimeError("DRUVO_API_BASE_URL is not configured")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/stock/check",
                headers=self._headers(),
                json={"lines": lines},
            )
            response.raise_for_status()
            return response.json()

    async def list_orders_for_email(self, customer_email: str) -> list[dict]:
        if not self.base_url:
            raise RuntimeError("DRUVO_API_BASE_URL is not configured")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/v1/orders",
                headers=self._headers(),
                params={"customer_email": customer_email},
            )
            response.raise_for_status()
            return response.json().get("orders", [])

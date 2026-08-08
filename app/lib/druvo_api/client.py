"""DRUVO AI Enterprise API client for master inventory sync."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Settings
from app.lib.druvo_api.errors import CatalogApiError
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

    def _require_config(self) -> None:
        if not self.base_url:
            raise CatalogApiError(
                "DRUVO API base URL is not configured.",
                cause="missing_base_url",
            )
        if not self.api_key:
            raise CatalogApiError(
                "DRUVO API key is not configured.",
                cause="missing_api_key",
            )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "DRUVO-UK-Website/0.1"}
        headers.update(bearer_auth_header(self.api_key))
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        self._require_config()
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.TimeoutException as exc:
            raise CatalogApiError("DRUVO API request timed out.", cause="timeout") from exc
        except httpx.HTTPError as exc:
            raise CatalogApiError("Could not reach DRUVO API.", cause=type(exc).__name__) from exc

    async def list_products(self) -> list[Product]:
        response = await self._request("GET", "/api/v1/products")
        if response.status_code == 401 or response.status_code == 403:
            raise CatalogApiError("DRUVO API rejected credentials.", cause=f"http_{response.status_code}")
        response.raise_for_status()
        payload = response.json()
        return [map_product(item) for item in payload.get("products", [])]

    async def get_product(self, slug: str) -> Product | None:
        response = await self._request("GET", f"/api/v1/products/{slug}")
        if response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            raise CatalogApiError("DRUVO API rejected credentials.", cause=f"http_{response.status_code}")
        response.raise_for_status()
        return map_product(response.json())

    async def list_categories(self) -> list[Category]:
        response = await self._request("GET", "/api/v1/categories")
        if response.status_code in (401, 403):
            raise CatalogApiError("DRUVO API rejected credentials.", cause=f"http_{response.status_code}")
        response.raise_for_status()
        payload = response.json()
        return [map_category(item) for item in payload.get("categories", [])]

    async def submit_order(self, payload: dict) -> dict:
        response = await self._request("POST", "/api/v1/orders", json=payload)
        if response.status_code >= 400:
            raise CatalogApiError(
                "DRUVO API rejected order submission.",
                cause=f"http_{response.status_code}",
            )
        return response.json()

    async def check_stock(self, lines: list[dict]) -> dict:
        response = await self._request("POST", "/api/v1/stock/check", json={"lines": lines})
        response.raise_for_status()
        return response.json()

    async def list_orders_for_email(self, customer_email: str) -> list[dict]:
        response = await self._request(
            "GET",
            "/api/v1/orders",
            params={"customer_email": customer_email},
        )
        response.raise_for_status()
        return response.json().get("orders", [])

    async def get_order(self, order_ref: str) -> dict | None:
        response = await self._request("GET", f"/api/v1/orders/{order_ref}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def list_promotions(self, active_only: bool = True) -> list[dict]:
        response = await self._request(
            "GET",
            "/api/v1/promotions",
            params={"active_only": str(active_only).lower()},
        )
        if response.status_code in (401, 403):
            raise CatalogApiError("DRUVO API rejected credentials.", cause=f"http_{response.status_code}")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json().get("promotions", [])

    async def ping(self) -> bool:
        """Return True when DRUVO API health responds (no catalog auth required)."""
        if not self.base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/api/v1/health")
                return response.status_code == 200
        except httpx.HTTPError:
            return False

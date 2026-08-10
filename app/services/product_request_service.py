"""Forward customer product requests to DRUVO Core API."""

from __future__ import annotations

import logging

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

_CONSENT_TEXT = (
    "I agree that DRUVO UK may store my contact details to respond about this product request."
)


class ProductRequestService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def submit(self, payload: dict) -> dict:
        base = (self._settings.druvo_api_base_url or "").rstrip("/")
        api_key = self._settings.druvo_api_key.strip()
        if not base or not api_key:
            raise RuntimeError("Product request API is not configured.")

        body = {
            "requested_item": payload.get("requested_item", ""),
            "customer_name": payload.get("customer_name", ""),
            "brand": payload.get("brand", ""),
            "size": payload.get("size", ""),
            "colour": payload.get("colour", ""),
            "budget_gbp": payload.get("budget_gbp"),
            "email": payload.get("email", ""),
            "phone": payload.get("phone", ""),
            "notes": payload.get("notes", ""),
            "consent_given": bool(payload.get("consent_given")),
            "consent_text": payload.get("consent_text") or _CONSENT_TEXT,
            "source": "chat",
        }
        async with httpx.AsyncClient(timeout=self._settings.druvo_api_timeout_seconds) as client:
            response = await client.post(
                f"{base}/api/v1/customer-product-requests",
                json=body,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if response.status_code >= 400:
            logger.warning("Product request API error %s", response.status_code)
            raise RuntimeError("Could not save your request right now.")
        return response.json()

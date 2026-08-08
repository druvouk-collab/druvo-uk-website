"""Load active website promotions from DRUVO AI API (single source of truth)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.lib.druvo_api.client import DruvoApiClient
from app.lib.druvo_api.errors import CatalogApiError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Promotion:
    id: int | None
    name: str
    description: str = ""
    discount_type: str = ""
    discount_value: float = 0.0
    min_spend_gbp: float | None = None
    promo_code: str = ""
    customer_terms: str = ""
    eligible_product_ids: list[int] = field(default_factory=list)
    eligible_category_slugs: list[str] = field(default_factory=list)
    start_at: str = ""
    end_at: str = ""
    active: bool = True

    @classmethod
    def from_payload(cls, payload: dict) -> Promotion:
        return cls(
            id=payload.get("id"),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            discount_type=str(payload.get("discount_type") or ""),
            discount_value=float(payload.get("discount_value") or 0),
            min_spend_gbp=payload.get("min_spend_gbp"),
            promo_code=str(payload.get("promo_code") or ""),
            customer_terms=str(payload.get("customer_terms") or ""),
            eligible_product_ids=[int(x) for x in (payload.get("eligible_product_ids") or []) if x],
            eligible_category_slugs=[str(x) for x in (payload.get("eligible_category_slugs") or []) if x],
            start_at=str(payload.get("start_at") or ""),
            end_at=str(payload.get("end_at") or ""),
            active=bool(payload.get("active", True)),
        )

    def is_currently_active(self, now: datetime | None = None) -> bool:
        if not self.active:
            return False
        now = now or datetime.now(timezone.utc)
        if self.start_at:
            try:
                start = datetime.fromisoformat(self.start_at.replace("Z", "+00:00"))
                if now < start:
                    return False
            except ValueError:
                pass
        if self.end_at:
            try:
                end = datetime.fromisoformat(self.end_at.replace("Z", "+00:00"))
                if now > end:
                    return False
            except ValueError:
                pass
        return True


class PromotionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def list_active(self) -> list[Promotion]:
        if self._settings.catalog_source != "druvo_api":
            return _mock_promotions()
        client = DruvoApiClient.from_settings(self._settings)
        try:
            payloads = await client.list_promotions(active_only=True)
        except CatalogApiError as exc:
            logger.warning("Promotions unavailable: %s", exc)
            return []
        promos = [Promotion.from_payload(p) for p in payloads]
        return [p for p in promos if p.is_currently_active()]


def _mock_promotions() -> list[Promotion]:
    return [
        Promotion(
            id=1,
            name="Free delivery over £75",
            description="Free standard UK delivery when your order subtotal is £75 or more.",
            discount_type="free_shipping",
            min_spend_gbp=75.0,
            active=True,
        ),
    ]

"""UK shipping charge calculation for checkout and Stripe."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings


@dataclass(frozen=True)
class ShippingQuote:
    subtotal_gbp: float
    shipping_gbp: float
    total_gbp: float
    free_shipping: bool

    def as_dict(self) -> dict:
        return {
            "subtotal_gbp": round(self.subtotal_gbp, 2),
            "shipping_gbp": round(self.shipping_gbp, 2),
            "total_gbp": round(self.total_gbp, 2),
            "free_shipping": self.free_shipping,
        }


def calculate_shipping(subtotal_gbp: float, settings: Settings | None = None) -> ShippingQuote:
    cfg = settings or get_settings()
    subtotal = max(0.0, float(subtotal_gbp))
    free = subtotal >= float(cfg.shipping_free_threshold_gbp)
    shipping = 0.0 if free else float(cfg.shipping_standard_gbp)
    return ShippingQuote(
        subtotal_gbp=subtotal,
        shipping_gbp=shipping,
        total_gbp=subtotal + shipping,
        free_shipping=free,
    )

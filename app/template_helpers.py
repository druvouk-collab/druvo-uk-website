"""Shared template helpers."""

from __future__ import annotations

from app.config import get_settings


def format_gbp(amount: float) -> str:
    return f"£{amount:,.2f}"


def template_globals() -> dict:
    settings = get_settings()
    return {
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "contact_email": settings.contact_email,
        "format_gbp": format_gbp,
        "current_year": 2026,
        "placeholder_product": "/static/images/placeholder-product.svg",
        "placeholder_category": "/static/images/placeholder-category.svg",
    }

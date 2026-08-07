"""Shared template helpers."""

from __future__ import annotations

from app.config import get_settings
from app.services.seo_service import canonical_site_url, canonical_url_for


def format_gbp(amount: float) -> str:
    return f"£{amount:,.2f}"


def google_site_verification_token() -> str:
    """Read verification token fresh from settings (supports Render env + tests)."""
    return get_settings().google_site_verification.strip()


def template_globals() -> dict:
    settings = get_settings()
    return {
        "site_name": settings.site_name,
        "site_url": settings.site_url,
        "canonical_base": canonical_site_url(settings),
        "canonical_url_for": canonical_url_for,
        "contact_email": settings.contact_email,
        "google_site_verification_token": google_site_verification_token,
        "chat_enabled": settings.chat_enabled,
        "format_gbp": format_gbp,
        "current_year": 2026,
        "placeholder_product": "/static/images/placeholder-product.svg",
        "placeholder_category": "/static/images/placeholder-category.svg",
    }

"""Shared template helpers."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.config import get_settings
from app.services.seo_service import canonical_site_url, canonical_url_for
from app.services.seo_metadata import product_image_alt

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
_STATIC_VERSION: str | None = None


def format_gbp(amount: float) -> str:
    return f"£{amount:,.2f}"


def google_site_verification_token() -> str:
    """Read verification token fresh from settings (supports Render env + tests)."""
    return get_settings().google_site_verification.strip()


def static_asset_version() -> str:
    """Cache-bust query for /static assets (immutable CDN cache)."""
    global _STATIC_VERSION
    if _STATIC_VERSION is not None:
        return _STATIC_VERSION

    commit = os.getenv("RENDER_GIT_COMMIT", "").strip()
    if commit:
        _STATIC_VERSION = commit[:12]
        return _STATIC_VERSION

    digest = hashlib.sha256()
    for rel in ("css/druvo.css", "js/chat.js", "js/cart.js", "js/images.js"):
        path = STATIC_DIR / rel
        if path.is_file():
            digest.update(path.read_bytes())
    _STATIC_VERSION = digest.hexdigest()[:12] or "dev"
    return _STATIC_VERSION


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
        "product_image_alt": product_image_alt,
        "static_asset_version": static_asset_version,
        "current_year": 2026,
        "placeholder_product": "/static/images/placeholder-product.svg",
        "placeholder_category": "/static/images/placeholder-category.svg",
    }

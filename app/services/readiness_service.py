"""Production readiness checks for DRUVO UK website."""

from __future__ import annotations

import os
from typing import Any

from app.config import Settings, get_settings
from app.lib.druvo_api.client import DruvoApiClient
from app.services.email_service import EmailService


def _check(name: str, ok: bool, detail: str = "", *, required: bool = True) -> dict:
    return {"name": name, "ok": ok, "required": required, "detail": detail}


async def build_readiness_report(settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    checks: list[dict] = []

    checks.append(_check("catalog_source_live", cfg.catalog_source == "druvo_api", cfg.catalog_source))
    checks.append(_check("druvo_api_base_url", bool(cfg.druvo_api_base_url)))
    checks.append(_check("druvo_api_key", bool(cfg.druvo_api_key) and len(cfg.druvo_api_key) == 43))
    checks.append(_check("site_url_public", not cfg._is_local_url(cfg.public_site_url), cfg.public_site_url))
    checks.append(
        _check(
            "session_secret",
            bool(cfg.session_secret) and cfg.session_secret != "dev-only-change-in-production",
        )
    )

    stripe_mode = "missing"
    if cfg.stripe_secret_key.startswith("sk_live"):
        stripe_mode = "live"
    elif cfg.stripe_secret_key.startswith("sk_test"):
        stripe_mode = "test"
    checks.append(_check("stripe_secret_key", bool(cfg.stripe_secret_key), stripe_mode))
    checks.append(_check("stripe_publishable_key", bool(cfg.stripe_publishable_key)))
    checks.append(_check("stripe_webhook_secret", bool(cfg.stripe_webhook_secret)))
    checks.append(
        _check(
            "stripe_test_mode",
            stripe_mode == "test",
            "Stripe is in test mode (required until launch sign-off).",
            required=False,
        )
    )
    checks.append(
        _check(
            "stripe_not_live_accidentally",
            stripe_mode != "live" or cfg.stripe_live_mode_confirmed,
            "Live Stripe keys require STRIPE_LIVE_MODE_CONFIRM=true.",
        )
    )

    email = EmailService(cfg)
    checks.append(_check("email_smtp", email.configured, "SMTP host and from-address required for customer emails."))

    checks.append(_check("shipping_config", cfg.shipping_standard_gbp >= 0))
    checks.append(
        _check(
            "admin_checklist_token",
            bool(cfg.admin_checklist_token),
            "Set ADMIN_CHECKLIST_TOKEN to protect /admin/launch-checklist.",
            required=False,
        )
    )

    api_reachable = False
    catalog_ok = False
    if cfg.catalog_source == "druvo_api" and cfg.druvo_api_base_url:
        client = DruvoApiClient.from_settings(cfg)
        api_reachable = await client.ping()
        checks.append(_check("druvo_api_reachable", api_reachable))
        if api_reachable and cfg.druvo_api_key:
            try:
                products = await client.list_products()
                catalog_ok = len(products) > 0
                checks.append(_check("druvo_catalog_nonempty", catalog_ok, f"{len(products)} products"))
            except Exception as exc:
                checks.append(_check("druvo_catalog_nonempty", False, type(exc).__name__))

    required_failed = [c for c in checks if c["required"] and not c["ok"]]
    ready = not required_failed

    return {
        "ready": ready,
        "service": "druvo-uk-website",
        "environment": "production" if cfg.production_mode else "development",
        "stripe_mode": stripe_mode,
        "payments_enabled": cfg.payments_enabled,
        "git_commit": os.getenv("RENDER_GIT_COMMIT", ""),
        "checks": checks,
        "required_failures": [c["name"] for c in required_failed],
    }

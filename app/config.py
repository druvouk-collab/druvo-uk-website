"""Application configuration — secrets from environment only."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.lib.druvo_api.key_sanitize import sanitize_api_base_url, sanitize_api_key

PRODUCTION_SITE_URL = "https://druvo.uk"
CANONICAL_HOST = "druvo.uk"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    site_name: str = "DRUVO UK"
    site_url: str = "http://127.0.0.1:8080"
    contact_email: str = "druvo.uk@gmail.com"
    catalog_source: str = "mock"
    database_url: str = ""
    # Transactional email (Resend HTTP API — works on any host, no SMTP ports needed)
    # One-time token for creating the first admin at /admin/setup?token=... (remove after setup)
    admin_setup_token: str = ""
    # Optional error monitoring (Sentry free developer plan). Leave blank to disable.
    sentry_dsn: str = ""
    # Shared secret for the DRUVO Manager sync API (Authorization: Bearer ...). 32+ random characters.
    manager_api_key: str = ""
    resend_api_key: str = ""
    email_from: str = "DRUVO UK <orders@druvo.uk>"
    shop_notification_email: str = ""
    # Legal business details — leave blank until verified by the owner; shown in emails/footer when set.
    business_legal_name: str = ""
    business_address: str = ""
    company_number: str = ""
    # Stripe Checkout sessions last at least 30 minutes; hold stock slightly longer.
    stock_reservation_minutes: int = 35
    druvo_api_base_url: str = ""
    druvo_api_key: str = ""
    druvo_api_timeout_seconds: int = 30
    druvo_api_image_timeout_seconds: int = 60
    session_secret: str = "dev-only-change-in-production"
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_live_mode_confirmed: bool = False
    production_mode: bool = False
    shipping_standard_gbp: float = 3.99
    shipping_free_threshold_gbp: float = 75.0
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    admin_checklist_token: str = ""
    openai_api_key: str = ""
    chat_model: str = "gpt-4o-mini"
    chat_enabled: bool = True
    chat_rate_limit_per_hour: int = 30
    google_site_verification: str = ""

    @property
    def stripe_mode(self) -> str:
        if self.stripe_secret_key.startswith("sk_live"):
            return "live"
        if self.stripe_secret_key.startswith("sk_test"):
            return "test"
        return "missing"

    @property
    def database_enabled(self) -> bool:
        return self.catalog_source == "db" and bool(self.database_url)

    @property
    def email_orders_enabled(self) -> bool:
        """Free-hosting mode: customers order by email, no online payment."""
        return self.catalog_source == "static"

    @property
    def resend_enabled(self) -> bool:
        return bool(self.resend_api_key)

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_publishable_key)

    @property
    def db_payments_enabled(self) -> bool:
        """Mac-independent checkout: PostgreSQL stock + Stripe Checkout."""
        return self.database_enabled and self.stripe_enabled and bool(self.stripe_webhook_secret)

    @property
    def payments_enabled(self) -> bool:
        if self.db_payments_enabled:
            return True
        return (
            self.catalog_source == "druvo_api"
            and bool(self.druvo_api_base_url)
            and bool(self.druvo_api_key)
            and self.stripe_enabled
        )

    @property
    def public_site_url(self) -> str:
        """Public HTTPS base URL for Stripe redirects (never localhost on Render)."""
        configured = self.site_url.strip().rstrip("/")
        if configured and not self._is_local_url(configured):
            return configured
        for candidate in (
            os.getenv("RENDER_EXTERNAL_URL", "").strip(),
            PRODUCTION_SITE_URL,
        ):
            if candidate:
                return candidate.rstrip("/")
        return configured or "http://127.0.0.1:8080"

    @staticmethod
    def _is_local_url(url: str) -> bool:
        lowered = url.lower()
        return (
            lowered.startswith("http://127.0.0.1")
            or lowered.startswith("http://localhost")
            or lowered.startswith("https://127.0.0.1")
            or lowered.startswith("https://localhost")
        )

    @field_validator("druvo_api_key", mode="before")
    @classmethod
    def _sanitize_druvo_api_key(cls, value: object) -> str:
        return sanitize_api_key(value)

    @field_validator("druvo_api_base_url", mode="before")
    @classmethod
    def _sanitize_druvo_api_base_url(cls, value: object) -> str:
        return sanitize_api_base_url(value)


@lru_cache
def get_settings() -> Settings:
    return Settings()

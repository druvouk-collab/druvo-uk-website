"""Application configuration — secrets from environment only."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.lib.druvo_api.key_sanitize import sanitize_api_base_url, sanitize_api_key

PRODUCTION_SITE_URL = "https://druvo-uk-website.onrender.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    site_name: str = "DRUVO UK"
    site_url: str = "http://127.0.0.1:8080"
    contact_email: str = "druvo.uk@gmail.com"
    catalog_source: str = "mock"
    druvo_api_base_url: str = ""
    druvo_api_key: str = ""
    druvo_api_timeout_seconds: int = 30
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

    @property
    def stripe_mode(self) -> str:
        if self.stripe_secret_key.startswith("sk_live"):
            return "live"
        if self.stripe_secret_key.startswith("sk_test"):
            return "test"
        return "missing"

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_publishable_key)

    @property
    def payments_enabled(self) -> bool:
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

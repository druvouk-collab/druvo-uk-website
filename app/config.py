"""Application configuration — secrets from environment only."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.lib.druvo_api.key_sanitize import sanitize_api_base_url, sanitize_api_key


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

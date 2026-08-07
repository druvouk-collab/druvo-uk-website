"""Application configuration — secrets from environment only."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()

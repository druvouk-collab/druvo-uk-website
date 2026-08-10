"""OpenAI configuration for DRUVO Chat — never log or expose API keys."""

from __future__ import annotations

import os
import re

OPENAI_ENV_VAR = "OPENAI_API_KEY"
_KEY_PATTERN = re.compile(r"^sk-[A-Za-z0-9_\-]{20,}$")


def resolve_openai_api_key() -> str:
    return os.getenv(OPENAI_ENV_VAR, "").strip()


def openai_key_status(key: str | None = None) -> str:
    resolved = (key or resolve_openai_api_key()).strip()
    if not resolved:
        return "missing"
    if not _KEY_PATTERN.match(resolved):
        return "invalid"
    return "configured"


def chat_ai_public_status(*, chat_enabled: bool, chat_model: str) -> dict[str, str | bool]:
    if not chat_enabled:
        return {
            "openai_key_status": "disabled",
            "ai_mode": "disabled",
            "ai_enabled": False,
            "env_var": OPENAI_ENV_VAR,
            "model": chat_model,
        }
    status = openai_key_status()
    return {
        "openai_key_status": status,
        "ai_mode": "openai_tools" if status == "configured" else "rules_fallback",
        "ai_enabled": status == "configured",
        "env_var": OPENAI_ENV_VAR,
        "model": chat_model,
    }


def openai_http_timeout_seconds() -> float:
    raw = os.getenv("DRUVO_OPENAI_TIMEOUT_SECONDS", "60").strip()
    try:
        return max(10.0, min(float(raw), 120.0))
    except ValueError:
        return 60.0

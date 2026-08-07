"""Sanitize DRUVO API keys from environment variables for safe HTTP headers."""

from __future__ import annotations

import re

_ENV_KEY_PREFIXES = ("DRUVO_WEBSITE_API_KEY=", "DRUVO_API_KEY=")
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,64}")


def sanitize_api_key(value: object) -> str:
    """Return a header-safe ASCII API key with common paste mistakes removed."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)

    cleaned = value.strip()

    # Whole env line pasted into Render (e.g. DRUVO_API_KEY=abc...).
    upper = cleaned.upper()
    for prefix in _ENV_KEY_PREFIXES:
        if upper.startswith(prefix):
            cleaned = cleaned.split("=", 1)[1].strip()
            break

    if cleaned.lower().startswith("bearer "):
        cleaned = cleaned[7:].strip()

    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1].strip()

    # DRUVO keys are ASCII; strip accidental Unicode from bad pastes (e.g. em dash).
    cleaned = cleaned.encode("ascii", "ignore").decode("ascii").strip()

    # Recover embedded token from polluted instructional paste text.
    if len(cleaned) > 64 and not _TOKEN_PATTERN.fullmatch(cleaned):
        match = _TOKEN_PATTERN.search(cleaned)
        if match:
            cleaned = match.group(0)

    return cleaned


def sanitize_api_base_url(value: object) -> str:
    """Return an ASCII-safe API base URL (no trailing slash)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)

    cleaned = value.strip().encode("ascii", "ignore").decode("ascii").strip()
    if cleaned.endswith("/"):
        cleaned = cleaned.rstrip("/")
    return cleaned


def bearer_auth_header(api_key: str) -> dict[str, str]:
    """Build Authorization header dict with a sanitized key."""
    key = sanitize_api_key(api_key)
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}

"""Tests for DRUVO API key sanitization."""

import httpx
import pytest

from app.config import Settings
from app.lib.druvo_api.key_sanitize import bearer_auth_header, sanitize_api_base_url, sanitize_api_key


def test_sanitize_strips_whitespace_and_bearer():
    raw = "  Bearer abc123  "
    assert sanitize_api_key(raw) == "abc123"


def test_sanitize_strips_quotes():
    assert sanitize_api_key('"abc123"') == "abc123"
    assert sanitize_api_key("'abc123'") == "abc123"


def test_sanitize_removes_unicode_for_headers():
    polluted = "abc123\u2014extra"
    cleaned = sanitize_api_key(polluted)
    assert cleaned == "abc123extra"
    httpx.Headers(bearer_auth_header(cleaned))


def test_sanitize_joins_split_token_runs():
    key43 = "a" * 43
    split = "\n".join(key43[i : i + 7] for i in range(0, 43, 7))
    assert sanitize_api_key(split) == key43


def test_sanitize_env_line_paste():
    assert sanitize_api_key("DRUVO_API_KEY=token12345678901234567890123456789012") == (
        "token12345678901234567890123456789012"
    )


def test_position_126_em_dash_crash_is_prevented():
    """Reproduce Render traceback: em dash at index 126 in Authorization value."""
    polluted_key = "x" * 119 + "\u2014"
    header_value = f"Bearer {polluted_key}"
    with pytest.raises(UnicodeEncodeError):
        header_value.encode("ascii")

    cleaned = sanitize_api_key(polluted_key)
    headers = bearer_auth_header(cleaned)
    httpx.Headers(headers)
    assert "\u2014" not in headers["Authorization"]
    headers["Authorization"].encode("ascii")


def test_settings_applies_sanitizer():
    settings = Settings(druvo_api_key='  Bearer "token-with-dash\u2014"  ')
    assert settings.druvo_api_key == "token-with-dash"


def test_sanitize_api_base_url_strips_unicode():
    assert sanitize_api_base_url("https://api.example.com/\u2014") == "https://api.example.com"

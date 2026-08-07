"""Pytest configuration."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def mock_catalog_by_default(monkeypatch):
    """Keep tests on mock catalog unless a test overrides env vars."""
    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    monkeypatch.delenv("DRUVO_API_BASE_URL", raising=False)
    monkeypatch.delenv("DRUVO_API_KEY", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

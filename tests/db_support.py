"""Shared database fixtures. Uses TEST_DATABASE_URL (PostgreSQL) when set, else a temp SQLite file."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base, _session_factory, get_engine


def _url(tmp_path: Path) -> str:
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'druvo_test.db'}"


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = _url(tmp_path)
    engine = get_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CATALOG_SOURCE", "db")
    get_settings.cache_clear()
    yield url
    Base.metadata.drop_all(engine)
    engine.dispose()
    get_engine.cache_clear()
    _session_factory.cache_clear()
    get_settings.cache_clear()

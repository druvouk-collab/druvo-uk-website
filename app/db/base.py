"""Database engine and session management.

DATABASE_URL comes from the environment only (Render → Environment). The app
never needs the DRUVO AI desktop app to read or write this database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    """Render/Neon give postgres:// or postgresql:// URLs; use the psycopg 3 driver."""
    url = (url or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@lru_cache(maxsize=4)
def get_engine(url: str) -> Engine:
    url = normalize_database_url(url)
    if not url:
        raise RuntimeError("DATABASE_URL is not configured.")
    kwargs: dict = {"future": True}
    if url.startswith("postgresql"):
        kwargs.update(pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300)
    return create_engine(url, **kwargs)


@lru_cache(maxsize=4)
def _session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False, future=True)


def database_url() -> str:
    from app.config import get_settings

    return get_settings().database_url


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on error."""
    session = _session_factory(url or database_url())()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

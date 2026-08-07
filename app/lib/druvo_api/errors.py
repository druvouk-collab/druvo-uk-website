"""Catalog API errors — safe to log without exposing secrets."""

from __future__ import annotations


class CatalogApiError(Exception):
    """DRUVO master catalog could not be loaded."""

    def __init__(self, message: str, *, cause: str = "") -> None:
        super().__init__(message)
        self.cause = cause

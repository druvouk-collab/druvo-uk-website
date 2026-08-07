"""Resilient catalog fetch results for storefront rendering."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.types.commerce import Category, Product


@dataclass
class CatalogSnapshot:
    products: list[Product] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    degraded: bool = False
    notice: str = ""

    @property
    def ok(self) -> bool:
        return not self.degraded

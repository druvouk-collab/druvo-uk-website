"""Catalog service — switches between mock data and future DRUVO AI API."""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.data import mock_catalog
from app.types.commerce import Category, Product


@dataclass
class CatalogFilters:
    query: str = ""
    category_slug: str | None = None
    size: str | None = None
    colour: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    in_stock_only: bool = False
    on_sale_only: bool = False
    new_arrivals_only: bool = False
    sort: str = "featured"


class CatalogService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def list_categories(self) -> list[Category]:
        if self._settings.catalog_source == "druvo_api":
            from app.lib.druvo_api.client import DruvoApiClient

            client = DruvoApiClient.from_settings(self._settings)
            return await client.list_categories()
        return mock_catalog.all_categories()

    async def list_products(self, filters: CatalogFilters | None = None) -> list[Product]:
        filters = filters or CatalogFilters()
        if self._settings.catalog_source == "druvo_api":
            from app.lib.druvo_api.client import DruvoApiClient

            client = DruvoApiClient.from_settings(self._settings)
            products = await client.list_products()
            return self._apply_filters(products, filters)
        return self._apply_filters(mock_catalog.all_products(), filters)

    async def get_product(self, slug: str) -> Product | None:
        if self._settings.catalog_source == "druvo_api":
            from app.lib.druvo_api.client import DruvoApiClient

            client = DruvoApiClient.from_settings(self._settings)
            return await client.get_product(slug)
        return mock_catalog.get_product(slug)

    async def get_category(self, slug: str) -> Category | None:
        if self._settings.catalog_source == "druvo_api":
            categories = await self.list_categories()
            return next((c for c in categories if c.slug == slug), None)
        return mock_catalog.get_category(slug)

    def _apply_filters(self, products: list[Product], filters: CatalogFilters) -> list[Product]:
        result = products

        if filters.query:
            q = filters.query.lower()
            result = [
                p
                for p in result
                if q in p.name.lower()
                or q in p.description.lower()
                or q in p.brand.lower()
                or any(q in t for t in p.tags)
            ]

        if filters.category_slug:
            result = [p for p in result if p.category_slug == filters.category_slug]

        if filters.size:
            result = [p for p in result if any(v.size == filters.size for v in p.variants)]

        if filters.colour:
            result = [p for p in result if any(v.colour == filters.colour for v in p.variants)]

        if filters.min_price is not None:
            result = [p for p in result if p.min_price >= filters.min_price]

        if filters.max_price is not None:
            result = [p for p in result if p.min_price <= filters.max_price]

        if filters.in_stock_only:
            result = [p for p in result if p.in_stock]

        if filters.on_sale_only:
            result = [p for p in result if p.is_on_sale]

        if filters.new_arrivals_only:
            result = [p for p in result if p.is_new_arrival]

        return self._sort(result, filters.sort)

    def _sort(self, products: list[Product], sort: str) -> list[Product]:
        if sort == "price-asc":
            return sorted(products, key=lambda p: p.min_price)
        if sort == "price-desc":
            return sorted(products, key=lambda p: p.min_price, reverse=True)
        if sort == "name":
            return sorted(products, key=lambda p: p.name.lower())
        # featured: new arrivals first, then name
        return sorted(products, key=lambda p: (not p.is_new_arrival, p.name.lower()))

    def available_sizes(self, products: list[Product]) -> list[str]:
        sizes = {v.size for p in products for v in p.variants}
        return sorted(sizes)

    def available_colours(self, products: list[Product]) -> list[str]:
        colours = {v.colour for p in products for v in p.variants}
        return sorted(colours)

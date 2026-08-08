"""Catalog service — switches between mock data and DRUVO AI master inventory API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from app.config import Settings, get_settings
from app.data import mock_catalog
from app.lib.druvo_api.client import DruvoApiClient
from app.lib.druvo_api.errors import CatalogApiError
from app.lib.druvo_api.image_proxy import to_website_proxy_path, to_website_proxy_url
from app.services.catalog_snapshot import CatalogSnapshot
from app.types.commerce import Category, Product

logger = logging.getLogger(__name__)

_DEGRADED_NOTICE = (
    "Our live catalog is temporarily unavailable. Please try again shortly — "
    "your basket is saved in this browser."
)


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
        self._settings_override = settings

    @property
    def _settings(self) -> Settings:
        return self._settings_override or get_settings()

    @property
    def uses_live_api(self) -> bool:
        return self._settings.catalog_source == "druvo_api"

    async def load_snapshot(self, filters: CatalogFilters | None = None) -> CatalogSnapshot:
        filters = filters or CatalogFilters()
        if not self.uses_live_api:
            products = self._apply_filters(mock_catalog.all_products(), filters)
            return CatalogSnapshot(
                products=products,
                categories=mock_catalog.all_categories(),
            )

        client = DruvoApiClient.from_settings(self._settings)
        try:
            products = self._proxy_images(await client.list_products())
            categories = await client.list_categories()
            return CatalogSnapshot(
                products=self._apply_filters(products, filters),
                categories=categories,
            )
        except CatalogApiError as exc:
            logger.warning("DRUVO catalog unavailable (%s): %s", exc.cause, exc)
            return CatalogSnapshot(degraded=True, notice=_DEGRADED_NOTICE)
        except Exception as exc:
            logger.exception("Unexpected catalog failure")
            return CatalogSnapshot(degraded=True, notice=_DEGRADED_NOTICE)

    async def list_categories(self) -> list[Category]:
        snapshot = await self.load_snapshot()
        return snapshot.categories

    async def list_products(self, filters: CatalogFilters | None = None) -> list[Product]:
        snapshot = await self.load_snapshot(filters)
        return snapshot.products

    async def get_product(self, slug: str) -> Product | None:
        if not self.uses_live_api:
            return mock_catalog.get_product(slug)

        client = DruvoApiClient.from_settings(self._settings)
        try:
            product = await client.get_product(slug)
            return self._proxy_product(product) if product else None
        except CatalogApiError:
            return None

    async def get_category(self, slug: str) -> Category | None:
        categories = await self.list_categories()
        return next((c for c in categories if c.slug == slug), None)

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
        return sorted(products, key=lambda p: (not p.is_new_arrival, p.name.lower()))

    def available_sizes(self, products: list[Product]) -> list[str]:
        sizes = {v.size for p in products for v in p.variants}
        return sorted(sizes)

    def available_colours(self, products: list[Product]) -> list[str]:
        colours = {v.colour for p in products for v in p.variants}
        return sorted(colours)

    def _proxy_images(self, products: list[Product]) -> list[Product]:
        if not self.uses_live_api:
            return products
        return [self._proxy_product(product) for product in products if product]

    @staticmethod
    def _proxy_product(product: Product | None) -> Product | None:
        if product is None:
            return None
        images = [to_website_proxy_url(image) for image in product.images if image]
        if not images:
            images = ["/static/images/placeholder-product.svg"]
        # map_product already emits proxy paths for gallery-aware payloads; avoid double-rewriting.
        if all(image.startswith("/api/catalog/images/") or image.startswith("/static/") for image in images):
            if images == product.images:
                return product
            return replace(product, images=images)
        if images == product.images:
            return product
        return replace(product, images=images)

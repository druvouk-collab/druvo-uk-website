"""Commerce domain types shared by templates, services, and future DRUVO API client."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProductVariant:
    sku: str
    size: str
    colour: str
    stock_quantity: int
    price_gbp: float
    variant_id: int | None = None

    @property
    def in_stock(self) -> bool:
        return self.stock_quantity > 0


@dataclass(frozen=True)
class Product:
    id: str
    slug: str
    name: str
    description: str
    category_slug: str
    category_name: str
    brand: str
    condition: str
    images: list[str]
    variants: list[ProductVariant]
    tags: list[str] = field(default_factory=list)
    is_new_arrival: bool = False
    is_on_sale: bool = False
    sale_price_gbp: float | None = None
    compare_at_price_gbp: float | None = None
    gtin: str = ""
    mpn: str = ""
    catalog_status: str = "demo"

    @property
    def is_live(self) -> bool:
        from app.services.catalog_visibility import is_live_catalog_product

        return is_live_catalog_product(self)

    @property
    def is_demo(self) -> bool:
        return not self.is_live

    @property
    def min_price(self) -> float:
        prices = [v.price_gbp for v in self.variants]
        if self.is_on_sale and self.sale_price_gbp is not None:
            return self.sale_price_gbp
        return min(prices) if prices else 0.0

    @property
    def max_price(self) -> float:
        prices = [v.price_gbp for v in self.variants]
        if self.is_on_sale and self.sale_price_gbp is not None:
            return self.sale_price_gbp
        return max(prices) if prices else 0.0

    @property
    def total_stock(self) -> int:
        return sum(v.stock_quantity for v in self.variants)

    @property
    def in_stock(self) -> bool:
        return self.total_stock > 0

    @property
    def sizes(self) -> list[str]:
        return sorted({v.size for v in self.variants})

    @property
    def colours(self) -> list[str]:
        return sorted({v.colour for v in self.variants})

    def variant_for(self, size: str, colour: str) -> ProductVariant | None:
        for variant in self.variants:
            if variant.size == size and variant.colour == colour:
                return variant
        return None

    def first_in_stock_variant(self) -> ProductVariant | None:
        for variant in self.variants:
            if variant.in_stock:
                return variant
        return None

    def colours_for_size(self, size: str) -> list[str]:
        return sorted({v.colour for v in self.variants if v.size == size and v.in_stock})

    def sizes_for_colour(self, colour: str) -> list[str]:
        return sorted({v.size for v in self.variants if v.colour == colour and v.in_stock})

    @property
    def display_price_gbp(self) -> float:
        if self.is_on_sale and self.sale_price_gbp is not None:
            return self.sale_price_gbp
        return self.min_price

    @property
    def product_url(self) -> str:
        return f"/product/{self.slug}"

    @property
    def absolute_product_url(self) -> str:
        from app.config import get_settings

        base = get_settings().public_site_url.rstrip("/")
        return f"{base}/product/{self.slug}"


@dataclass(frozen=True)
class Category:
    slug: str
    name: str
    description: str
    image: str


@dataclass(frozen=True)
class OrderLine:
    product_slug: str
    product_name: str
    sku: str
    size: str
    colour: str
    quantity: int
    unit_price_gbp: float


@dataclass(frozen=True)
class Order:
    id: str
    placed_at: str
    status: str
    tracking_number: str | None
    carrier: str | None
    lines: list[OrderLine]
    subtotal_gbp: float
    shipping_gbp: float
    total_gbp: float
    status_code: str = ""
    shipped_at: str | None = None
    delivered_at: str | None = None
    status_updated_at: str | None = None

    @property
    def has_tracking(self) -> bool:
        return bool(self.tracking_number and self.tracking_number.strip())

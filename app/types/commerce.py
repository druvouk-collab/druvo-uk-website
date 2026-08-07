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
    lines: list[OrderLine]
    subtotal_gbp: float
    shipping_gbp: float
    total_gbp: float

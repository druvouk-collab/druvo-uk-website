"""ORM models. Money is stored as integer pence to avoid rounding errors."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Category(TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Product(TimestampMixin, Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    brand: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    condition: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_new_arrival: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_on_sale: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sale_price_pence: Mapped[int | None] = mapped_column(Integer)
    compare_at_price_pence: Mapped[int | None] = mapped_column(Integer)
    gtin: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    mpn: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    # draft = hidden, live = on sale, archived = sold/removed (kept for order history and SEO redirects)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)

    category: Mapped[Category | None] = relationship(lazy="joined")
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ProductImage.position", lazy="selectin"
    )
    variants: Mapped[list[Variant]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="Variant.id", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint("status IN ('draft','live','archived')", name="ck_products_status"),
        Index("ix_products_status", "status"),
    )


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    alt: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    product: Mapped[Product] = relationship(back_populates="images")


class Variant(TimestampMixin, Base):
    __tablename__ = "variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    size: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    colour: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    price_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    # Units available to sell right now. Decremented when a checkout reserves stock.
    stock_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    product: Mapped[Product] = relationship(back_populates="variants")

    __table_args__ = (
        CheckConstraint("stock_quantity >= 0", name="ck_variants_stock_non_negative"),
        CheckConstraint("price_pence >= 0", name="ck_variants_price_non_negative"),
    )


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    marketing_opt_in: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


ORDER_STATUSES = (
    "pending_payment",
    "paid",
    "packed",
    "shipped",
    "delivered",
    "cancelled",
    "expired",
    "refunded",
    "partially_refunded",
)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"))
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending_payment", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="GBP", nullable=False)
    subtotal_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    shipping_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    total_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    refunded_pence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shipping_method: Mapped[str] = mapped_column(String(60), default="standard", nullable=False)
    shipping_address: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    phone: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    # Client-generated key so a double-clicked "Pay" button cannot create two orders.
    idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_checkout_url: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    payment_method_type: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    reservation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    carrier: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    tracking_number: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    tracking_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shop_notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    customer: Mapped[Customer | None] = relationship(lazy="joined")
    items: Mapped[list[OrderItem]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id", lazy="selectin"
    )
    reservations: Mapped[list[StockReservation]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN (" + ",".join(f"'{s}'" for s in ORDER_STATUSES) + ")", name="ck_orders_status"
        ),
        CheckConstraint("total_pence = subtotal_pence + shipping_pence", name="ck_orders_total"),
        Index("ix_orders_status_created", "status", "created_at"),
        Index("ix_orders_email", "email"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("variants.id", ondelete="SET NULL"))
    product_slug: Mapped[str] = mapped_column(String(200), nullable=False)
    product_name: Mapped[str] = mapped_column(String(300), nullable=False)
    sku: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    colour: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_pence: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")

    __table_args__ = (CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),)


class StockReservation(Base):
    __tablename__ = "stock_reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    # active = stock held for checkout, consumed = paid, released = returned to stock
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    order: Mapped[Order] = relationship(back_populates="reservations")

    __table_args__ = (
        CheckConstraint("status IN ('active','consumed','released')", name="ck_reservations_status"),
        Index("ix_reservations_status_expires", "status", "expires_at"),
    )


class StripeEvent(Base):
    """Every processed Stripe webhook event ID — replays are ignored."""

    __tablename__ = "stripe_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    stripe_refund_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    amount_pence: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    restocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    totp_secret: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(320), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class OutboxEvent(Base):
    """Events for DRUVO AI (orders, stock changes). Delivered asynchronously; never blocks checkout."""

    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_outbox_status", "status", "created_at"),)


__all__ = [
    "AdminUser",
    "AuditLog",
    "Category",
    "Customer",
    "Order",
    "OrderItem",
    "OutboxEvent",
    "Product",
    "ProductImage",
    "Refund",
    "StockReservation",
    "StripeEvent",
    "Variant",
    "ORDER_STATUSES",
]

"""Sales and profit reporting for the admin dashboard.

Net profit = money kept from sales (total paid − refunds) − item cost − Stripe fees
− marketplace commissions − postage − packaging − other expenses.
Figures are not VAT-adjusted (the business is not VAT registered at time of writing).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db import models
from app.db.base import session_scope

LONDON = ZoneInfo("Europe/London")
SALE_STATUSES = ("paid", "packed", "shipped", "delivered", "refunded", "partially_refunded")


@dataclass
class Totals:
    orders: int = 0
    items: int = 0
    gross_pence: int = 0
    refunds_pence: int = 0
    shipping_charged_pence: int = 0
    discounts_pence: int = 0
    cogs_pence: int = 0
    payment_fees_pence: int = 0
    marketplace_fees_pence: int = 0
    postage_pence: int = 0
    packaging_pence: int = 0
    expenses_pence: int = 0
    fees_unknown: int = 0
    by_channel: dict = field(default_factory=dict)

    @property
    def net_sales_pence(self) -> int:
        return self.gross_pence - self.refunds_pence

    @property
    def costs_pence(self) -> int:
        return (
            self.cogs_pence + self.payment_fees_pence + self.marketplace_fees_pence
            + self.postage_pence + self.packaging_pence + self.expenses_pence
        )

    @property
    def profit_pence(self) -> int:
        return self.net_sales_pence - self.costs_pence

    @property
    def margin_pct(self) -> float:
        return round(100 * self.profit_pence / self.net_sales_pence, 1) if self.net_sales_pence else 0.0

    @property
    def average_order_pence(self) -> int:
        return self.gross_pence // self.orders if self.orders else 0


def london_day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=LONDON).astimezone(timezone.utc)


def totals_between(start: datetime, end: datetime) -> Totals:
    t = Totals()
    with session_scope() as db:
        orders = db.scalars(
            select(models.Order).where(
                models.Order.paid_at >= start, models.Order.paid_at < end, models.Order.status.in_(SALE_STATUSES)
            )
        ).all()
        for o in orders:
            t.orders += 1
            t.gross_pence += o.total_pence
            t.refunds_pence += o.refunded_pence
            t.shipping_charged_pence += o.shipping_pence
            t.discounts_pence += o.discount_pence
            t.marketplace_fees_pence += o.marketplace_fee_pence
            t.postage_pence += o.postage_cost_pence
            t.packaging_pence += o.packaging_cost_pence
            if o.payment_fee_pence is None:
                t.fees_unknown += 1
            else:
                t.payment_fees_pence += o.payment_fee_pence
            fully_refunded = o.refunded_pence >= o.total_pence
            for item in o.items:
                t.items += item.quantity
                if not fully_refunded:
                    t.cogs_pence += item.unit_cost_pence * item.quantity
            ch = t.by_channel.setdefault(o.channel, {"orders": 0, "gross_pence": 0})
            ch["orders"] += 1
            ch["gross_pence"] += o.total_pence
        t.expenses_pence = int(
            db.scalar(
                select(func.coalesce(func.sum(models.Expense.amount_pence), 0)).where(
                    models.Expense.spent_on >= start, models.Expense.spent_on < end
                )
            )
            or 0
        )
    return t


def period_bounds(period: str, today: date | None = None) -> tuple[datetime, datetime, str]:
    today = today or datetime.now(LONDON).date()
    tomorrow = london_day_start(today + timedelta(days=1))
    if period == "today":
        return london_day_start(today), tomorrow, "Today"
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return london_day_start(start), tomorrow, "This week"
    if period == "month":
        return london_day_start(today.replace(day=1)), tomorrow, "This month"
    if period == "year":
        return london_day_start(today.replace(month=1, day=1)), tomorrow, "This year"
    raise ValueError(period)


def summary_cards(today: date | None = None) -> list[tuple[str, Totals]]:
    return [(label, totals_between(s, e)) for s, e, label in (period_bounds(p, today) for p in ("today", "week", "month", "year"))]


def breakdown(granularity: str, count: int = 12, today: date | None = None) -> list[tuple[str, Totals]]:
    """Rows for the reports table: day (last 14), week, month, year buckets in London time."""
    today = today or datetime.now(LONDON).date()
    rows: list[tuple[str, Totals]] = []
    for i in range(count):
        if granularity == "day":
            d = today - timedelta(days=i)
            start, end, label = d, d + timedelta(days=1), d.strftime("%a %d %b")
        elif granularity == "week":
            monday = today - timedelta(days=today.weekday()) - timedelta(weeks=i)
            start, end, label = monday, monday + timedelta(days=7), "w/c " + monday.strftime("%d %b %Y")
        elif granularity == "month":
            y, m = today.year, today.month - i
            while m <= 0:
                m += 12
                y -= 1
            start = date(y, m, 1)
            end = date(y + (m == 12), m % 12 + 1, 1)
            label = start.strftime("%B %Y")
        elif granularity == "year":
            start, end, label = date(today.year - i, 1, 1), date(today.year - i + 1, 1, 1), str(today.year - i)
        else:
            raise ValueError(granularity)
        rows.append((label, totals_between(london_day_start(start), london_day_start(end))))
    return rows


def low_stock(limit: int = 50) -> list[dict]:
    with session_scope() as db:
        rows = db.execute(
            select(models.Variant, models.Product)
            .join(models.Product, models.Variant.product_id == models.Product.id)
            .where(models.Product.status == "live", models.Variant.stock_quantity <= models.Variant.low_stock_threshold)
            .order_by(models.Variant.stock_quantity, models.Product.name)
            .limit(limit)
        ).all()
        return [
            {"product_id": p.id, "name": p.name, "sku": v.sku, "size": v.size, "stock": v.stock_quantity,
             "threshold": v.low_stock_threshold}
            for v, p in rows
        ]


def pending_orders(limit: int = 50) -> list[models.Order]:
    with session_scope() as db:
        return db.scalars(
            select(models.Order)
            .where(models.Order.status.in_(("paid", "packed")))
            .order_by(models.Order.paid_at)
            .limit(limit)
        ).all()


def orders_needing_attention() -> list[models.Order]:
    with session_scope() as db:
        return db.scalars(
            select(models.Order).where(
                models.Order.notes.contains("STOCK CONFLICT") | models.Order.notes.contains("AMOUNT MISMATCH"),
                models.Order.status.in_(("paid", "packed")),
            )
        ).all()

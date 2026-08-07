"""Website-side order status mapping and account display tests."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.lib.druvo_api.mapper import map_order
from app.main import app
from app.services.account_order_service import AccountOrderService


def test_map_order_includes_tracking_and_variant_lines():
    order = map_order(
        {
            "order_id": 12,
            "external_order_id": "web-abc123",
            "status": "shipped",
            "status_label": "Shipped",
            "created_at": "2026-08-07 12:00:00",
            "total_amount": 40.0,
            "tracking_number": "RM123456789GB",
            "carrier": "Royal Mail",
            "lines": [
                {
                    "sku": "DRUVO-2-NAVY-M",
                    "product_name": "Adidas Tracksuit",
                    "size": "M",
                    "colour": "Navy",
                    "quantity": 1,
                    "unit_price_gbp": 40.0,
                }
            ],
        }
    )
    assert order.status == "Shipped"
    assert order.tracking_number == "RM123456789GB"
    assert order.carrier == "Royal Mail"
    assert order.has_tracking is True
    assert order.lines[0].product_name == "Adidas Tracksuit"
    assert order.lines[0].size == "M"


def test_map_order_hides_tracking_when_missing():
    order = map_order(
        {
            "external_order_id": "web-no-track",
            "status": "received",
            "status_label": "Received",
            "created_at": "2026-08-07 12:00:00",
            "total_amount": 40.0,
            "lines": [],
        }
    )
    assert order.tracking_number is None
    assert order.carrier is None
    assert order.has_tracking is False


class _FakeOrderClient:
    def __init__(self) -> None:
        self.orders = [
            {
                "external_order_id": "web-live-1",
                "customer_email": "shopper@druvo.uk",
                "status": "processing",
                "status_label": "Processing",
                "created_at": "2026-08-07 13:00:00",
                "total_amount": 40.0,
                "lines": [],
            }
        ]

    async def list_orders_for_email(self, email: str):
        return [o for o in self.orders if o["customer_email"] == email]

    async def get_order(self, order_ref: str):
        for order in self.orders:
            if order["external_order_id"] == order_ref:
                return order
        return None


def test_account_service_reads_latest_status(monkeypatch):
    service = AccountOrderService()
    monkeypatch.setattr(
        AccountOrderService,
        "live_orders_enabled",
        property(lambda self: True),
    )
    service._client = lambda: _FakeOrderClient()  # type: ignore[method-assign]

    async def _run():
        orders = await service.list_orders_for_email("shopper@druvo.uk")
        assert orders[0].status == "Processing"
        order = await service.get_order("web-live-1", "shopper@druvo.uk")
        assert order is not None
        assert order.id == "web-live-1"

    import asyncio

    asyncio.run(_run())


@pytest.mark.asyncio
async def test_order_detail_shows_tracking_when_present():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/account/orders/DRU-10042")
        assert response.status_code == 200
        assert "RM123456789GB" in response.text
        assert "Royal Mail" in response.text

"""Phase B variant mapping and checkout integration tests."""

from __future__ import annotations

from dataclasses import asdict

from app.lib.druvo_api.mapper import map_product
from app.services.order_service import CheckoutLine, WebsiteOrderService
from app.types.commerce import Product


def test_map_product_without_variants():
    product = map_product(
        {
            "id": "3",
            "slug": "druvo-3",
            "name": "Simple Product",
            "description": "",
            "category_slug": "tops",
            "category_name": "Tops",
            "brand": "",
            "condition": "Pre-loved",
            "images": [],
            "variants": [
                {
                    "variant_id": None,
                    "sku": "DRUVO-3",
                    "size": "One Size",
                    "colour": "Default",
                    "stock_quantity": 5,
                    "price_gbp": 20.0,
                }
            ],
            "tags": [],
            "is_new_arrival": False,
            "is_on_sale": False,
            "sale_price_gbp": None,
        }
    )
    assert product.total_stock == 5
    assert product.first_in_stock_variant() is not None
    assert product.first_in_stock_variant().sku == "DRUVO-3"


def test_map_product_with_multiple_colours_and_sizes():
    product = map_product(
        {
            "id": "8",
            "slug": "coat-001",
            "name": "Wool Coat",
            "description": "Warm coat",
            "category_slug": "outerwear",
            "category_name": "Outerwear",
            "brand": "DRUVO",
            "condition": "Pre-loved",
            "images": ["/img/coat.jpg"],
            "variants": [
                {"variant_id": 1, "sku": "COAT-NAV-M", "size": "M", "colour": "Navy", "stock_quantity": 2, "price_gbp": 60.0},
                {"variant_id": 2, "sku": "COAT-NAV-L", "size": "L", "colour": "Navy", "stock_quantity": 0, "price_gbp": 60.0},
                {"variant_id": 3, "sku": "COAT-BLK-M", "size": "M", "colour": "Black", "stock_quantity": 1, "price_gbp": 62.0},
            ],
            "available_sizes": ["M"],
            "available_colours": ["Black", "Navy"],
            "tags": [],
            "is_new_arrival": False,
            "is_on_sale": False,
            "sale_price_gbp": None,
        }
    )
    assert product.colours_for_size("M") == ["Black", "Navy"]
    assert product.sizes_for_colour("Navy") == ["M"]
    assert product.variant_for("L", "Navy").stock_quantity == 0
    assert product.variant_for("M", "Black").sku == "COAT-BLK-M"


class _FakeClient:
    def __init__(self) -> None:
        self.last_stock_payload: list[dict] = []

    async def check_stock(self, lines: list[dict]) -> dict:
        self.last_stock_payload = lines
        return {
            "ok": all(line["sku"] != "COAT-NAV-L" for line in lines),
            "lines": [
                {
                    "sku": line["sku"],
                    "requested": line["quantity"],
                    "available_quantity": 0 if line["sku"] == "COAT-NAV-L" else line["quantity"],
                    "sufficient": line["sku"] != "COAT-NAV-L",
                }
                for line in lines
            ],
        }

    async def submit_order(self, payload: dict) -> dict:
        return {"order_id": 99, "status": "confirmed", "duplicate": False}


def test_validate_stock_passes_variant_id():
    client = _FakeClient()
    service = WebsiteOrderService(client=client)

    async def _run():
        result = await service.validate_stock(
            [CheckoutLine(sku="COAT-BLK-M", quantity=1, unit_price_gbp=62.0, variant_id=3)]
        )
        assert result["ok"] is True
        assert client.last_stock_payload == [
            {"sku": "COAT-BLK-M", "quantity": 1, "variant_id": 3}
        ]

    import asyncio

    asyncio.run(_run())


def test_out_of_stock_variant_fails_validation():
    client = _FakeClient()
    service = WebsiteOrderService(client=client)

    async def _run():
        result = await service.validate_stock(
            [CheckoutLine(sku="COAT-NAV-L", quantity=1, unit_price_gbp=60.0, variant_id=2)]
        )
        assert result["ok"] is False

    import asyncio

    asyncio.run(_run())


def test_product_helpers_select_first_in_stock_variant():
    product = map_product(
        {
            "id": "9",
            "slug": "tee-001",
            "name": "Tee",
            "description": "",
            "category_slug": "tops",
            "category_name": "Tops",
            "brand": "",
            "condition": "Pre-loved",
            "images": [],
            "variants": [
                {"variant_id": 10, "sku": "TEE-RED-S", "size": "S", "colour": "Red", "stock_quantity": 0, "price_gbp": 12.0},
                {"variant_id": 11, "sku": "TEE-BLU-M", "size": "M", "colour": "Blue", "stock_quantity": 4, "price_gbp": 12.0},
            ],
            "tags": [],
            "is_new_arrival": False,
            "is_on_sale": False,
            "sale_price_gbp": None,
        }
    )
    first = product.first_in_stock_variant()
    assert first is not None
    assert asdict(first)["sku"] == "TEE-BLU-M"

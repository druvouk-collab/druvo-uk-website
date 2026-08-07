"""Checkout order submission API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.order_service import CheckoutLine, CheckoutRequest, WebsiteOrderService
from app.services.shipping_service import calculate_shipping

router = APIRouter(prefix="/api/checkout", tags=["checkout"])
orders = WebsiteOrderService()


@router.get("/shipping-config")
async def shipping_config() -> dict:
    settings = get_settings()
    return {
        "standard_gbp": settings.shipping_standard_gbp,
        "free_threshold_gbp": settings.shipping_free_threshold_gbp,
    }


@router.get("/shipping-quote")
async def shipping_quote(subtotal: float = 0) -> dict:
    return calculate_shipping(subtotal).as_dict()


class CheckoutLinePayload(BaseModel):
    sku: str
    quantity: int = Field(gt=0)
    unit_price_gbp: float = Field(ge=0)
    variant_id: int | None = None


class CheckoutOrderPayload(BaseModel):
    customer_email: str
    customer_name: str = ""
    external_order_id: str = ""
    lines: list[CheckoutLinePayload]


@router.post("/validate")
async def validate_checkout_stock(payload: CheckoutOrderPayload) -> dict:
    if not orders.orders_enabled:
        raise HTTPException(status_code=503, detail="DRUVO API not configured.")
    try:
        return await orders.validate_stock(
            [
                CheckoutLine(
                    sku=line.sku,
                    quantity=line.quantity,
                    unit_price_gbp=line.unit_price_gbp,
                    variant_id=line.variant_id,
                )
                for line in payload.lines
            ]
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/orders")
async def submit_checkout_order(payload: CheckoutOrderPayload) -> dict:
    if get_settings().payments_enabled:
        raise HTTPException(
            status_code=403,
            detail="Direct order submission is disabled. Complete payment via Stripe checkout.",
        )
    if not orders.orders_enabled:
        raise HTTPException(
            status_code=503,
            detail="Checkout is not connected to DRUVO AI. Set CATALOG_SOURCE=druvo_api and API credentials.",
        )
    try:
        result = await orders.submit(
            CheckoutRequest(
                customer_email=payload.customer_email,
                customer_name=payload.customer_name,
                lines=[
                    CheckoutLine(
                        sku=line.sku,
                        quantity=line.quantity,
                        unit_price_gbp=line.unit_price_gbp,
                        variant_id=line.variant_id,
                    )
                    for line in payload.lines
                ],
            ),
            external_order_id=payload.external_order_id.strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result

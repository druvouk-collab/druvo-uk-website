"""Checkout order submission API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.order_service import CheckoutLine, CheckoutRequest, WebsiteOrderService

router = APIRouter(prefix="/api/checkout", tags=["checkout"])
orders = WebsiteOrderService()


class CheckoutLinePayload(BaseModel):
    sku: str
    quantity: int = Field(gt=0)
    unit_price_gbp: float = Field(ge=0)


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
                CheckoutLine(sku=line.sku, quantity=line.quantity, unit_price_gbp=line.unit_price_gbp)
                for line in payload.lines
            ]
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/orders")
async def submit_checkout_order(payload: CheckoutOrderPayload) -> dict:
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

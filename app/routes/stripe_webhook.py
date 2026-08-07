"""Stripe webhook and payment session endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.order_service import CheckoutLine, CheckoutRequest, WebsiteOrderService
from app.services.stripe_service import StripeCheckoutService

router = APIRouter(tags=["stripe"])
stripe_checkout = StripeCheckoutService()
orders = WebsiteOrderService()


class CheckoutLinePayload(BaseModel):
    sku: str
    quantity: int = Field(gt=0)
    unit_price_gbp: float = Field(ge=0)
    variant_id: int | None = None


class PaymentSessionPayload(BaseModel):
    customer_email: str
    customer_name: str = ""
    external_order_id: str = ""
    lines: list[CheckoutLinePayload]


@router.post("/api/checkout/payment-session")
async def create_payment_session(payload: PaymentSessionPayload) -> dict:
    if not stripe_checkout.enabled:
        raise HTTPException(
            status_code=503,
            detail="Stripe test-mode payments are not configured.",
        )
    try:
        return await stripe_checkout.create_checkout_session(
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
            external_order_id=payload.external_order_id.strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    if not stripe_checkout._settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Stripe webhook secret is not configured.")
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        result = await stripe_checkout.handle_webhook(payload, signature)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result

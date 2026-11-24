"""Stripe webhook and payment session endpoints."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.config import get_settings
from app.lib.druvo_api.errors import CatalogApiError
from app.services.db_checkout import BasketLine, CheckoutError, DbCheckoutService, OutOfStockError
from app.services.order_service import CheckoutLine, WebsiteOrderService
from app.services.stripe_service import StripeCheckoutService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["stripe"])
stripe_checkout = StripeCheckoutService()
db_checkout = DbCheckoutService()
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
    phone: str = ""
    lines: list[CheckoutLinePayload]


@router.post("/api/checkout/payment-session")
async def create_payment_session(payload: PaymentSessionPayload) -> dict:
    if get_settings().db_payments_enabled:
        try:
            return await run_in_threadpool(
                db_checkout.create_checkout,
                customer_email=payload.customer_email,
                customer_name=payload.customer_name,
                phone=payload.phone,
                idempotency_key=payload.external_order_id,
                lines=[BasketLine(sku=line.sku, quantity=line.quantity) for line in payload.lines],
            )
        except OutOfStockError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CheckoutError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
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


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    if get_settings().database_enabled:
        payload = await request.body()
        signature = request.headers.get("stripe-signature", "")
        try:
            event = db_checkout.verify_event(payload, signature)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        try:
            return await run_in_threadpool(db_checkout.handle_event, event)
        except LookupError as exc:
            logger.warning("Stripe webhook for unknown order: %s", exc)
            raise HTTPException(status_code=404, detail="Order not found.") from exc
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
    except CatalogApiError as exc:
        logger.warning("Stripe webhook catalog error: %s", exc.cause or type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="DRUVO master order system is unavailable.",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("Stripe webhook upstream HTTP error: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail="DRUVO master order system is unavailable.",
        ) from exc
    return result
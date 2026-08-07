"""Customer account and order history routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.services.account_order_service import AccountOrderService
from app.templating import templates
from app.types.commerce import Order

router = APIRouter(prefix="/account")
account_orders = AccountOrderService()


async def _orders_for_view(email: str = "") -> tuple[list[Order], bool, str, bool]:
    lookup_email = email.strip()
    if account_orders.live_orders_enabled and lookup_email:
        live = await account_orders.list_orders_for_email(lookup_email)
        return live, True, lookup_email, True
    return [], account_orders.live_orders_enabled, lookup_email, bool(lookup_email)


@router.get("", response_class=HTMLResponse)
async def account_dashboard(request: Request, email: str = Query("")):
    orders, live_mode, lookup_email, has_email = await _orders_for_view(email)
    return templates.TemplateResponse(
        request,
        "pages/account/dashboard.html",
        {
            "page_title": "My Account",
            "orders": orders[:3],
            "live_orders": live_mode,
            "lookup_email": lookup_email,
            "has_email": has_email,
        },
    )


@router.get("/login", response_class=HTMLResponse)
async def account_login(request: Request, email: str = Query("")):
    return templates.TemplateResponse(
        request,
        "pages/account/login.html",
        {"page_title": "Find your orders", "lookup_email": email.strip()},
    )


@router.get("/orders", response_class=HTMLResponse)
async def order_history(request: Request, email: str = Query("")):
    orders, live_mode, lookup_email, has_email = await _orders_for_view(email)
    return templates.TemplateResponse(
        request,
        "pages/account/orders.html",
        {
            "page_title": "Order History",
            "orders": orders,
            "live_orders": live_mode,
            "lookup_email": lookup_email,
            "has_email": has_email,
        },
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def order_detail(request: Request, order_id: str, email: str = Query("")):
    lookup_email = email.strip()
    order = None
    if account_orders.live_orders_enabled and lookup_email:
        order = await account_orders.get_order(order_id, lookup_email)
    if not order:
        return templates.TemplateResponse(request, "pages/404.html", {"page_title": "Not found"}, status_code=404)
    return templates.TemplateResponse(
        request,
        "pages/account/order_detail.html",
        {"page_title": f"Order {order_id}", "order": order, "lookup_email": lookup_email},
    )

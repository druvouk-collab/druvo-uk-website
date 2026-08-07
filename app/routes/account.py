"""Customer account scaffolding routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.services.account_order_service import AccountOrderService
from app.templating import templates
from app.types.commerce import Order, OrderLine

router = APIRouter(prefix="/account")
account_orders = AccountOrderService()

_MOCK_ORDERS = [
    Order(
        id="DRU-10042",
        placed_at="2026-08-01",
        status="Shipped",
        tracking_number="RM123456789GB",
        carrier="Royal Mail",
        lines=[
            OrderLine("cashmere-roll-neck", "Cashmere Roll Neck", "CN-GRY-M", "M", "Grey", 1, 44.00),
        ],
        subtotal_gbp=44.00,
        shipping_gbp=3.99,
        total_gbp=47.99,
    ),
    Order(
        id="DRU-10038",
        placed_at="2026-07-18",
        status="Delivered",
        tracking_number="RM987654321GB",
        carrier="Royal Mail",
        lines=[
            OrderLine("white-leather-trainers", "White Leather Trainers", "CP-WHT-42", "UK 9", "White", 1, 165.00),
        ],
        subtotal_gbp=165.00,
        shipping_gbp=0.00,
        total_gbp=165.00,
    ),
]


async def _orders_for_view(email: str = "") -> tuple[list[Order], bool, str]:
    if account_orders.live_orders_enabled and email.strip():
        live = await account_orders.list_orders_for_email(email)
        return live, True, email.strip()
    return _MOCK_ORDERS, False, email.strip()


@router.get("", response_class=HTMLResponse)
async def account_dashboard(request: Request, email: str = Query("")):
    orders, live_mode, lookup_email = await _orders_for_view(email)
    return templates.TemplateResponse(
        request,
        "pages/account/dashboard.html",
        {
            "page_title": "My Account",
            "orders": orders[:3],
            "live_orders": live_mode,
            "lookup_email": lookup_email,
        },
    )


@router.get("/login", response_class=HTMLResponse)
async def account_login(request: Request):
    return templates.TemplateResponse(
        request,
        "pages/account/login.html",
        {"page_title": "Sign In"},
    )


@router.get("/orders", response_class=HTMLResponse)
async def order_history(request: Request, email: str = Query("")):
    orders, live_mode, lookup_email = await _orders_for_view(email)
    return templates.TemplateResponse(
        request,
        "pages/account/orders.html",
        {
            "page_title": "Order History",
            "orders": orders,
            "live_orders": live_mode,
            "lookup_email": lookup_email,
        },
    )


@router.get("/orders/{order_id}", response_class=HTMLResponse)
async def order_detail(request: Request, order_id: str, email: str = Query("")):
    if account_orders.live_orders_enabled and email.strip():
        order = await account_orders.get_order(order_id, email)
    else:
        order = next((o for o in _MOCK_ORDERS if o.id == order_id), None)
    if not order:
        return templates.TemplateResponse(request, "pages/404.html", {"page_title": "Not found"}, status_code=404)
    return templates.TemplateResponse(
        request,
        "pages/account/order_detail.html",
        {"page_title": f"Order {order_id}", "order": order, "lookup_email": email.strip()},
    )

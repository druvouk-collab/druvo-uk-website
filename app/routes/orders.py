"""Customer order pages: find an order, track it, start a return (cloud database checkout)."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.services import order_tracking
from app.templating import templates

router = APIRouter(prefix="/orders")

_LOOKUPS: dict[str, deque] = defaultdict(deque)
_LOOKUP_LIMIT = 10          # attempts per IP
_LOOKUP_WINDOW = 3600.0     # per hour


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    hits = _LOOKUPS[ip]
    while hits and now - hits[0] > _LOOKUP_WINDOW:
        hits.popleft()
    if len(hits) >= _LOOKUP_LIMIT:
        return True
    hits.append(now)
    return False


def _render(request: Request, name: str, ctx: dict, status: int = 200) -> HTMLResponse:
    response = templates.TemplateResponse(request, f"pages/orders/{name}.html", ctx, status_code=status)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("/find", response_class=HTMLResponse)
async def find_form(request: Request):
    return _render(request, "find", {"page_title": "Track your order", "enabled": get_settings().database_enabled})


@router.post("/find", response_class=HTMLResponse)
async def find_submit(request: Request, order_number: str = Form(""), email: str = Form("")):
    ctx = {"page_title": "Track your order", "enabled": get_settings().database_enabled,
           "order_number": order_number, "email": email}
    if not ctx["enabled"]:
        return _render(request, "find", ctx)
    if _rate_limited(_client_ip(request)):
        ctx["error"] = "Too many attempts. Please try again in an hour, or email us."
        return _render(request, "find", ctx, status=429)
    url = await run_in_threadpool(order_tracking.find_order, order_number, email)
    if not url:
        ctx["error"] = "We couldn't find an order with that number and email. Check both and try again."
        return _render(request, "find", ctx, status=404)
    path = url.split("://", 1)[-1]
    return RedirectResponse(path[path.index("/"):], status_code=303)


@router.get("/{order_number}", response_class=HTMLResponse)
async def order_page(request: Request, order_number: str, t: str = "", returned: str = ""):
    if not get_settings().database_enabled:
        return _render(request, "find", {"page_title": "Track your order", "enabled": False}, status=404)
    view = await run_in_threadpool(order_tracking.order_view, order_number, t)
    if view is None:
        return _render(request, "find", {"page_title": "Track your order", "enabled": True,
                                         "error": "This order link isn't valid. Enter your order number and email."},
                       status=404)
    return _render(request, "detail", {"page_title": f"Order {order_number}", "order": view, "token": t,
                                       "just_returned": returned == "1"})


@router.post("/{order_number}/return", response_class=HTMLResponse)
async def start_return(request: Request, order_number: str, t: str = Form(""), reason: str = Form("")):
    try:
        await run_in_threadpool(order_tracking.request_return, order_number, t, reason)
    except order_tracking.TrackingError as exc:
        view = await run_in_threadpool(order_tracking.order_view, order_number, t)
        if view is None:
            return _render(request, "find", {"page_title": "Track your order", "enabled": True, "error": str(exc)},
                           status=404)
        return _render(request, "detail", {"page_title": f"Order {order_number}", "order": view, "token": t,
                                           "error": str(exc)}, status=400)
    return RedirectResponse(f"/orders/{order_number}?t={t}&returned=1", status_code=303)

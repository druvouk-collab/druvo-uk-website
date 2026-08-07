"""Admin-only production launch checklist."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import get_settings
from app.services.readiness_service import build_readiness_report
from app.templating import templates

router = APIRouter(prefix="/admin", tags=["admin"])

MANUAL_CHECKLIST = [
    "Stripe remains in TEST mode until launch sign-off (sk_test_ / pk_test_ keys).",
    "Stripe webhook endpoint registered at /webhooks/stripe on the public site URL.",
    "DRUVO AI Website API running with stable tunnel or permanent host.",
    "Cloudflare Quick Tunnel replaced with named tunnel or hosted API before launch.",
    "SMTP credentials configured and test email delivered successfully.",
    "Legal pages reviewed: privacy, terms, delivery, returns.",
    "All live products have images, stock, prices, and consistent variants in DRUVO AI.",
    "Test checkout end-to-end: payment → webhook → DRUVO order → stock deduction → account history.",
    "Customer order-history lookup tested with real checkout email.",
    "SESSION_SECRET and ADMIN_CHECKLIST_TOKEN set to strong random values on Render.",
]


def _authorize(token: str) -> None:
    expected = get_settings().admin_checklist_token.strip()
    if not expected or token.strip() != expected:
        raise HTTPException(status_code=403, detail="Admin checklist access denied.")


@router.get("/launch-checklist", response_class=HTMLResponse)
async def launch_checklist_page(request: Request, token: str = Query("")):
    _authorize(token)
    report = await build_readiness_report()
    return templates.TemplateResponse(
        request,
        "pages/admin/launch_checklist.html",
        {
            "page_title": "Production launch checklist",
            "report": report,
            "manual_items": MANUAL_CHECKLIST,
        },
    )


@router.get("/readiness")
async def launch_readiness_json(token: str = Query("")) -> JSONResponse:
    _authorize(token)
    report = await build_readiness_report()
    return JSONResponse(report)

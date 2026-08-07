"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import CANONICAL_HOST, get_settings
from app.lib.druvo_api.client import DruvoApiClient
from app.routes import account, admin, catalog_api, chat_api, checkout_api, legal, seo, shop, stripe_webhook
from app.services.readiness_service import build_readiness_report
from app.templating import templates

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent / "static"


def _json_error_path(path: str) -> bool:
    return path.startswith("/api/") or path.startswith("/webhooks/")

app = FastAPI(
    title="DRUVO UK",
    description="Public e-commerce storefront for DRUVO UK resale",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(shop.router)
app.include_router(catalog_api.router)
app.include_router(checkout_api.router)
app.include_router(stripe_webhook.router)
app.include_router(account.router)
app.include_router(admin.router)
app.include_router(legal.router)
app.include_router(seo.router)
app.include_router(chat_api.router)


@app.middleware("http")
async def www_to_canonical_redirect(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":")[0].lower()
    if host == f"www.{CANONICAL_HOST}":
        target = f"https://{CANONICAL_HOST}{request.url.path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(url=target, status_code=301)
    return await call_next(request)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "druvo-uk-website"})


@app.get("/health/readiness")
async def readiness() -> JSONResponse:
    report = await build_readiness_report()
    status_code = 200 if report["ready"] else 503
    return JSONResponse(report, status_code=status_code)


@app.get("/health/druvo")
async def druvo_health() -> JSONResponse:
    settings = get_settings()
    raw_key = os.getenv("DRUVO_API_KEY", "")
    payload = {
        "catalog_source": settings.catalog_source,
        "api_configured": bool(settings.druvo_api_base_url and settings.druvo_api_key),
        "api_base_url_set": bool(settings.druvo_api_base_url),
        "api_key_set": bool(settings.druvo_api_key),
        "api_key_raw_length": len(raw_key),
        "api_key_length": len(settings.druvo_api_key),
        "api_key_length_ok": len(settings.druvo_api_key) == 43,
        "stripe_enabled": settings.stripe_enabled,
        "stripe_mode": settings.stripe_mode,
        "payments_enabled": settings.payments_enabled,
        "email_configured": settings.email_configured,
        "git_commit": os.getenv("RENDER_GIT_COMMIT", ""),
    }
    if settings.catalog_source == "druvo_api" and settings.druvo_api_base_url:
        client = DruvoApiClient.from_settings(settings)
        payload["api_reachable"] = await client.ping()
        if settings.druvo_api_key:
            try:
                products = await client.list_products()
                payload["catalog_ok"] = True
                payload["product_count"] = len(products)
            except Exception as exc:
                payload["catalog_ok"] = False
                payload["catalog_error"] = type(exc).__name__
    return JSONResponse(payload)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> HTMLResponse | JSONResponse:
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request,
            "pages/404.html",
            {"page_title": "Page not found"},
            status_code=404,
        )
    if _json_error_path(request.url.path):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return templates.TemplateResponse(
        request,
        "pages/error.html",
        {"page_title": "Request error", "message": str(exc.detail)},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    logger.exception("Unhandled error on %s: %s", request.url.path, type(exc).__name__)
    if _json_error_path(request.url.path):
        return JSONResponse({"detail": "Service temporarily unavailable."}, status_code=503)
    return templates.TemplateResponse(
        request,
        "pages/error.html",
        {
            "page_title": "Temporarily unavailable",
            "message": "Something went wrong loading this page. Please try again in a moment.",
        },
        status_code=503,
    )

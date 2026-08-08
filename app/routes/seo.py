"""SEO routes — robots.txt, sitemap.xml, and Google Merchant feed."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from app.services.merchant_service import build_merchant_feed_xml
from app.services.seo_service import build_sitemap_urls, robots_txt, sitemap_xml

router = APIRouter(tags=["seo"])


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> PlainTextResponse:
    return PlainTextResponse(robots_txt(), media_type="text/plain; charset=utf-8")


@router.get("/sitemap.xml")
async def sitemap() -> Response:
    urls = await build_sitemap_urls()
    body = sitemap_xml(urls)
    return Response(content=body, media_type="application/xml; charset=utf-8")


@router.get("/google-merchant-feed.xml")
async def google_merchant_feed() -> Response:
    """Public Google Merchant product feed synced from DRUVO AI inventory."""
    body = await build_merchant_feed_xml()
    return Response(content=body, media_type="application/xml; charset=utf-8")

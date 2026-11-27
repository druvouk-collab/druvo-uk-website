"""SEO routes — robots.txt, sitemap.xml, and Google Merchant feed."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response

from app.services.merchant_service import build_merchant_feed_xml, build_social_catalog_csv
from app.services.seo_service import build_sitemap_urls, is_non_public_host, robots_txt, sitemap_xml

router = APIRouter(tags=["seo"])


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots(request: Request) -> PlainTextResponse:
    if is_non_public_host(request.headers.get("host", "")):
        # Staging and the old *.onrender.com address must never be crawled (duplicate of druvo.uk).
        return PlainTextResponse("User-agent: *\nDisallow: /\n", media_type="text/plain; charset=utf-8")
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


@router.get("/feeds/social-catalog.csv")
async def social_catalog() -> Response:
    """Product catalogue for Meta (Facebook/Instagram), TikTok and Snapchat catalogue managers."""
    body = await build_social_catalog_csv()
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=3600"})

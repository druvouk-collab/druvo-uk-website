"""SEO routes — robots.txt and sitemap.xml."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

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

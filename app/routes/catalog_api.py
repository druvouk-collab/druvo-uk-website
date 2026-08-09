"""Catalog image proxy — fetches DRUVO AI images server-side with API key."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.config import get_settings
from app.lib.druvo_api.key_sanitize import bearer_auth_header

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/catalog", tags=["catalog"])

_image_client: httpx.AsyncClient | None = None


def _image_timeout_seconds() -> float:
    settings = get_settings()
    return float(getattr(settings, "druvo_api_image_timeout_seconds", 60) or 60)


def _get_image_client() -> httpx.AsyncClient:
    global _image_client
    if _image_client is None or _image_client.is_closed:
        _image_client = httpx.AsyncClient(
            timeout=httpx.Timeout(_image_timeout_seconds(), connect=10.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=True,
        )
    return _image_client


@router.get("/images/{image_path:path}")
async def proxy_catalog_image(image_path: str) -> Response:
    settings = get_settings()
    if settings.catalog_source != "druvo_api" or not settings.druvo_api_base_url or not settings.druvo_api_key:
        raise HTTPException(status_code=404, detail="Catalog image proxy is not configured.")

    rel = image_path.lstrip("/")
    if ".." in rel.split("/"):
        raise HTTPException(status_code=400, detail="Invalid image path.")

    base = settings.druvo_api_base_url.rstrip("/")
    url = f"{base}/api/v1/images/{rel}"
    headers = bearer_auth_header(settings.druvo_api_key)

    client = _get_image_client()
    try:
        upstream = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        logger.warning("Image proxy timeout for %s", rel)
        raise HTTPException(status_code=504, detail="DRUVO AI image fetch timed out.") from exc
    except httpx.HTTPError as exc:
        logger.warning("Image proxy error for %s: %s", rel, exc)
        raise HTTPException(status_code=502, detail="Could not reach DRUVO AI image service.") from exc

    if upstream.status_code == 404:
        raise HTTPException(status_code=404, detail="Image not found.")
    if upstream.status_code >= 400:
        raise HTTPException(status_code=502, detail="DRUVO AI image fetch failed.")

    media_type = upstream.headers.get("content-type", "application/octet-stream")
    response_headers = {
        "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
    }
    content_length = upstream.headers.get("content-length")
    if content_length:
        response_headers["Content-Length"] = content_length

    return Response(
        content=upstream.content,
        media_type=media_type,
        headers=response_headers,
    )

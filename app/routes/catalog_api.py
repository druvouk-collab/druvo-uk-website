"""Catalog image proxy — fetches DRUVO AI images server-side with API key."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.config import get_settings
from app.lib.druvo_api.key_sanitize import bearer_auth_header

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


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

    try:
        async with httpx.AsyncClient(timeout=float(settings.druvo_api_timeout_seconds)) as client:
            upstream = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach DRUVO AI image service.") from exc

    if upstream.status_code == 404:
        raise HTTPException(status_code=404, detail="Image not found.")
    if upstream.status_code >= 400:
        raise HTTPException(status_code=502, detail="DRUVO AI image fetch failed.")

    media_type = upstream.headers.get("content-type", "application/octet-stream")
    return Response(content=upstream.content, media_type=media_type)

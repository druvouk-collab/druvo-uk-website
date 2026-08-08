"""Rewrite DRUVO AI image URLs for browser-safe website proxy routes."""

from __future__ import annotations

from urllib.parse import urlparse


def extract_image_relative_path(url: str) -> str | None:
    """Extract Images-relative path from a DRUVO Website API image URL."""
    if not url:
        return None
    marker = "/api/v1/images/"
    if marker in url:
        return url.split(marker, 1)[1].lstrip("/")
    parsed = urlparse(url)
    if parsed.path.startswith("/api/v1/images/"):
        return parsed.path[len("/api/v1/images/") :]
    return None


def to_website_proxy_path(relative_path: str) -> str:
    """Build a same-origin catalog proxy path from an Images-relative path."""
    rel = relative_path.strip().lstrip("/").replace("\\", "/")
    if not rel or ".." in rel.split("/"):
        return ""
    return f"/api/catalog/images/{rel}"


def to_website_proxy_url(url: str) -> str:
    """Map DRUVO API image URLs to same-origin website proxy paths."""
    if not url:
        return url
    if url.startswith("/api/catalog/images/"):
        return url
    if url.startswith(("http://", "https://")):
        rel = extract_image_relative_path(url)
        if rel:
            return to_website_proxy_path(rel)
        return url
    return to_website_proxy_path(url)

"""Automated SEO audit for all sitemap-eligible URLs."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse
from xml.etree import ElementTree

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

CANONICAL_BASE = "https://druvo.uk"


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.in_title = False
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.h1: list[str] = []
        self.in_h1 = False
        self.ld_json: list[dict] = []
        self._ld_buffer = ""
        self._in_ld_json = False
        self.links: list[str] = []
        self.img_alts: list[str] = []
        self.onrender_refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = attr.get("name") or attr.get("property") or ""
            content = attr.get("content", "")
            if name:
                self.meta[name] = content
        elif tag == "link" and attr.get("rel") == "canonical":
            self.canonical = attr.get("href", "")
        elif tag == "h1":
            self.in_h1 = True
        elif tag == "script" and attr.get("type") == "application/ld+json":
            self._in_ld_json = True
            self._ld_buffer = ""
        elif tag == "a" and attr.get("href"):
            self.links.append(attr["href"])
        elif tag == "img":
            self.img_alts.append(attr.get("alt", ""))

        for _, value in attrs:
            if value and "onrender.com" in value:
                self.onrender_refs.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        elif tag == "h1":
            self.in_h1 = False
        elif tag == "script" and self._in_ld_json:
            self._in_ld_json = False
            try:
                self.ld_json.append(json.loads(self._ld_buffer.strip()))
            except json.JSONDecodeError:
                pass

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title += data
        if self.in_h1:
            self.h1.append(data.strip())
        if self._in_ld_json:
            self._ld_buffer += data
        if "onrender.com" in data:
            self.onrender_refs.append(data.strip())


def _parse_page(html: str) -> _PageParser:
    parser = _PageParser()
    parser.feed(html)
    return parser


def _schema_types(ld_blocks: list[dict]) -> set[str]:
    types: set[str] = set()
    for block in ld_blocks:
        t = block.get("@type")
        if isinstance(t, str):
            types.add(t)
        elif isinstance(t, list):
            types.update(t)
    return types


def _extract_sitemap_paths(xml_text: str) -> list[str]:
    root = ElementTree.fromstring(xml_text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    paths: list[str] = []
    for loc in root.findall("sm:url/sm:loc", ns):
        if loc.text:
            paths.append(urlparse(loc.text).path or "/")
    return paths


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_all_sitemap_urls_pass_seo_audit(client):
    sitemap = await client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    paths = _extract_sitemap_paths(sitemap.text)
    assert paths

    titles: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    failures: list[str] = []

    for path in paths:
        response = await client.get(path)
        if response.status_code != 200:
            failures.append(f"{path}: HTTP {response.status_code}")
            continue

        html = response.text
        page = _parse_page(html)
        label = path or "/"

        if page.canonical != f"{CANONICAL_BASE}{path}":
            failures.append(f"{label}: canonical={page.canonical!r}")

        robots = page.meta.get("robots", "")
        if robots != "index, follow":
            failures.append(f"{label}: robots={robots!r}")

        title = page.title.strip()
        if not title:
            failures.append(f"{label}: missing title")
        elif title in titles.values():
            failures.append(f"{label}: duplicate title {title!r}")
        titles[label] = title

        desc = page.meta.get("description", "").strip()
        if not desc or desc.startswith("DRUVO UK — premium pre-loved"):
            failures.append(f"{label}: generic or missing meta description")
        elif desc in descriptions.values():
            failures.append(f"{label}: duplicate meta description")
        descriptions[label] = desc

        if not page.h1 or not any(page.h1):
            failures.append(f"{label}: missing H1")

        if page.onrender_refs or "onrender.com" in html:
            failures.append(f"{label}: contains onrender.com reference")

        if path.startswith("/product/"):
            types = _schema_types(page.ld_json)
            if "Product" not in types:
                failures.append(f"{label}: missing Product schema")
            if "BreadcrumbList" not in types:
                failures.append(f"{label}: missing BreadcrumbList schema")

        for link in page.links:
            if link.startswith("http") and "onrender.com" in link:
                failures.append(f"{label}: broken/onrender link {link}")

        for alt in page.img_alts:
            if alt == "":
                failures.append(f"{label}: image missing alt text")
                break

    assert not failures, "SEO audit failures:\n" + "\n".join(failures)


@pytest.mark.asyncio
async def test_sitemap_includes_all_mock_products(client):
    sitemap = await client.get("/sitemap.xml")
    paths = _extract_sitemap_paths(sitemap.text)
    product_paths = [p for p in paths if p.startswith("/product/")]
    assert len(product_paths) >= 5


@pytest.mark.asyncio
async def test_static_responses_have_cache_control(client):
    response = await client.get("/static/css/druvo.css")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "public, max-age=604800, immutable"

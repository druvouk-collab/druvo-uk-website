"""Check the public DRUVO website the way a customer and Google see it.

Usage: python scripts/site_check.py [https://druvo.uk]

- Retries each URL so a Render free-plan cold start (up to ~60 s) is not reported as an outage.
- Checks every page in sitemap.xml plus robots.txt, the Merchant feed, and product structured data.
- Exits 1 if anything is still failing after retries, so GitHub emails the owner.
Standard library only, so it runs on any GitHub runner without installing packages.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://druvo.uk").rstrip("/")
UA = "DRUVO-site-check/1.0 (+https://druvo.uk)"
ATTEMPTS = 4
WAIT_SECONDS = 20


def fetch(url: str) -> tuple[int, str, float]:
    last = (0, "", 0.0)
    for attempt in range(1, ATTEMPTS + 1):
        start = time.monotonic()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = resp.read().decode("utf-8", "replace")
                return resp.status, body, time.monotonic() - start
        except urllib.error.HTTPError as exc:
            last = (exc.code, "", time.monotonic() - start)
        except Exception as exc:  # network error, timeout
            last = (0, str(exc), time.monotonic() - start)
        if attempt < ATTEMPTS:
            print(f"  retry {attempt}/{ATTEMPTS - 1} for {url} (got {last[0] or last[1]})")
            time.sleep(WAIT_SECONDS)
    return last


def main() -> int:
    problems: list[str] = []

    def check(path: str) -> str:
        url = path if path.startswith("http") else BASE + path
        status, body, secs = fetch(url)
        flag = "OK " if status == 200 else "BAD"
        print(f"{flag} {status} {secs:5.1f}s {url}")
        if status != 200:
            problems.append(f"{status} {url}")
        return body

    print(f"Checking {BASE} at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    check("/health")
    robots = check("/robots.txt")
    if robots and not re.search(r"^Sitemap: https?://\S+/sitemap\.xml", robots, re.M):
        problems.append("robots.txt does not point to the sitemap")
    if re.search(r"^Disallow:\s*/\s*$", robots, re.M):
        problems.append("robots.txt blocks the whole site")

    sitemap = check("/sitemap.xml")
    # Fetch each sitemap path from BASE, so the same script can check a staging copy.
    urls = [BASE + urlparse(u).path for u in re.findall(r"<loc>([^<]+)</loc>", sitemap)]
    print(f"sitemap.xml lists {len(urls)} URLs")
    if not urls:
        problems.append("sitemap.xml has no URLs")

    products = 0
    checked_images: set[str] = set()
    for url in urls:
        if "/static/" in url:
            continue
        body = check(url)
        if not body:
            continue
        if 'name="robots" content="noindex' in body:
            problems.append(f"noindex on {url}")
        if "/product/" in url:
            products += 1
            blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', body, re.S)
            types = []
            for block in blocks:
                try:
                    types.append(json.loads(block).get("@type"))
                except ValueError:
                    problems.append(f"invalid JSON-LD on {url}")
            if "Product" not in types:
                problems.append(f"no Product structured data on {url}")
        for src in sorted(set(re.findall(r'<img[^>]+src="(/[^"]+)"', body))):
            if src not in checked_images:
                checked_images.add(src)
                check(src)

    feed = check("/google-merchant-feed.xml")
    items = feed.count("<item>")
    print(f"Merchant feed has {items} item(s); product pages checked: {products}")

    print()
    if problems:
        print("PROBLEMS FOUND:")
        for p in problems:
            print(" -", p)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

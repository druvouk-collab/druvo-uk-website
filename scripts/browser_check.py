"""Open DRUVO pages in a real browser on mobile and desktop, save screenshots, and report problems.

Usage: python scripts/browser_check.py [https://druvo.uk] [output-dir]

Per page and device it records: HTTP status, load time, JavaScript errors, failed requests (images, CSS, JS),
broken images, sideways scrolling on mobile, title, meta description, canonical, Google verification tag,
and on product pages the delivery line and Product structured data. Also tries the basket flow:
add the first product to the basket and open the basket/checkout page.
Exits 1 when a real problem is found.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://druvo.uk").rstrip("/")
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "browser-check")
OUT.mkdir(parents=True, exist_ok=True)

PAGES = ["/", "/shop", "/categories", "/new-arrivals", "/sale", "/about", "/contact", "/faq",
         "/delivery", "/returns", "/terms", "/privacy",
         "/product/balance-cream-2-piece-sweatshirt-jogger-tracksuit-set-l", "/checkout"]
DEVICES = {
    "mobile": {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True,
               "has_touch": True,
               "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"},
    "desktop": {"viewport": {"width": 1440, "height": 900}},
}


def main() -> int:
    problems: list[str] = []
    report: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for device, opts in DEVICES.items():
            ctx = browser.new_context(**opts)
            page = ctx.new_page()
            errors: list[str] = []
            failed: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("requestfailed", lambda r: failed.append(r.url))
            page.on("response", lambda r: failed.append(f"{r.status} {r.url}") if r.status >= 400 else None)
            for path in PAGES:
                errors.clear(); failed.clear()
                start = time.monotonic()
                resp = page.goto(BASE + path, wait_until="networkidle", timeout=90000)
                secs = time.monotonic() - start
                page.wait_for_timeout(500)
                info = page.evaluate("""() => {
                  const m = n => (document.querySelector(`meta[name="${n}"]`)||{}).content || null;
                  const imgs = [...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.src)
                                 .map(i => i.src);
                  return {
                    title: document.title,
                    description: m('description'),
                    verification: m('google-site-verification'),
                    viewport: m('viewport'),
                    canonical: (document.querySelector('link[rel=canonical]')||{}).href || null,
                    h1: [...document.querySelectorAll('h1')].map(h => h.innerText.trim()),
                    overflowX: document.documentElement.scrollWidth - window.innerWidth,
                    brokenImages: imgs,
                    jsonld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent),
                    delivery: (document.querySelector('[data-delivery-price]')||{}).innerText || null,
                  };
                }""")
                name = path.strip("/").replace("/", "_") or "home"
                page.screenshot(path=str(OUT / f"{device}-{name}.png"), full_page=True)
                status = resp.status if resp else 0
                row = {"device": device, "path": path, "status": status, "seconds": round(secs, 2),
                       "title": info["title"], "description_len": len(info["description"] or ""),
                       "h1": info["h1"], "canonical": info["canonical"],
                       "verification_tag": bool(info["verification"]),
                       "overflow_px": info["overflowX"], "js_errors": list(errors),
                       "failed_requests": [f for f in failed if "google" not in f and "favicon" not in f],
                       "broken_images": info["brokenImages"]}
                if "/product/" in path:
                    types = []
                    for block in info["jsonld"]:
                        try:
                            types.append(json.loads(block).get("@type"))
                        except ValueError:
                            problems.append(f"{device} {path}: invalid JSON-LD")
                    row["jsonld_types"] = types
                    row["delivery_line"] = info["delivery"]
                    blob = " ".join(info["jsonld"])
                    row["shippingDetails"] = "shippingDetails" in blob
                    row["returnPolicy"] = "hasMerchantReturnPolicy" in blob
                    if "Product" not in types:
                        problems.append(f"{device} {path}: no Product structured data")
                report.append(row)
                print(f"{device:7} {status} {secs:5.1f}s overflow={info['overflowX']}px "
                      f"jsErr={len(errors)} failed={len(row['failed_requests'])} h1={len(info['h1'])} {path}")
                if status != 200:
                    problems.append(f"{device} {path}: HTTP {status}")
                if errors:
                    problems.append(f"{device} {path}: JS errors {errors[:2]}")
                if row["failed_requests"]:
                    problems.append(f"{device} {path}: failed requests {row['failed_requests'][:3]}")
                if info["brokenImages"]:
                    problems.append(f"{device} {path}: broken images {info['brokenImages'][:3]}")
                if device == "mobile" and info["overflowX"] > 2:
                    problems.append(f"mobile {path}: page scrolls sideways by {info['overflowX']}px")
                if len(info["h1"]) != 1 and path != "/checkout":
                    print(f"   note: {len(info['h1'])} <h1> headings on {path}")

            # Basket flow: product page -> add to basket -> basket/checkout shows the item.
            page.goto(BASE + PAGES[12], wait_until="networkidle")
            add = page.locator("button:has-text('Add to basket'), button:has-text('Add to bag'), "
                               "[data-add-to-cart], [data-add-to-basket]").first
            if add.count():
                add.click()
                page.wait_for_timeout(1000)
                page.goto(BASE + "/checkout", wait_until="networkidle")
                page.wait_for_timeout(800)
                page.screenshot(path=str(OUT / f"{device}-basket-flow.png"), full_page=True)
                has_item = "Tracksuit" in page.inner_text("body") or "tracksuit" in page.inner_text("body")
                print(f"{device:7} basket flow: item visible at checkout = {has_item}")
                if not has_item:
                    problems.append(f"{device}: item not visible at checkout after adding to basket")
            else:
                problems.append(f"{device}: no add-to-basket button found on product page")
            ctx.close()
        browser.close()

    (OUT / "report.json").write_text(json.dumps(report, indent=2))
    print()
    if problems:
        print("PROBLEMS FOUND:")
        for p in problems:
            print(" -", p)
        return 1
    print("ALL BROWSER CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

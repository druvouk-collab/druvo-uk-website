"""End-to-end checkout test with Stripe TEST mode — no real money moves.

Drives a real browser through: product page → add to basket → checkout form → Stripe Checkout →
pay with Stripe's test card 4242 4242 4242 4242 → Stripe webhook (forwarded by the Stripe CLI) →
order marked paid in PostgreSQL, stock reduced, confirmation email attempted.

Run by .github/workflows/stripe-e2e.yml against a throwaway PostgreSQL database.
Usage: python scripts/stripe_e2e.py <app-url> <database-url> [output-dir]
Refuses to run with a live Stripe key.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import sqlalchemy as sa
from playwright.sync_api import sync_playwright

APP = sys.argv[1].rstrip("/")
DB = sys.argv[2]
OUT = Path(sys.argv[3] if len(sys.argv) > 3 else "stripe-e2e")
OUT.mkdir(parents=True, exist_ok=True)

if not os.environ.get("STRIPE_SECRET_KEY", "").startswith("sk_test_"):
    sys.exit("Refusing to run: STRIPE_SECRET_KEY must be a TEST key (sk_test_...).")

engine = sa.create_engine(DB)


def one(sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql), params).first()


def main() -> int:
    variant = one("SELECT v.sku, v.stock_quantity, p.slug FROM variants v JOIN products p ON p.id = v.product_id "
                  "WHERE v.stock_quantity > 0 ORDER BY v.id LIMIT 1")
    if not variant:
        print("No product with stock in the test database"); return 1
    sku, stock_before, slug = variant
    print(f"Testing with {sku} ({slug}), stock before = {stock_before}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        # After paying, Stripe redirects to the public site URL; don't let the test touch druvo.uk.
        page.route("https://druvo.uk/**", lambda route: route.fulfill(status=200, body="redirected"))

        page.goto(f"{APP}/product/{slug}", wait_until="networkidle")
        page.click("[data-add-to-cart]")
        page.wait_for_timeout(800)
        page.goto(f"{APP}/checkout", wait_until="networkidle")
        page.fill("#email", "stripe-test@druvo.uk")
        page.fill("#first-name", "Test")
        page.fill("#last-name", "Customer")
        page.fill("#address", "1 Test Street")
        page.fill("#city", "Manchester")
        page.fill("#postcode", "M1 1AA")
        page.screenshot(path=str(OUT / "1-checkout-form.png"), full_page=True)
        page.click("#place-order")
        page.wait_for_url("https://checkout.stripe.com/**", timeout=60000)
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(OUT / "2-stripe-checkout.png"), full_page=True)

        # Stripe-hosted page: choose card if a payment-method list is shown, then enter the test card.
        card_tab = page.locator("[data-testid='card-accordion-item-button'], button:has-text('Card')")
        if card_tab.count() and card_tab.first.is_visible():
            card_tab.first.click()
        page.fill("#cardNumber", "4242 4242 4242 4242")
        page.fill("#cardExpiry", "12 / 34")
        page.fill("#cardCvc", "123")
        if page.locator("#billingName").count():
            page.fill("#billingName", "Test Customer")
        if page.locator("#billingPostalCode").count() and page.locator("#billingPostalCode").is_visible():
            page.fill("#billingPostalCode", "M1 1AA")
        page.screenshot(path=str(OUT / "3-card-entered.png"), full_page=True)
        page.click(".SubmitButton, button[type=submit]")
        page.wait_for_url(lambda url: "checkout.stripe.com" not in url, timeout=90000)
        print("Stripe accepted the test payment and redirected to:", page.url.split("?")[0])
        browser.close()

    # The webhook (forwarded by the Stripe CLI) marks the order paid.
    order = None
    for _ in range(30):
        order = one("SELECT order_number, status, total_pence, email FROM orders "
                    "WHERE email = 'stripe-test@druvo.uk' ORDER BY id DESC LIMIT 1")
        if order and order[1] == "paid":
            break
        time.sleep(2)
    stock_after = one("SELECT stock_quantity FROM variants WHERE sku = :sku", sku=sku)[0]

    problems = []
    if not order:
        problems.append("no order was created")
    elif order[1] != "paid":
        problems.append(f"order {order[0]} status is {order[1]!r}, expected 'paid' (webhook not processed?)")
    if stock_after != stock_before - 1:
        problems.append(f"stock went {stock_before} -> {stock_after}, expected -1")

    print(f"Order: {order}")
    print(f"Stock: {stock_before} -> {stock_after}")
    if problems:
        print("PROBLEMS FOUND:"); [print(" -", p) for p in problems]
        return 1
    print("STRIPE TEST-MODE CHECKOUT PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

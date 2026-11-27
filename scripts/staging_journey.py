"""Complete customer journey against a running DRUVO shop in Stripe TEST mode. No real money moves.

Steps (each prints PASS/FAIL):
 1. Browse: shop and product pages load, product has an add-to-basket button.
 2. Basket + pay: real browser adds the item, fills checkout, pays on Stripe with card 4242 4242 4242 4242.
 3. Confirmation: Stripe's webhook marks the order paid; stock goes down; confirmation + shop emails sent
    (only checked when RESEND_API_KEY is set).
 4. Tracking: customer finds the order with order number + email and sees "paid".
 5. Dispatch: owner signs in to /admin with 2-step code and marks it dispatched with tracking; customer
    page shows the tracking number; dispatch email sent.
 6. Return: owner marks delivered; customer requests a return from the order page.
 7. Refund: owner marks the return received and refunds with restock through /admin (real Stripe test
    refund); Stripe's charge.refunded webhook does not double-count; stock is back where it started.
 8. Last item: two customers start paying for the last unit at the same moment → exactly one gets a
    Stripe checkout, the other is told it's sold out.
 9. Expiry: the winning checkout is expired on Stripe → Stripe's checkout.session.expired webhook releases
    the stock, and the item can be bought again.

Usage: python scripts/staging_journey.py <app-url> <database-url>
Env:   STRIPE_SECRET_KEY (sk_test_ only), ADMIN_SETUP_TOKEN (same value the app has; a throwaway admin is
       created on an empty admin table) or ADMIN_EMAIL + ADMIN_PASSWORD + ADMIN_TOTP_SECRET for an existing one.
       PAY_MODE=browser (default, real Stripe page) | fake (local test against tests/fake_stripe.py).
       JOURNEY_EMAIL: customer email (default delivered@resend.dev — Resend's test inbox).
Refuses to run with a live key, and refuses to run against druvo.uk.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
import pyotp
import sqlalchemy as sa

APP = sys.argv[1].rstrip("/")
DB = sys.argv[2]
OUT = Path(os.environ.get("JOURNEY_OUT", "staging-journey"))
OUT.mkdir(parents=True, exist_ok=True)
PAY_MODE = os.environ.get("PAY_MODE", "browser")
EMAIL = os.environ.get("JOURNEY_EMAIL", "delivered@resend.dev")
KEY = os.environ.get("STRIPE_SECRET_KEY", "")
EMAILS_ON = bool(os.environ.get("RESEND_API_KEY"))

if not KEY.startswith("sk_test_"):
    sys.exit("Refusing to run: STRIPE_SECRET_KEY must be a TEST key (sk_test_...).")
if re.match(r"https?://(www\.)?druvo\.uk", APP):
    sys.exit("Refusing to run against the live shop. Use staging or a local copy.")

engine = sa.create_engine(DB)
http = httpx.Client(base_url=APP, timeout=60, follow_redirects=False)
results: list[tuple[str, bool, str]] = []


def one(sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(sa.text(sql), params).first()


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail else ''}", flush=True)
    return ok


def wait_for(fn, timeout: float = 60, every: float = 2):
    end = time.time() + timeout
    value = fn()
    while not value and time.time() < end:
        time.sleep(every)
        value = fn()
    return value


def hidden(html: str, name: str) -> str:
    m = re.search(rf'name="{name}" value="([^"]*)"', html)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- Stripe (real, or the local fake)

def stripe_post(path: str, data: dict | None = None) -> dict:
    import stripe

    stripe.api_key = KEY
    if os.environ.get("STRIPE_API_BASE"):
        stripe.api_base = os.environ["STRIPE_API_BASE"]
    if path.endswith("/expire"):
        return stripe.checkout.Session.expire(path.split("/")[-2])
    raise ValueError(path)


# ---------------------------------------------------------------- admin

class Admin:
    def __init__(self) -> None:
        self.c = httpx.Client(base_url=APP, timeout=60, follow_redirects=False)
        self.email = os.environ.get("ADMIN_EMAIL") or f"journey-{uuid.uuid4().hex[:6]}@druvo.uk"
        self.password = os.environ.get("ADMIN_PASSWORD") or f"Journey-{uuid.uuid4().hex}"
        self.secret = os.environ.get("ADMIN_TOTP_SECRET", "")

    def _fresh_code(self) -> str:
        totp = pyotp.TOTP(self.secret)
        step = int(time.time() // 30)
        if getattr(self, "_last_step", None) == step:  # codes can't be reused (replay protection)
            time.sleep(30 - time.time() % 30 + 1)
        self._last_step = int(time.time() // 30)
        return totp.now()

    def sign_in(self) -> None:
        if not self.secret:
            token = os.environ.get("ADMIN_SETUP_TOKEN", "")
            page = self.c.get("/admin/setup", params={"token": token})
            if page.status_code != 200:
                raise RuntimeError("Admin setup not available (set ADMIN_SETUP_TOKEN on an empty staging DB, "
                                   "or give ADMIN_EMAIL/ADMIN_PASSWORD/ADMIN_TOTP_SECRET)")
            self.secret = re.search(r"type the key <code>([A-Z2-7]+)</code>", page.text).group(1)
            done = self.c.post("/admin/setup", data={
                "token": token, "totp_token": hidden(page.text, "totp_token"), "email": self.email,
                "password": self.password, "password2": self.password, "code": self._fresh_code()})
            if "Admin account created" not in done.text:
                raise RuntimeError("Admin setup failed")
        r = self.c.post("/admin/login", data={"email": self.email, "password": self.password})
        if r.status_code != 303:
            raise RuntimeError("Admin password step failed")
        page = self.c.get("/admin/login/2fa")
        r = self.c.post("/admin/login/2fa", data={"csrf": hidden(page.text, "csrf"), "code": self._fresh_code()})
        if r.status_code != 303 or r.headers.get("location") != "/admin":
            raise RuntimeError("Admin 2-step sign-in failed")

    def action(self, number: str, action: str, **form) -> str:
        page = self.c.get(f"/admin/orders/{number}")
        r = self.c.post(f"/admin/orders/{number}/{action}", data={"csrf": hidden(page.text, "csrf"), **form})
        location = r.headers.get("location", "")
        if r.status_code != 303 or "err=" in location:
            raise RuntimeError(f"/admin {action} failed: {r.status_code} {httpx.URL(location).params.get('err', '')}")
        return location


# ---------------------------------------------------------------- payment

def pay_in_browser(slug: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1280, "height": 900}, locale="en-GB", timezone_id="Europe/London",
            # Headless Chromium announces itself as "HeadlessChrome"; use an ordinary desktop Chrome string.
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/131.0.0.0 Safari/537.36")
        try:
            _pay_steps(page, slug)
        except Exception:
            import traceback

            traceback.print_exc()
            # Stripe sometimes changes its page: keep evidence so the fix is quick.
            page.screenshot(path=str(OUT / "error.png"), full_page=True)
            print("URL:", page.url.split("?")[0].split("#")[0], "| title:", page.title())
            for frame in page.frames:
                try:
                    ids = frame.eval_on_selector_all(
                        "input, select, button", "els => els.map(e => (e.offsetParent ? '' : '(hidden)') + "
                        "e.tagName + '#' + (e.id || e.name || e.getAttribute('aria-label') || e.textContent.trim().slice(0, 30)))")
                    text = frame.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 400)")
                except Exception as exc:  # noqa: BLE001
                    ids, text = [f"<unreadable: {type(exc).__name__}>"], ""
                print(f"Frame {frame.url.split('?')[0][:80]}: fields={ids[:80]}")
                if text.strip():
                    print("   text:", " ".join(text.split())[:400])
            raise
        finally:
            browser.close()


def _pay_steps(page, slug: str) -> None:
    # On the shop: product page → basket → checkout form.
    page.goto(f"{APP}/product/{slug}", wait_until="networkidle")
    page.click("[data-add-to-cart]")
    page.wait_for_timeout(800)
    page.goto(f"{APP}/checkout", wait_until="networkidle")
    # Database mode asks only for contact details here (Stripe collects the address); the older form also had
    # address fields, so fill whichever are on the page.
    for selector, value in (("#email", EMAIL), ("#phone", "07911123456"), ("#first-name", "Test"),
                            ("#last-name", "Customer"), ("#address", "1 Test Street"), ("#city", "Manchester"),
                            ("#postcode", "M1 1AA")):
        loc = page.locator(selector)
        if loc.count() and loc.first.is_visible():
            loc.first.fill(value)
    page.screenshot(path=str(OUT / "1-checkout-form.png"), full_page=True)
    page.click("#place-order")

    # On Stripe's hosted page (test mode): delivery address, phone, then the 4242 test card.
    page.wait_for_url("https://checkout.stripe.com/**", timeout=60000)
    # Not "networkidle": Stripe's page keeps background connections open (wallets, bot check), so it never
    # goes quiet. The loop below waits for the card field itself.
    page.wait_for_load_state("domcontentloaded")
    page.screenshot(path=str(OUT / "2-stripe-checkout.png"), full_page=True)

    def find(selector: str):
        """First visible match in the page or any of Stripe's iframes, else None."""
        for frame in page.frames:
            loc = frame.locator(selector)
            try:
                if loc.count() and loc.first.is_visible():
                    return loc.first
            except Exception:  # noqa: BLE001 — frame navigated away
                continue
        return None

    # Stripe's hosted page (Nov 2026) renders its form inside a Stripe Elements iframe with ids such as
    # #payment-numberInput and #shippingAddress-nameInput; older pages used #cardNumber in the main frame.
    card_sel = "#payment-numberInput, #cardNumber, input[autocomplete='cc-number']"
    form_sel = card_sel + ", #shippingAddress-nameInput, #shippingName"

    def wait_for(selector: str, what: str, click_card: bool = False) -> None:
        deadline = time.time() + 60
        while find(selector) is None:
            if time.time() > deadline:
                raise TimeoutError(f"Stripe {what} did not appear within 60 s")
            if click_card:  # card may sit in a collapsed list of payment methods
                for frame in page.frames:
                    try:
                        tab = frame.locator("[data-testid='card-accordion-item-button'], "
                                            "button:has-text('Card'), [role=radio]:has-text('Card')")
                        if tab.count() and tab.first.is_visible():
                            tab.first.click(timeout=3000)
                            break
                    except Exception:  # noqa: BLE001
                        continue
            page.wait_for_timeout(1000)

    # Stripe sometimes shows the card section only after contact and delivery details are complete,
    # so fill those first, then wait for the card fields.
    wait_for(form_sel, "checkout form")

    def fill_if_shown(selector: str, value: str) -> None:
        loc = find(selector)
        if loc is not None and not loc.input_value(timeout=5000):
            loc.fill(value, timeout=10000)
            loc.press("Escape", timeout=5000)  # close any address suggestions list

    # Pay in pounds like a UK customer (Stripe offers its own currency conversion to foreign visitors).
    for frame in page.frames:  # the currency radio buttons are visually hidden, so don't require visibility
        gbp = frame.locator("#currency-gbp")
        if gbp.count():
            try:  # best effort: the total is charged in GBP to the shop either way
                label = frame.locator("label[for='currency-gbp']")
                (label.first if label.count() else gbp.first).click(force=True, timeout=5000)
                page.wait_for_timeout(1500)
                print("Currency chosen on Stripe's page: GBP" if gbp.first.is_checked() else
                      "Stripe's page kept its own currency choice (adaptive pricing)")
            except Exception as exc:  # noqa: BLE001
                print("Could not switch Stripe's currency selector:", type(exc).__name__)
            break
    country = find("#shippingAddress-countryInput, #shippingCountry")
    if country is not None and country.input_value() != "GB":
        try:  # GB is the only allowed country, so Stripe usually pre-selects and locks it
            country.select_option("GB", timeout=5000)
        except Exception as exc:  # noqa: BLE001
            print("Country selector left as Stripe set it:", type(exc).__name__)
    for selector, value in (("#linkAuthentication-emailInput, #email", EMAIL),
                            ("#shippingAddress-nameInput, #shippingName", "Test Customer"),
                            ("#shippingAddress-addressLine1Input, #shippingAddressLine1", "1 Test Street"),
                            ("#shippingAddress-localityInput, #shippingLocality", "Manchester"),
                            ("#shippingAddress-postalCodeInput, #shippingPostalCode", "M1 1AA")):
        fill_if_shown(selector, value)
    # Phone: Stripe rejects Ofcom's reserved 07700 900xxx drama numbers, so use a valid-format UK mobile
    # (test mode only — nothing is called or texted). Overwrite whatever was prefilled.
    phone = find("#shippingAddress-phoneInput, #phoneNumber")
    if phone is not None:
        phone.fill("7911 123456", timeout=10000)
    wait_for(card_sel, "card fields", click_card=True)
    find(card_sel).fill("4242 4242 4242 4242")
    find("#payment-expiryInput, #cardExpiry, input[autocomplete='cc-exp']").fill("12 / 34")
    find("#payment-cvcInput, #cardCvc, input[autocomplete='cc-csc']").fill("123")
    fill_if_shown("#billingName", "Test Customer")
    fill_if_shown("#billingPostalCode", "M1 1AA")
    page.screenshot(path=str(OUT / "3-card-entered.png"), full_page=True)
    submit = find("[data-testid='hosted-payment-submit-button'], .SubmitButton, button[type=submit]")
    if submit is None:
        raise RuntimeError("No Pay button found on Stripe's page")
    print("Pressing Stripe's pay button:", " ".join((submit.text_content() or "").split())[:40])
    submit.click()
    try:
        page.wait_for_url(lambda url: "checkout.stripe.com" not in url, timeout=90000)
    except Exception:
        # Why did Stripe not finish? Form errors, or a visible bot-check challenge?
        errors, values = [], {}
        for frame in page.frames:
            try:
                errors += frame.eval_on_selector_all(
                    "[role=alert], .FieldError, .p-FieldError, [id$='-error'], .Error",
                    "els => els.map(e => e.textContent.trim()).filter(t => t)")
                for sel in ("#shippingAddress-addressLine1Input", "#shippingAddress-localityInput",
                            "#shippingAddress-postalCodeInput", "#shippingAddress-nameInput", "#payment-numberInput"):
                    if frame.locator(sel).count():
                        values[sel] = bool(frame.locator(sel).first.input_value())
            except Exception:  # noqa: BLE001
                continue
        visible_challenge = False
        for el in page.query_selector_all("iframe[src*='hcaptcha']"):
            box = el.bounding_box()
            if box and box["width"] > 100 and box["height"] > 100 and el.is_visible():
                visible_challenge = True
        print("Form errors shown by Stripe:", errors[:10])
        print("Fields holding a value:", values)
        print("Visible hCaptcha challenge:", visible_challenge)
        raise RuntimeError("Stripe did not finish the payment within 90 s"
                           + (" — Stripe showed its hCaptcha bot check" if visible_challenge else "")
                           + (f" — form errors: {errors[:3]}" if errors else ""))
    page.screenshot(path=str(OUT / "4-back-on-shop.png"), full_page=True)


def pay_fake(slug: str, sku: str, price: float) -> None:
    r = http.post("/api/checkout/payment-session", json={
        "customer_email": EMAIL, "customer_name": "Test Customer", "external_order_id": uuid.uuid4().hex,
        "lines": [{"sku": sku, "quantity": 1, "unit_price_gbp": price}]})
    r.raise_for_status()
    session_id = r.json()["session_id"]
    httpx.post(f"{os.environ['STRIPE_API_BASE']}/_test/pay/{session_id}", timeout=30).raise_for_status()


# ---------------------------------------------------------------- journey

def main() -> int:
    row = one("SELECT v.sku, v.stock_quantity, p.slug, v.price_pence FROM variants v JOIN products p ON p.id = v.product_id "
              "WHERE v.stock_quantity > 0 AND p.status = 'live' ORDER BY v.id LIMIT 1")
    if not row:
        print("No product with stock on staging"); return 1
    sku, stock0, slug, price_pence = row
    print(f"Product {sku} ({slug}) — stock at start: {stock0}")

    # 1. Browse
    shop, product = http.get("/shop"), http.get(f"/product/{slug}")
    check("1 Browse shop and product page", shop.status_code == 200 and product.status_code == 200
          and "data-add-to-cart" in product.text and slug in shop.text)

    # 2. Basket and payment
    started = time.time()
    try:
        pay_in_browser(slug) if PAY_MODE == "browser" else pay_fake(slug, sku, price_pence / 100)
        check("2 Basket → Stripe Checkout → test card 4242 accepted", True)
    except Exception as exc:  # noqa: BLE001
        check("2 Basket → Stripe Checkout → test card 4242 accepted", False, f"{type(exc).__name__}: {exc}")
        return summary()

    # 3. Confirmation
    order = wait_for(lambda: one("SELECT order_number, status, confirmation_email_sent_at, shop_notification_sent_at "
                                 "FROM orders WHERE email = :e AND status = 'paid' AND created_at > to_timestamp(:t) "
                                 "ORDER BY id DESC LIMIT 1", e=EMAIL.lower(), t=started - 5), 90)
    if not check("3 Webhook marks order paid", bool(order)):
        return summary()
    number = order[0]
    check("3 Stock reduced by one", one("SELECT stock_quantity FROM variants WHERE sku=:s", s=sku)[0] == stock0 - 1)
    if EMAILS_ON:
        sent = wait_for(lambda: one("SELECT confirmation_email_sent_at IS NOT NULL AND shop_notification_sent_at IS NOT NULL "
                                    "FROM orders WHERE order_number=:n", n=number)[0], 30)
        check("3 Confirmation + shop emails sent (Resend)", bool(sent))

    # 4. Tracking
    found = http.post("/orders/find", data={"order_number": number, "email": EMAIL})
    track = found.headers.get("location", "")
    page = http.get(track) if track else None
    check("4 Customer finds order (number + email) and sees 'paid'",
          found.status_code == 303 and page is not None and 'data-order-status="paid"' in page.text)
    check("4 Wrong email is refused", http.post("/orders/find", data={"order_number": number,
                                                                       "email": "someone@else.example"}).status_code == 404)

    # 5. Dispatch via /admin
    admin = Admin()
    try:
        admin.sign_in()
        check("5 Owner signs in to /admin with password + 2-step code", True)
        admin.action(number, "dispatch", carrier="Royal Mail", tracking_number="JT123456789GB", tracking_url="")
        shipped = http.get(track).text
        check("5 Marked dispatched; customer page shows tracking",
              'data-order-status="shipped"' in shipped and "JT123456789GB" in shipped)
        if EMAILS_ON:
            check("5 Dispatch email sent", bool(wait_for(lambda: one(
                "SELECT dispatch_email_sent_at FROM orders WHERE order_number=:n", n=number)[0], 30)))

        # 6. Delivered + return request
        admin.action(number, "delivered")
        token = track.split("t=")[1]
        r = http.post(f"/orders/{number}/return", data={"t": token, "reason": "Too small"})
        after = http.get(track).text
        check("6 Customer requests a return from the order page",
              r.status_code == 303 and 'data-return-status="requested"' in after)

        # 7. Return received + refund with restock (real Stripe test refund)
        admin.action(number, "return-received")
        total = one("SELECT total_pence FROM orders WHERE order_number=:n", n=number)[0]
        admin.action(number, "refund", confirm="1", restock="1", amount=f"{total / 100:.2f}", reason="Journey test")
        time.sleep(8)  # let Stripe's charge.refunded webhook arrive too
        o = one("SELECT status, refunded_pence, total_pence FROM orders WHERE order_number=:n", n=number)
        refunds = one("SELECT count(*), sum(amount_pence) FROM refunds r JOIN orders o ON o.id=r.order_id "
                      "WHERE o.order_number=:n", n=number)
        check("7 Refunded in full via Stripe, webhook not double-counted",
              o[0] == "refunded" and o[1] == o[2] and refunds[0] == 1 and refunds[1] == o[2], f"{o} refunds={refunds}")
        check("7 Stock restored", one("SELECT stock_quantity FROM variants WHERE sku=:s", s=sku)[0] == stock0)
        final = http.get(track).text
        check("7 Customer page shows refunded", 'data-order-status="refunded"' in final)
        if EMAILS_ON:
            check("7 Refund email sent", bool(wait_for(lambda: one(
                "SELECT bool_and(email_sent_at IS NOT NULL) FROM refunds r JOIN orders o ON o.id=r.order_id "
                "WHERE o.order_number=:n", n=number)[0], 30)))
    except Exception as exc:  # noqa: BLE001
        check("5–7 Admin dispatch / return / refund", False, f"{type(exc).__name__}: {exc}")

    # 8. Two customers, one last item
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE variants SET stock_quantity = 1 WHERE sku = :s"), {"s": sku})

    def attempt(i: int) -> httpx.Response:
        return httpx.post(f"{APP}/api/checkout/payment-session", timeout=60, json={
            "customer_email": f"race{i}@example.com", "customer_name": f"Racer {i}",
            "external_order_id": uuid.uuid4().hex, "lines": [{"sku": sku, "quantity": 1, "unit_price_gbp": 0}]})

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        race = list(pool.map(attempt, [1, 2]))
    codes = sorted(r.status_code for r in race)
    check("8 Two buyers, last item: exactly one gets checkout, other is refused",
          codes == [200, 409] and one("SELECT stock_quantity FROM variants WHERE sku=:s", s=sku)[0] == 0, f"{codes}")

    # 9. Expired checkout releases stock
    winner = next((r.json() for r in race if r.status_code == 200), None)
    if winner:
        stripe_post(f"/v1/checkout/sessions/{winner['session_id']}/expire")
        released = wait_for(lambda: one("SELECT stock_quantity FROM variants WHERE sku=:s", s=sku)[0] == 1, 60)
        status = one("SELECT status FROM orders WHERE order_number=:n", n=winner["order_number"])[0]
        check("9 Expired checkout releases the stock", bool(released) and status == "expired", status)
        again = attempt(3)
        check("9 Item can be bought again after expiry", again.status_code == 200)
        if again.status_code == 200:
            stripe_post(f"/v1/checkout/sessions/{again.json()['session_id']}/expire")
            wait_for(lambda: one("SELECT stock_quantity FROM variants WHERE sku=:s", s=sku)[0] == 1, 60)
    with engine.begin() as conn:
        conn.execute(sa.text("UPDATE variants SET stock_quantity = :q WHERE sku = :s"), {"q": stock0, "s": sku})
    return summary()


def summary() -> int:
    failed = [r for r in results if not r[1]]
    real = PAY_MODE == "browser" and not os.environ.get("STRIPE_API_BASE")
    services = [
        ("Stripe API (checkout, refunds, expiry)", "REAL — Stripe test mode" if real else "SIMULATED — tests/fake_stripe.py"),
        ("Stripe hosted payment page + test card 4242", "REAL — Chromium on checkout.stripe.com" if real else "SIMULATED — no browser"),
        ("Stripe webhooks", "REAL — sent by Stripe, forwarded by Stripe CLI, signature checked" if real
         else "SIMULATED — signed by the stand-in, signature checked"),
        ("Emails", ("REAL — Resend API, test inbox delivered@resend.dev" if real else "SIMULATED — stand-in Resend")
         if EMAILS_ON else "NOT TESTED — no RESEND_API_KEY"),
        ("Shop, /admin with 2-step sign-in, PostgreSQL 16", "REAL — this branch, throwaway database (not druvo.uk)"),
    ]
    lines = [f"{'PASS' if ok else 'FAIL'}  {name}{(' — ' + d) if d else ''}" for name, ok, d in results]
    (OUT / "results.txt").write_text("\n".join(lines) + "\n\n" + "\n".join(f"{a}: {b}" for a, b in services) + "\n")
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    for a, b in services:
        print(f"  {a}: {b}")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as fh:
            fh.write(f"## Customer journey — {len(results) - len(failed)}/{len(results)} checks passed\n\n")
            fh.write("| Result | Check |\n|---|---|\n")
            fh.writelines(f"| {'✅' if ok else '❌'} | {name}{(' — ' + d) if d else ''} |\n" for name, ok, d in results)
            fh.write("\n| Service | How it was tested |\n|---|---|\n")
            fh.writelines(f"| {a} | {b} |\n" for a, b in services)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

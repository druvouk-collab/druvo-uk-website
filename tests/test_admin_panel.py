"""Admin dashboard: 2FA login, CSRF, products & photos, orders, discounts, reports, GDPR, headers."""

from __future__ import annotations

import io
import re
import time

import pyotp
import pytest
import stripe
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.admin import security as sec
from app.config import get_settings
from app.db import models
from app.db.base import session_scope
from app.services import reporting
from app.services.alerts import reset_throttle
from tests.test_db_checkout import SKU as _SKU  # noqa: F401
from tests.test_db_checkout import _checkout, _order, _paid_event, shop  # noqa: F401
from tests.db_support import db_url  # noqa: F401

SETUP_TOKEN = "setup-token-abcdefghijklmnop"
EMAIL = "owner@druvo.uk"
PASSWORD = "Correct-Horse-Battery-9"


@pytest.fixture
def admin_env(shop, monkeypatch):
    monkeypatch.setenv("ADMIN_SETUP_TOKEN", SETUP_TOKEN)
    monkeypatch.setenv("SESSION_SECRET", "x" * 48)
    get_settings.cache_clear()
    sec.login_limiter.reset()
    reset_throttle()
    from app.main import app

    client = TestClient(app, base_url="https://testserver")
    yield {"client": client, **shop}
    sec.login_limiter.reset()


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def _setup_owner(client) -> str:
    page = client.get(f"/admin/setup?token={SETUP_TOKEN}")
    assert page.status_code == 200
    secret = re.search(r"type the key <code>([A-Z2-7]+)</code>", page.text).group(1)
    totp_token = re.search(r'name="totp_token" value="([^"]+)"', page.text).group(1)
    done = client.post("/admin/setup", data={
        "token": SETUP_TOKEN, "totp_token": totp_token, "email": EMAIL, "password": PASSWORD,
        "password2": PASSWORD, "code": pyotp.TOTP(secret).now()})
    assert "Admin account created" in done.text
    assert len(re.findall(r"<code>[0-9A-F]{6}-[0-9A-F]{6}</code>", done.text)) == 8
    return secret


def _next_code(secret: str) -> str:
    with session_scope() as db:
        last = db.scalar(select(models.AdminUser)).totp_last_step
    step = max(int(time.time()) // 30, last + 1)
    return pyotp.TOTP(secret).at(step * 30)


def _login(client, secret: str) -> str:
    r = client.post("/admin/login", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=True)
    assert "authenticator" in r.text
    r = client.post("/admin/login/2fa", data={"csrf": _csrf(r.text), "code": _next_code(secret)}, follow_redirects=True)
    assert r.status_code == 200 and "Overview" in r.text
    return _csrf(r.text)


def test_setup_login_2fa_and_lockout(admin_env):
    client = admin_env["client"]
    assert client.get("/admin/setup?token=wrong").status_code == 404
    secret = _setup_owner(client)
    assert client.get(f"/admin/setup?token={SETUP_TOKEN}").status_code == 404  # one-time

    # Admin pages need a full 2FA session.
    assert client.get("/admin/orders", follow_redirects=False).headers["location"] == "/admin/login"
    client.post("/admin/login", data={"email": EMAIL, "password": PASSWORD})
    assert client.get("/admin/orders", follow_redirects=False).status_code == 303  # password only is not enough
    client.cookies.clear()

    csrf = _login(client, secret)
    assert client.get("/admin/products").status_code == 200

    # The same 2FA code can't be replayed.
    client.cookies.clear()
    with session_scope() as db:
        used = db.scalar(select(models.AdminUser)).totp_last_step
    r = client.post("/admin/login", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=True)
    r = client.post("/admin/login/2fa", data={"csrf": _csrf(r.text), "code": pyotp.TOTP(secret).at(used * 30)},
                    follow_redirects=True)
    assert "That code didn" in r.text

    # Five wrong passwords lock the account (per-account lockout, separate from the per-IP limit).
    client.cookies.clear()
    sec.login_limiter.reset()
    for _ in range(5):
        client.post("/admin/login", data={"email": EMAIL, "password": "wrong-password-123"})
    r = client.post("/admin/login", data={"email": EMAIL, "password": PASSWORD})
    assert "locked" in r.text, re.findall(r"a-flash err[^>]*>([^<]+)", r.text)
    assert csrf
    # Per-IP rate limit: 10 attempts per 15 minutes.
    for _ in range(10):
        client.post("/admin/login", data={"email": "x@example.com", "password": "nope-nope-nope"})
    assert "Too many attempts" in client.post("/admin/login", data={"email": EMAIL, "password": PASSWORD}).text


def test_recovery_code_login(admin_env):
    client = admin_env["client"]
    page = client.get(f"/admin/setup?token={SETUP_TOKEN}")
    secret = re.search(r"type the key <code>([A-Z2-7]+)</code>", page.text).group(1)
    totp_token = re.search(r'name="totp_token" value="([^"]+)"', page.text).group(1)
    done = client.post("/admin/setup", data={"token": SETUP_TOKEN, "totp_token": totp_token, "email": EMAIL,
                                             "password": PASSWORD, "password2": PASSWORD, "code": pyotp.TOTP(secret).now()})
    code = re.findall(r"<code>([0-9A-F]{6}-[0-9A-F]{6})</code>", done.text)[0]
    r = client.post("/admin/login", data={"email": EMAIL, "password": PASSWORD}, follow_redirects=True)
    r = client.post("/admin/login/2fa", data={"csrf": _csrf(r.text), "code": code}, follow_redirects=True)
    assert "Overview" in r.text
    with session_scope() as db:
        assert len(db.scalar(select(models.AdminUser)).recovery_codes) == 7


def test_csrf_required_and_security_headers(admin_env):
    client = admin_env["client"]
    secret = _setup_owner(client)
    _login(client, secret)
    assert client.post("/admin/products/new", data={"name": "No token"}).status_code == 403
    r = client.get("/admin")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    home = client.get("/")
    assert home.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" in home.headers


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (2400, 1200), (200, 180, 150)).save(buf, format="PNG")
    return buf.getvalue()


def test_product_create_edit_photo_and_storefront(admin_env):
    client = admin_env["client"]
    csrf = _login(client, _setup_owner(client))
    form = {
        "csrf": csrf, "name": "Nike Air Max 90 Trainers White UK 9", "description": "Pre-loved, excellent condition.",
        "brand": "Nike", "condition": "Pre-loved – Excellent", "category": "footwear", "status": "live",
        "variant_count": "0", "v0_sku": "nk-am90-w-9", "v0_size": "UK 9", "v0_colour": "White",
        "v0_price": "45.00", "v0_cost": "18.50", "v0_stock": "1", "v0_threshold": "1",
    }
    r = client.post("/admin/products/new", data=form, follow_redirects=False)
    assert r.status_code == 303, r.text
    pid = int(re.search(r"/admin/products/(\d+)", r.headers["location"]).group(1))
    with session_scope() as db:
        v = db.scalar(select(models.Variant).where(models.Variant.sku == "NK-AM90-W-9"))
        assert v.price_pence == 4500 and v.cost_pence == 1850
        assert db.scalar(select(models.OutboxEvent).where(models.OutboxEvent.topic == "product.updated"))

    up = client.post(f"/admin/products/{pid}/images", data={"csrf": csrf, "alt": "White Air Max side view"},
                     files={"photo": ("shoe.png", _png(), "image/png")}, follow_redirects=False)
    assert "Photo+added" in up.headers["location"]
    with session_scope() as db:
        img = db.scalar(select(models.ProductImage).where(models.ProductImage.product_id == pid))
        url = img.url
    media = client.get(url)
    assert media.status_code == 200 and media.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(media.content)).size) == 1600  # resized
    bad = client.post(f"/admin/products/{pid}/images", data={"csrf": csrf},
                      files={"photo": ("x.png", b"not an image", "image/png")}, follow_redirects=False)
    assert "supported+photo" in bad.headers["location"]

    page = client.get("/product/nike-air-max-90-trainers-white-uk-9")
    assert page.status_code == 200 and url in page.text

    # Duplicate SKU on another product is refused.
    form2 = dict(form, name="Another product", v0_sku="NK-AM90-W-9")
    r2 = client.post("/admin/products/new", data=form2, follow_redirects=False)
    assert "already+used" in r2.headers["location"]


def test_admin_dispatch_and_refund(admin_env):
    client = admin_env["client"]
    csrf = _login(client, _setup_owner(client))
    result = _checkout()
    from app.services.db_checkout import DbCheckoutService

    DbCheckoutService().handle_event(_paid_event(result["session_id"], _order(result["order_number"])))
    number = result["order_number"]
    assert number in client.get("/admin").text  # in "to dispatch"
    r = client.post(f"/admin/orders/{number}/dispatch", data={"csrf": csrf, "carrier": "Royal Mail",
                                                              "tracking_number": "AB123456789GB", "postage_cost": "3.20"},
                    follow_redirects=True)
    assert "Dispatched" in r.text
    order = _order(number)
    assert order.status == "shipped" and order.postage_cost_pence == 320
    r = client.post(f"/admin/orders/{number}/refund", data={"csrf": csrf, "amount": "5.00", "reason": "Goodwill"},
                    follow_redirects=True)
    assert "confirmation box" in r.text
    r = client.post(f"/admin/orders/{number}/refund", data={"csrf": csrf, "amount": "5.00", "reason": "Goodwill",
                                                            "confirm": "1"}, follow_redirects=True)
    assert "Refund issued" in r.text
    assert _order(number).status == "partially_refunded"
    csv_text = client.get("/admin/orders.csv").text
    assert number in csv_text


def test_discount_code_applied_at_checkout(admin_env, monkeypatch):
    client = admin_env["client"]
    csrf = _login(client, _setup_owner(client))
    coupons = []
    monkeypatch.setattr(stripe.Coupon, "create", staticmethod(lambda **kw: coupons.append(kw) or {"id": "co_1"}))
    r = client.post("/admin/promotions", data={"csrf": csrf, "code": "welcome10", "discount_type": "percent", "value": "10"},
                    follow_redirects=True)
    assert "WELCOME10 created" in r.text
    from app.services.db_checkout import BasketLine, DbCheckoutService, PromoCodeError

    out = DbCheckoutService().create_checkout(customer_email="d@example.com", customer_name="D",
                                              lines=[BasketLine(_current_sku(), 1)], promo_code="welcome10")
    order = _order(out["order_number"])
    assert order.discount_pence == order.subtotal_pence // 10
    assert order.total_pence == order.subtotal_pence - order.discount_pence + order.shipping_pence
    assert coupons[0]["amount_off"] == order.discount_pence
    assert admin_env["sessions"][-1]["discounts"] == [{"coupon": "co_1"}]
    DbCheckoutService().handle_event(_paid_event(out["session_id"], order))
    with session_scope() as db:
        assert db.scalar(select(models.Promotion)).times_used == 1
    with pytest.raises(PromoCodeError):
        DbCheckoutService().create_checkout(customer_email="e@example.com", customer_name="E",
                                            lines=[BasketLine(_current_sku(), 1)], promo_code="NOPE")


def _current_sku() -> str:
    with session_scope() as db:
        v = db.scalar(select(models.Variant).where(models.Variant.stock_quantity > 0))
        v.stock_quantity = 5
        return v.sku


def test_profit_report(admin_env):
    with session_scope() as db:
        v = db.scalar(select(models.Variant))
        v.cost_pence = 800
        v.stock_quantity = 3
    result = _checkout()
    from app.services.db_checkout import DbCheckoutService

    DbCheckoutService().handle_event(_paid_event(result["session_id"], _order(result["order_number"])))
    with session_scope() as db:
        o = db.scalar(select(models.Order).where(models.Order.order_number == result["order_number"]))
        assert o.payment_fee_pence == 56
        o.postage_cost_pence = 320
        db.add(models.Expense(spent_on=o.paid_at, category="Packaging", amount_pence=100))
        total = o.total_pence
    t = reporting.summary_cards()[0][1]
    assert t.orders == 1 and t.gross_pence == total
    assert t.profit_pence == total - 800 - 56 - 320 - 100
    client = admin_env["client"]
    _login(client, _setup_owner(client))
    for by in ("day", "week", "month", "year"):
        assert client.get(f"/admin/reports?by={by}").status_code == 200


def test_customer_export_and_erase(admin_env):
    client = admin_env["client"]
    csrf = _login(client, _setup_owner(client))
    result = _checkout(email="gdpr@example.com")
    from app.services.db_checkout import DbCheckoutService

    DbCheckoutService().handle_event(_paid_event(result["session_id"], _order(result["order_number"])))
    with session_scope() as db:
        cid = db.scalar(select(models.Customer).where(models.Customer.email == "gdpr@example.com")).id
    export = client.get(f"/admin/customers/{cid}/export.json").json()
    assert export["customer"]["email"] == "gdpr@example.com" and export["orders"]
    r = client.post(f"/admin/customers/{cid}/erase", data={"csrf": csrf, "confirm": "ERASE"}, follow_redirects=True)
    assert "in progress" in r.text  # paid order not yet complete
    with session_scope() as db:
        db.scalar(select(models.Order).where(models.Order.order_number == result["order_number"])).status = "delivered"
    r = client.post(f"/admin/customers/{cid}/erase", data={"csrf": csrf, "confirm": "ERASE"}, follow_redirects=True)
    assert "erased" in r.text
    order = _order(result["order_number"])
    assert order.email.endswith("@deleted.invalid") and order.shipping_address == {}
    assert order.total_pence > 0


def test_admin_refuses_weak_secret_in_production(admin_env, monkeypatch):
    monkeypatch.setenv("PRODUCTION_MODE", "true")
    monkeypatch.setenv("SESSION_SECRET", "dev-only-change-in-production")
    get_settings.cache_clear()
    client = admin_env["client"]
    client.cookies.set(sec.COOKIE_NAME, "anything")
    assert client.get("/admin").status_code == 503


def test_daily_digest_and_maintenance(admin_env):
    from app.services.background import run_maintenance_once, send_daily_digest

    with session_scope() as db:
        db.scalar(select(models.Variant)).stock_quantity = 0
    assert send_daily_digest(force=True) is True
    digest = [e for e in admin_env["emails"] if "Daily summary" in e["json"]["subject"]]
    assert digest and "sold-out" in digest[0]["json"]["text"].lower()
    assert "released_orders" in run_maintenance_once()

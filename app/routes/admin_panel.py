"""Admin dashboard routes (server-rendered, mobile-friendly, password + 2FA protected).

Available when the cloud database is enabled (CATALOG_SOURCE=db). Every POST checks a
CSRF token; every change is written to the audit log.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import func, or_, select

from app.admin import security as sec
from app.config import get_settings
from app.db import models
from app.db.base import session_scope
from app.services import catalog_admin, channel_sync, inventory, order_ops, reporting
from app.services.order_ops import audit
from app.templating import templates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin-panel"], include_in_schema=False)
media_router = APIRouter(tags=["media"], include_in_schema=False)

NAV = [
    ("/admin", "Overview"),
    ("/admin/tasks", "Tasks"),
    ("/admin/orders", "Orders"),
    ("/admin/products", "Products"),
    ("/admin/inventory", "Inventory"),
    ("/admin/customers", "Customers"),
    ("/admin/promotions", "Discounts"),
    ("/admin/reports", "Sales & profit"),
    ("/admin/expenses", "Expenses"),
    ("/admin/channels", "Platforms"),
    ("/admin/activity", "Activity"),
]


def _require_db() -> None:
    if not get_settings().database_enabled:
        raise HTTPException(status_code=404)


def _money(pence: int | None) -> str:
    if pence is None:
        return "—"
    sign = "-" if pence < 0 else ""
    return f"{sign}£{abs(pence) / 100:,.2f}"


def _render(request: Request, name: str, session: sec.AdminSession | None, **ctx) -> HTMLResponse:
    flash = request.query_params.get("msg", "")
    error = request.query_params.get("err", "")
    return templates.TemplateResponse(
        request,
        f"admin/{name}.html",
        {"admin": session, "nav": NAV, "money": _money, "flash": flash, "error": error,
         "test_mode": get_settings().stripe_mode != "live", **ctx},
    )


def _redirect(url: str, msg: str = "", err: str = "") -> RedirectResponse:
    from urllib.parse import urlencode

    query = urlencode({k: v for k, v in (("msg", msg), ("err", err)) if v})
    return RedirectResponse(url + (("&" if "?" in url else "?") + query if query else ""), status_code=303)


class AdminLoginRequired(Exception):
    """Raised when an admin page is opened without a fully authenticated (2FA) session."""


def _session(request: Request) -> sec.AdminSession:
    _require_db()
    session = sec.read_session(request)
    if session is None:
        raise AdminLoginRequired()
    return session


async def _post(request: Request) -> tuple[sec.AdminSession, dict]:
    session = _session(request)
    form = await request.form()
    sec.check_csrf(session, str(form.get("csrf", "")))
    return session, form


# ====================================================================== setup & login


def _setup_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().session_secret, salt="druvo-admin-setup")


def _setup_allowed(token: str) -> bool:
    expected = get_settings().admin_setup_token.strip()
    return bool(expected) and len(expected) >= 16 and secrets.compare_digest(token, expected) and sec.admin_count() == 0


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, token: str = ""):
    _require_db()
    if not await run_in_threadpool(_setup_allowed, token):
        raise HTTPException(status_code=404)
    secret = sec.new_totp_secret()
    return _render(request, "setup", None, token=token, totp_token=_setup_serializer().dumps(secret),
                   secret=secret, qr="", step="form")


@router.post("/setup", response_class=HTMLResponse)
async def setup_submit(request: Request):
    _require_db()
    form = await request.form()
    token = str(form.get("token", ""))
    if not await run_in_threadpool(_setup_allowed, token):
        raise HTTPException(status_code=404)
    try:
        secret = _setup_serializer().loads(str(form.get("totp_token", "")), max_age=3600)
    except BadSignature as exc:
        raise HTTPException(status_code=400, detail="Setup expired — reload the page.") from exc
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    error = ""
    try:
        if "@" not in email:
            raise sec.AdminAuthError("Enter a valid email address.")
        sec.validate_new_password(password, email)
        if password != str(form.get("password2", "")):
            raise sec.AdminAuthError("Passwords don't match.")
        step = sec.verify_totp(secret, str(form.get("code", "")))
        if step is None:
            raise sec.AdminAuthError("The 6-digit code didn't match — check your phone's time and try again.")
    except sec.AdminAuthError as exc:
        error = str(exc)
    if error:
        return _render(request, "setup", None, token=token, totp_token=form.get("totp_token"), secret=secret,
                       step="form", form_error=error, email=email)
    plain_codes, hashed = sec.new_recovery_codes()

    def create() -> None:
        with session_scope() as db:
            db.add(models.AdminUser(email=email, password_hash=sec.hash_password(password), totp_secret=secret,
                                    totp_last_step=step, recovery_codes=hashed, role="owner"))
            audit(db, email, "admin.created", "admin", email)

    await run_in_threadpool(create)
    return _render(request, "setup", None, step="done", recovery_codes=plain_codes)


@router.get("/setup/qr.svg")
async def setup_qr(request: Request, t: str = "", email: str = "admin"):
    _require_db()
    if sec.admin_count() != 0:
        raise HTTPException(status_code=404)
    try:
        secret = _setup_serializer().loads(t, max_age=3600)
    except BadSignature as exc:
        raise HTTPException(status_code=404) from exc
    svg = sec.totp_qr_svg(sec.totp_uri(secret, email or "admin"))
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    _require_db()
    if sec.read_session(request):
        return _redirect("/admin")
    return _render(request, "login", None, step="password", setup_needed=sec.admin_count() == 0)


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    _require_db()
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    password = str(form.get("password", ""))
    if not sec.login_limiter.hit(sec.client_ip(request)):
        return _render(request, "login", None, step="password", form_error="Too many attempts. Try again in 15 minutes.")

    def check():
        with session_scope() as db:
            admin = db.scalar(select(models.AdminUser).where(models.AdminUser.email == email))
            if admin is None:
                sec.verify_password(sec.hash_password("timing-equaliser"), password)
                return None, "Email or password is incorrect."
            if not admin.is_active or sec.is_locked(admin):
                return None, "This account is temporarily locked. Try again in 15 minutes."
            if not sec.verify_password(admin.password_hash, password):
                sec.register_failure(admin)
                audit(db, email, "admin.login_failed", "admin", email, ip=sec.client_ip(request))
                return None, "Email or password is incorrect."
            return admin, ""

    admin, error = await run_in_threadpool(check)
    if admin is None:
        return _render(request, "login", None, step="password", form_error=error, email=email)
    response = _redirect("/admin/login/2fa")
    sec.issue_cookie(response, admin, mfa=False, request=request)
    return response


@router.get("/login/2fa", response_class=HTMLResponse)
async def login_2fa_page(request: Request):
    _require_db()
    pending = sec.read_session(request, require_mfa=False)
    if pending is None:
        return _redirect("/admin/login")
    return _render(request, "login", pending, step="2fa")


@router.post("/login/2fa", response_class=HTMLResponse)
async def login_2fa_submit(request: Request):
    _require_db()
    pending = sec.read_session(request, require_mfa=False)
    if pending is None:
        return _redirect("/admin/login")
    form = await request.form()
    sec.check_csrf(pending, str(form.get("csrf", "")))
    code = str(form.get("code", "")).strip()
    if not sec.login_limiter.hit(sec.client_ip(request)):
        return _render(request, "login", pending, step="2fa", form_error="Too many attempts. Try again in 15 minutes.")

    def check():
        with session_scope() as db:
            admin = db.get(models.AdminUser, pending.admin_id)
            if admin is None or sec.is_locked(admin):
                return None, "This account is temporarily locked."
            step = sec.verify_totp(admin.totp_secret, code, admin.totp_last_step)
            if step is not None:
                admin.totp_last_step = step
            else:
                remaining = sec.use_recovery_code(admin.recovery_codes, code) if "-" in code else None
                if remaining is None:
                    sec.register_failure(admin)
                    audit(db, admin.email, "admin.2fa_failed", "admin", admin.email, ip=sec.client_ip(request))
                    return None, "That code didn't work. Codes change every 30 seconds."
                admin.recovery_codes = remaining
                audit(db, admin.email, "admin.recovery_code_used", "admin", admin.email, left=len(remaining))
            admin.failed_logins = 0
            admin.last_login_at = datetime.now(timezone.utc)
            audit(db, admin.email, "admin.login", "admin", admin.email, ip=sec.client_ip(request))
            db.flush()
            db.expunge(admin)
            return admin, ""

    admin, error = await run_in_threadpool(check)
    if admin is None:
        return _render(request, "login", pending, step="2fa", form_error=error)
    response = _redirect("/admin")
    sec.issue_cookie(response, admin, mfa=True, request=request)
    return response


@router.post("/logout")
async def logout(request: Request):
    session = sec.read_session(request, require_mfa=False)
    form = await request.form()
    if session:
        sec.check_csrf(session, str(form.get("csrf", "")))
        if form.get("everywhere"):
            def bump():
                with session_scope() as db:
                    db.get(models.AdminUser, session.admin_id).session_version += 1
            await run_in_threadpool(bump)
    response = _redirect("/admin/login", msg="Signed out.")
    sec.clear_cookie(response)
    return response


@router.get("/account", response_class=HTMLResponse)
async def account_page(request: Request):
    session = _session(request)
    with session_scope() as db:
        admin = db.get(models.AdminUser, session.admin_id)
        codes_left = len(admin.recovery_codes or [])
    return _render(request, "account", session, codes_left=codes_left)


@router.post("/account/password")
async def change_password(request: Request):
    session, form = await _post(request)
    try:
        with session_scope() as db:
            admin = db.get(models.AdminUser, session.admin_id)
            if not sec.verify_password(admin.password_hash, str(form.get("current", ""))):
                raise sec.AdminAuthError("Current password is incorrect.")
            new = str(form.get("new", ""))
            sec.validate_new_password(new, admin.email)
            if new != str(form.get("new2", "")):
                raise sec.AdminAuthError("New passwords don't match.")
            admin.password_hash = sec.hash_password(new)
            admin.session_version += 1
            audit(db, admin.email, "admin.password_changed", "admin", admin.email)
    except sec.AdminAuthError as exc:
        return _redirect("/admin/account", err=str(exc))
    response = _redirect("/admin/login", msg="Password changed — please sign in again.")
    sec.clear_cookie(response)
    return response


@router.post("/account/recovery-codes", response_class=HTMLResponse)
async def regenerate_recovery_codes(request: Request):
    session, _ = await _post(request)
    plain, hashed = sec.new_recovery_codes()
    with session_scope() as db:
        db.get(models.AdminUser, session.admin_id).recovery_codes = hashed
        audit(db, session.email, "admin.recovery_codes_regenerated", "admin", session.email)
    return _render(request, "account", session, codes_left=len(plain), new_codes=plain)


# ====================================================================== overview


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    session = _session(request)

    def load():
        return {
            "cards": reporting.summary_cards(),
            "pending": reporting.pending_orders(10),
            "low_stock": reporting.low_stock(10),
            "attention": reporting.orders_needing_attention(),
        }

    data = await run_in_threadpool(load)
    return _render(request, "overview", session, **data)


# ====================================================================== orders


@router.get("/orders", response_class=HTMLResponse)
async def orders_list(request: Request, status: str = "", q: str = "", page: int = 1, channel: str = ""):
    session = _session(request)
    page = max(page, 1)
    with session_scope() as db:
        query = select(models.Order).order_by(models.Order.created_at.desc())
        if status == "open":
            query = query.where(models.Order.status.in_(("paid", "packed")))
        elif status:
            query = query.where(models.Order.status == status)
        else:
            query = query.where(models.Order.status != "pending_payment")
        if channel:
            query = query.where(models.Order.channel == channel)
        if q.strip():
            like = f"%{q.strip().lower()}%"
            query = query.where(or_(func.lower(models.Order.order_number).like(like),
                                    func.lower(models.Order.email).like(like), func.lower(models.Order.name).like(like)))
        orders = db.scalars(query.offset((page - 1) * 50).limit(51)).all()
        channels = db.scalars(select(models.Channel).order_by(models.Channel.id)).all()
    return _render(request, "orders", session, orders=orders[:50], has_more=len(orders) > 50, page=page,
                   status=status, q=q, statuses=models.ORDER_STATUSES, channel=channel, channels=channels,
                   now=datetime.now(timezone.utc))


@router.get("/orders/import", response_class=HTMLResponse)
async def order_import_page(request: Request):
    session = _session(request)
    channel_sync.seed_channels()
    with session_scope() as db:
        channels = db.scalars(select(models.Channel).where(models.Channel.code != "druvo.uk")).all()
    return _render(request, "order_import", session, channels=channels)


@router.post("/orders/import")
async def order_import(request: Request):
    session, form = await _post(request)
    try:
        price = catalog_admin.pence_from_form(form.get("price"), required=True, field="sale price")
        fee = catalog_admin.pence_from_form(form.get("fee"), field="marketplace fee")
        shipping = catalog_admin.pence_from_form(form.get("shipping"), field="delivery charged") or 0
        qty = catalog_admin.int_from_form(form.get("quantity"), default=1, field="quantity") or 1
        address = {k: str(form.get(k, "")).strip() for k in ("line1", "city", "postal_code") if str(form.get(k, "")).strip()}
        result = await run_in_threadpool(lambda: channel_sync.record_marketplace_sale(
            str(form.get("channel", "")), str(form.get("external_order_id", "")),
            [{"sku": str(form.get("sku", "")), "quantity": qty, "unit_price_pence": price}],
            actor=session.email, shipping_pence=shipping, marketplace_fee_pence=fee,
            buyer_name=str(form.get("buyer_name", "")), shipping_address=address))
    except (catalog_admin.CatalogEditError, channel_sync.ChannelError) as exc:
        return _redirect("/admin/orders/import", err=str(exc))
    if result.get("duplicate"):
        return _redirect(f"/admin/orders/{result['order_number']}", msg="That order was already recorded.")
    msg = "Sale recorded and stock updated everywhere."
    if result.get("conflicts"):
        msg = "Sale recorded — but it was OVERSOLD. See the warning on the order."
    return _redirect(f"/admin/orders/{result['order_number']}", msg=msg)


@router.get("/orders/{number}", response_class=HTMLResponse)
async def order_detail(request: Request, number: str):
    session = _session(request)
    with session_scope() as db:
        order = db.scalar(select(models.Order).where(models.Order.order_number == number))
        if order is None:
            raise HTTPException(status_code=404)
        refunds = db.scalars(select(models.Refund).where(models.Refund.order_id == order.id)).all()
        history = db.scalars(select(models.AuditLog).where(models.AuditLog.entity == "order", models.AuditLog.entity_id == number)
                             .order_by(models.AuditLog.created_at.desc())).all()
        cogs = sum(i.unit_cost_pence * i.quantity for i in order.items)
        profit = (order.total_pence - order.refunded_pence - (order.payment_fee_pence or 0) - order.marketplace_fee_pence
                  - order.postage_cost_pence - order.packaging_cost_pence - (0 if order.refunded_pence >= order.total_pence else cogs))
    return _render(request, "order_detail", session, order=order, refunds=refunds, history=history, cogs=cogs,
                   profit=profit, carriers=["Royal Mail", "Evri", "DPD", "Parcelforce", "InPost", "Yodel", "Other"])


async def _order_action(request: Request, number: str, fn, ok: str):
    session, form = await _post(request)
    try:
        await run_in_threadpool(fn, session, form)
    except (order_ops.OrderOpError, catalog_admin.CatalogEditError) as exc:
        return _redirect(f"/admin/orders/{number}", err=str(exc))
    except Exception:
        logger.exception("Admin order action failed for %s", number)
        return _redirect(f"/admin/orders/{number}", err="Something went wrong — nothing was changed. Try again.")
    return _redirect(f"/admin/orders/{number}", msg=ok)


@router.post("/orders/{number}/packed")
async def order_packed(request: Request, number: str):
    return await _order_action(request, number, lambda s, f: order_ops.mark_packed(number, actor=s.email), "Marked as packed.")


@router.post("/orders/{number}/dispatch")
async def order_dispatch(request: Request, number: str):
    def run(s, f):
        carrier = str(f.get("carrier", ""))
        if carrier == "Other":
            carrier = str(f.get("carrier_other", "")).strip() or "Other"
        order_ops.mark_dispatched(number, carrier=carrier, tracking_number=str(f.get("tracking_number", "")),
                                  tracking_url=str(f.get("tracking_url", "")), actor=s.email)
        _save_costs(number, f, s.email)
    return await _order_action(request, number, run, "Dispatched — the customer has been emailed.")


@router.post("/orders/{number}/delivered")
async def order_delivered(request: Request, number: str):
    return await _order_action(request, number, lambda s, f: order_ops.mark_delivered(number, actor=s.email), "Marked as delivered.")


@router.post("/orders/{number}/refund")
async def order_refund(request: Request, number: str):
    def run(s, f):
        if not f.get("confirm"):
            raise order_ops.OrderOpError("Tick the confirmation box to issue the refund.")
        amount = catalog_admin.pence_from_form(f.get("amount"), field="amount")
        order_ops.refund_order(number, amount_pence=amount, reason=str(f.get("reason", ""))[:300],
                               restock=bool(f.get("restock")), actor=s.email)
    return await _order_action(request, number, run, "Refund issued — the customer has been emailed.")


def _save_costs(number: str, form, actor: str) -> None:
    postage = catalog_admin.pence_from_form(form.get("postage_cost"), field="postage cost")
    packaging = catalog_admin.pence_from_form(form.get("packaging_cost"), field="packaging cost")
    with session_scope() as db:
        order = db.scalar(select(models.Order).where(models.Order.order_number == number))
        if postage is not None:
            order.postage_cost_pence = postage
        if packaging is not None:
            order.packaging_cost_pence = packaging
        audit(db, actor, "order.costs_updated", "order", number, postage=postage, packaging=packaging)


@router.post("/orders/{number}/costs")
async def order_costs(request: Request, number: str):
    return await _order_action(request, number, lambda s, f: _save_costs(number, f, s.email), "Costs saved.")


@router.post("/orders/{number}/note")
async def order_note(request: Request, number: str):
    def run(s, f):
        note = str(f.get("note", "")).strip()[:1000]
        if note:
            with session_scope() as db:
                audit(db, s.email, "order.note", "order", number, note=note)
    return await _order_action(request, number, run, "Note added.")


@router.get("/orders.csv")
async def orders_csv(request: Request):
    _session(request)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["order", "paid_at", "status", "channel", "customer", "items", "subtotal", "discount", "shipping",
                     "total", "refunded", "stripe_fee", "postage_cost", "packaging_cost", "item_cost"])
    with session_scope() as db:
        for o in db.scalars(select(models.Order).where(models.Order.paid_at.is_not(None)).order_by(models.Order.paid_at)):
            writer.writerow([o.order_number, o.paid_at.isoformat(), o.status, o.channel, o.name,
                             sum(i.quantity for i in o.items), *(f"{v / 100:.2f}" for v in (
                                 o.subtotal_pence, o.discount_pence, o.shipping_pence, o.total_pence, o.refunded_pence,
                                 o.payment_fee_pence or 0, o.postage_cost_pence, o.packaging_cost_pence,
                                 sum(i.unit_cost_pence * i.quantity for i in o.items)))])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="druvo-orders.csv"'})


# ====================================================================== products


@router.get("/products", response_class=HTMLResponse)
async def products_list(request: Request, q: str = "", status: str = ""):
    session = _session(request)
    with session_scope() as db:
        query = select(models.Product).order_by(models.Product.updated_at.desc())
        if status:
            query = query.where(models.Product.status == status)
        if q.strip():
            like = f"%{q.strip().lower()}%"
            query = query.where(or_(func.lower(models.Product.name).like(like), func.lower(models.Product.brand).like(like)))
        products = db.scalars(query.limit(200)).unique().all()
    return _render(request, "products", session, products=products, q=q, status=status)


def _product_form_context(product_id: int | None):
    with session_scope() as db:
        product = db.get(models.Product, product_id) if product_id else None
        if product_id and product is None:
            raise HTTPException(status_code=404)
        categories = db.scalars(select(models.Category).order_by(models.Category.sort_order)).all()
        sold = {}
        if product:
            for v in product.variants:
                sold[v.id] = int(db.scalar(select(func.coalesce(func.sum(models.OrderItem.quantity), 0))
                                           .where(models.OrderItem.variant_id == v.id)) or 0)
        channels = db.scalars(select(models.Channel).where(models.Channel.enabled.is_(True))
                              .order_by(models.Channel.id)).all() if product else []
        listings = {}
        if product:
            for row in db.scalars(select(models.ChannelListing).where(
                    models.ChannelListing.variant_id.in_([v.id for v in product.variants] or [0]))).all():
                listings[(row.variant_id, row.channel_code)] = row
        return {"product": product, "categories": categories, "conditions": catalog_admin.CONDITIONS,
                "statuses": catalog_admin.STATUSES, "sold": sold, "channels": channels, "listings": listings,
                "listing_statuses": models.LISTING_STATUSES}


@router.get("/products/new", response_class=HTMLResponse)
async def product_new(request: Request):
    session = _session(request)
    return _render(request, "product_edit", session, **_product_form_context(None))


@router.get("/products/{product_id}", response_class=HTMLResponse)
async def product_edit(request: Request, product_id: int):
    session = _session(request)
    await run_in_threadpool(channel_sync.seed_channels)
    return _render(request, "product_edit", session, **_product_form_context(product_id))


def _form_to_product(form) -> dict:
    data = {k: form.get(k) for k in ("name", "slug", "description", "brand", "condition", "category", "status", "gtin",
                                     "mpn", "tags", "is_new_arrival", "is_on_sale", "sale_price")}
    variants = []
    for i in range(int(form.get("variant_count", 0) or 0) + 1):
        variants.append({k: form.get(f"v{i}_{k}") for k in ("id", "sku", "size", "colour", "price", "cost", "stock", "threshold")})
    data["variants"] = variants
    return data


@router.post("/products/new")
async def product_create(request: Request):
    session, form = await _post(request)
    try:
        product_id = await run_in_threadpool(lambda: catalog_admin.save_product(_form_to_product(form), actor=session.email))
    except catalog_admin.CatalogEditError as exc:
        return _redirect("/admin/products/new", err=str(exc))
    return _redirect(f"/admin/products/{product_id}", msg="Product created. Add photos below.")


@router.post("/products/{product_id}")
async def product_update(request: Request, product_id: int):
    session, form = await _post(request)
    try:
        await run_in_threadpool(lambda: catalog_admin.save_product(_form_to_product(form), actor=session.email, product_id=product_id))
    except catalog_admin.CatalogEditError as exc:
        return _redirect(f"/admin/products/{product_id}", err=str(exc))
    return _redirect(f"/admin/products/{product_id}", msg="Saved.")


@router.post("/products/{product_id}/images")
async def product_image_upload(request: Request, product_id: int):
    session, form = await _post(request)
    upload = form.get("photo")
    data = await upload.read() if hasattr(upload, "read") else b""
    try:
        await run_in_threadpool(lambda: catalog_admin.add_image(product_id, data, alt=str(form.get("alt", "")), actor=session.email))
    except catalog_admin.CatalogEditError as exc:
        return _redirect(f"/admin/products/{product_id}", err=str(exc))
    return _redirect(f"/admin/products/{product_id}", msg="Photo added.")


@router.post("/products/{product_id}/images/{image_id}/delete")
async def product_image_delete(request: Request, product_id: int, image_id: int):
    session, _ = await _post(request)
    try:
        await run_in_threadpool(lambda: catalog_admin.delete_image(product_id, image_id, actor=session.email))
    except catalog_admin.CatalogEditError as exc:
        return _redirect(f"/admin/products/{product_id}", err=str(exc))
    return _redirect(f"/admin/products/{product_id}", msg="Photo removed.")


@router.post("/products/{product_id}/images/{image_id}/first")
async def product_image_first(request: Request, product_id: int, image_id: int):
    session, _ = await _post(request)
    await run_in_threadpool(lambda: catalog_admin.move_image_first(product_id, image_id, actor=session.email))
    return _redirect(f"/admin/products/{product_id}", msg="Main photo updated.")


@router.post("/products/{product_id}/variants/{variant_id}/delete")
async def product_variant_delete(request: Request, product_id: int, variant_id: int):
    session, _ = await _post(request)
    try:
        await run_in_threadpool(lambda: catalog_admin.delete_variant(product_id, variant_id, actor=session.email))
    except catalog_admin.CatalogEditError as exc:
        return _redirect(f"/admin/products/{product_id}", err=str(exc))
    return _redirect(f"/admin/products/{product_id}", msg="Variant deleted.")


# ====================================================================== customers


@router.get("/customers", response_class=HTMLResponse)
async def customers_list(request: Request, q: str = ""):
    session = _session(request)
    with session_scope() as db:
        stats = (
            select(models.Order.email, func.count(models.Order.id).label("orders"),
                   func.coalesce(func.sum(models.Order.total_pence - models.Order.refunded_pence), 0).label("spent"),
                   func.max(models.Order.paid_at).label("last"))
            .where(models.Order.paid_at.is_not(None)).group_by(models.Order.email).subquery()
        )
        query = (select(models.Customer, stats.c.orders, stats.c.spent, stats.c.last)
                 .join(stats, stats.c.email == models.Customer.email, isouter=True)
                 .order_by(models.Customer.created_at.desc()))
        if q.strip():
            like = f"%{q.strip().lower()}%"
            query = query.where(or_(func.lower(models.Customer.email).like(like), func.lower(models.Customer.name).like(like)))
        rows = db.execute(query.limit(200)).all()
    return _render(request, "customers", session, rows=rows, q=q)


@router.get("/customers/{customer_id}", response_class=HTMLResponse)
async def customer_detail(request: Request, customer_id: int):
    session = _session(request)
    with session_scope() as db:
        customer = db.get(models.Customer, customer_id)
        if customer is None:
            raise HTTPException(status_code=404)
        orders = db.scalars(select(models.Order).where(models.Order.email == customer.email,
                                                       models.Order.status != "pending_payment")
                            .order_by(models.Order.created_at.desc())).all()
    return _render(request, "customer_detail", session, customer=customer, orders=orders)


@router.get("/customers/{customer_id}/export.json")
async def customer_export(request: Request, customer_id: int):
    session = _session(request)
    data = await run_in_threadpool(catalog_admin.export_customer, customer_id)
    with session_scope() as db:
        audit(db, session.email, "customer.exported", "customer", customer_id)
    return Response(json.dumps(data, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="customer-{customer_id}.json"'})


@router.post("/customers/{customer_id}/erase")
async def customer_erase(request: Request, customer_id: int):
    session, form = await _post(request)
    if str(form.get("confirm", "")).strip().upper() != "ERASE":
        return _redirect(f"/admin/customers/{customer_id}", err="Type ERASE to confirm.")
    try:
        await run_in_threadpool(lambda: catalog_admin.anonymise_customer(customer_id, actor=session.email))
    except catalog_admin.CatalogEditError as exc:
        return _redirect(f"/admin/customers/{customer_id}", err=str(exc))
    return _redirect("/admin/customers", msg="Customer's personal data erased. Order records kept for accounting.")


# ====================================================================== promotions


@router.get("/promotions", response_class=HTMLResponse)
async def promotions_page(request: Request):
    session = _session(request)
    with session_scope() as db:
        promos = db.scalars(select(models.Promotion).order_by(models.Promotion.created_at.desc())).all()
    return _render(request, "promotions", session, promos=promos)


def _parse_date(value) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).replace(tzinfo=reporting.LONDON).astimezone(timezone.utc)
    except ValueError as exc:
        raise catalog_admin.CatalogEditError("Dates must look like 2026-12-01") from exc


@router.post("/promotions")
async def promotion_create(request: Request):
    session, form = await _post(request)
    try:
        code = str(form.get("code", "")).strip().upper()
        if not code.replace("-", "").isalnum() or not 3 <= len(code) <= 30:
            raise catalog_admin.CatalogEditError("Code must be 3–30 letters/numbers, e.g. WINTER10.")
        dtype = str(form.get("discount_type", "percent"))
        if dtype == "percent":
            value = catalog_admin.int_from_form(form.get("value"), field="percentage")
            if not 1 <= value <= 90:
                raise catalog_admin.CatalogEditError("Percentage must be between 1 and 90.")
        else:
            dtype = "fixed"
            value = catalog_admin.pence_from_form(form.get("value"), required=True, field="amount")
        limit_raw = str(form.get("usage_limit", "")).strip()
        with session_scope() as db:
            if db.scalar(select(models.Promotion).where(models.Promotion.code == code)):
                raise catalog_admin.CatalogEditError("That code already exists.")
            db.add(models.Promotion(
                name=str(form.get("name", "")).strip()[:200] or code, code=code, discount_type=dtype, discount_value=value,
                min_spend_pence=catalog_admin.pence_from_form(form.get("min_spend"), field="minimum spend") or 0,
                starts_at=_parse_date(form.get("starts_at")), ends_at=_parse_date(form.get("ends_at")),
                usage_limit=int(limit_raw) if limit_raw.isdigit() else None, active=True,
                description=str(form.get("description", "")).strip()[:500]))
            audit(db, session.email, "promotion.created", "promotion", code, type=dtype, value=value)
    except catalog_admin.CatalogEditError as exc:
        return _redirect("/admin/promotions", err=str(exc))
    return _redirect("/admin/promotions", msg=f"Discount code {code} created.")


@router.post("/promotions/{promo_id}/toggle")
async def promotion_toggle(request: Request, promo_id: int):
    session, _ = await _post(request)
    with session_scope() as db:
        promo = db.get(models.Promotion, promo_id)
        if promo is None:
            raise HTTPException(status_code=404)
        promo.active = not promo.active
        audit(db, session.email, "promotion.toggled", "promotion", promo.code, active=promo.active)
    return _redirect("/admin/promotions", msg="Updated.")


# ====================================================================== reports & expenses


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, by: str = "day"):
    session = _session(request)
    if by not in ("day", "week", "month", "year"):
        by = "day"
    count = {"day": 14, "week": 12, "month": 12, "year": 3}[by]
    rows = await run_in_threadpool(reporting.breakdown, by, count)
    start, end, label = reporting.period_bounds("year")
    year = await run_in_threadpool(reporting.totals_between, start, end)
    best = await run_in_threadpool(reporting.best_sellers, start, end)
    stock_value = await run_in_threadpool(reporting.inventory_value)
    return _render(request, "reports", session, rows=rows, by=by, year=year, best=best, stock_value=stock_value)


@router.get("/reports.csv")
async def reports_csv(request: Request, by: str = "month"):
    """Accounting summary (one row per period) — for your accountant / Self Assessment / Corporation Tax prep."""
    _session(request)
    if by not in ("day", "week", "month", "year"):
        by = "month"
    rows = await run_in_threadpool(reporting.breakdown, by, {"day": 31, "week": 26, "month": 24, "year": 5}[by])
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["period", "orders", "sales", "refunds", "net_sales", "delivery_charged", "discounts", "item_cost",
                "payment_fees", "marketplace_fees", "postage", "packaging", "expenses", "net_profit",
                "orders_with_estimated_fees"])
    for label, t in rows:
        w.writerow([label, t.orders, *(f"{v / 100:.2f}" for v in (
            t.gross_pence, t.refunds_pence, t.net_sales_pence, t.shipping_charged_pence, t.discounts_pence, t.cogs_pence,
            t.payment_fees_pence, t.marketplace_fees_pence, t.postage_pence, t.packaging_pence, t.expenses_pence,
            t.profit_pence)), t.estimated_fee_orders + t.fees_unknown])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="druvo-summary-by-{by}.csv"'})


@router.get("/expenses", response_class=HTMLResponse)
async def expenses_page(request: Request):
    session = _session(request)
    with session_scope() as db:
        expenses = db.scalars(select(models.Expense).order_by(models.Expense.spent_on.desc()).limit(200)).all()
    return _render(request, "expenses", session, expenses=expenses,
                   categories=["Stock purchase", "Packaging", "Postage supplies", "Software & hosting", "Marketing",
                               "Marketplace subscription", "Other"],
                   today=datetime.now(reporting.LONDON).date().isoformat())


@router.post("/expenses")
async def expense_create(request: Request):
    session, form = await _post(request)
    try:
        amount = catalog_admin.pence_from_form(form.get("amount"), required=True, field="amount")
        spent_on = _parse_date(form.get("spent_on")) or datetime.now(timezone.utc)
        with session_scope() as db:
            db.add(models.Expense(spent_on=spent_on, category=str(form.get("category", "Other"))[:60],
                                  description=str(form.get("description", ""))[:300], amount_pence=amount,
                                  created_by=session.email))
            audit(db, session.email, "expense.added", "expense", "", amount_pence=amount)
    except catalog_admin.CatalogEditError as exc:
        return _redirect("/admin/expenses", err=str(exc))
    return _redirect("/admin/expenses", msg="Expense recorded.")


@router.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request):
    session = _session(request)
    with session_scope() as db:
        entries = db.scalars(select(models.AuditLog).order_by(models.AuditLog.created_at.desc()).limit(200)).all()
    return _render(request, "activity", session, entries=entries)


# ====================================================================== public media


@media_router.get("/media/{image_id}.jpg")
async def media(image_id: int):
    if not get_settings().database_enabled:
        raise HTTPException(status_code=404)
    found = await run_in_threadpool(catalog_admin.get_image_bytes, image_id)
    if found is None:
        raise HTTPException(status_code=404)
    data, content_type = found
    return Response(data, media_type=content_type, headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ====================================================================== multichannel


@router.post("/listings")
async def listing_update(request: Request):
    session, form = await _post(request)
    product_id = str(form.get("product_id", ""))
    back = f"/admin/products/{product_id}" if product_id.isdigit() else str(form.get("back", "/admin/tasks"))
    if not back.startswith("/admin/"):
        back = "/admin/tasks"
    try:
        price_raw = str(form.get("price", "")).strip()
        price = catalog_admin.pence_from_form(price_raw, field="platform price") if price_raw else None
        url = str(form.get("external_url", "")).strip()
        await run_in_threadpool(lambda: channel_sync.upsert_listing(
            int(form.get("variant_id", 0)), str(form.get("channel", "")), actor=session.email,
            status=str(form.get("status", "")) or None, price_pence=price,
            external_url=url if url else None,
            external_listing_id=str(form.get("external_listing_id", "")).strip() or None))
    except (catalog_admin.CatalogEditError, channel_sync.ChannelError, ValueError) as exc:
        return _redirect(back, err=str(exc))
    return _redirect(back, msg="Listing updated.")


@router.get("/products/{product_id}/pack/{channel}", response_class=HTMLResponse)
async def listing_pack(request: Request, product_id: int, channel: str):
    """Assisted listing: everything needed to list by hand on Vinted/Depop (or any platform), ready to copy."""
    session = _session(request)
    with session_scope() as db:
        product = db.get(models.Product, product_id)
        if product is None:
            raise HTTPException(status_code=404)
        ch = db.scalar(select(models.Channel).where(models.Channel.code == channel))
        if ch is None:
            raise HTTPException(status_code=404)
        listings = {row.variant_id: row for row in db.scalars(select(models.ChannelListing).where(
            models.ChannelListing.channel_code == channel,
            models.ChannelListing.variant_id.in_([v.id for v in product.variants] or [0]))).all()}
    title_limit = {"ebay": 80}.get(channel, 0)
    title = product.name if not title_limit else product.name[:title_limit]
    base = get_settings().public_site_url.rstrip("/")
    return _render(request, "listing_pack", session, product=product, channel=ch, listings=listings, title=title,
                   title_limit=title_limit, base=base)


@router.get("/inventory", response_class=HTMLResponse)
async def inventory_page(request: Request, q: str = "", show: str = "live"):
    session = _session(request)
    with session_scope() as db:
        query = (select(models.Variant, models.Product).join(models.Product, models.Variant.product_id == models.Product.id)
                 .order_by(models.Product.name))
        if show == "live":
            query = query.where(models.Product.status == "live")
        if q.strip():
            like = f"%{q.strip().lower()}%"
            query = query.where(or_(func.lower(models.Product.name).like(like), func.lower(models.Variant.sku).like(like)))
        rows = []
        cost_value = retail_value = units = 0
        listed = {}
        for listing in db.scalars(select(models.ChannelListing).where(
                models.ChannelListing.status.in_(("published", "pending", "needs_attention", "failed")))).all():
            listed.setdefault(listing.variant_id, []).append(listing)
        for variant, product in db.execute(query.limit(1000)).all():
            reserved = inventory.reserved_quantity(db, variant.id)
            rows.append({"v": variant, "p": product, "reserved": reserved, "listings": listed.get(variant.id, [])})
            units += variant.stock_quantity
            cost_value += variant.stock_quantity * variant.cost_pence
            retail_value += variant.stock_quantity * variant.price_pence
    return _render(request, "inventory", session, rows=rows, q=q, show=show, units=units,
                   cost_value=cost_value, retail_value=retail_value)


@router.get("/inventory/{variant_id}", response_class=HTMLResponse)
async def stock_history(request: Request, variant_id: int):
    session = _session(request)
    with session_scope() as db:
        variant = db.get(models.Variant, variant_id)
        if variant is None:
            raise HTTPException(status_code=404)
        product = variant.product
        moves = db.scalars(select(models.StockMovement).where(models.StockMovement.variant_id == variant_id)
                           .order_by(models.StockMovement.id.desc()).limit(300)).all()
    return _render(request, "stock_history", session, variant=variant, product=product, moves=moves)


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(request: Request):
    session = _session(request)
    tasks = await run_in_threadpool(channel_sync.open_tasks)
    with session_scope() as db:
        low = reporting.low_stock(50)
        names = {c.code: c.name for c in db.scalars(select(models.Channel)).all()}
    return _render(request, "tasks", session, low=low, names=names, listing_statuses=models.LISTING_STATUSES,
                   now=datetime.now(timezone.utc), **tasks)


@router.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request):
    session = _session(request)
    await run_in_threadpool(channel_sync.seed_channels)
    with session_scope() as db:
        channels = db.scalars(select(models.Channel).order_by(models.Channel.id)).all()
        counts = dict(db.execute(select(models.ChannelListing.channel_code, func.count(models.ChannelListing.id))
                                 .where(models.ChannelListing.status == "published")
                                 .group_by(models.ChannelListing.channel_code)).all())
        pending_manager = db.scalar(select(func.count(models.OutboxEvent.id)).where(
            models.OutboxEvent.consumer == "manager", models.OutboxEvent.status == "pending")) or 0
    return _render(request, "channels", session, channels=channels, counts=counts, pending_manager=pending_manager,
                   manager_api_ready=len(get_settings().manager_api_key.strip()) >= 32)


@router.post("/channels/{code}")
async def channel_update(request: Request, code: str):
    session, form = await _post(request)
    try:
        pct = str(form.get("fee_percent", "0")).strip() or "0"
        bp = round(float(pct) * 100)
        if not 0 <= bp <= 5000:
            raise catalog_admin.CatalogEditError("Fee percentage must be between 0 and 50.")
        fixed = catalog_admin.pence_from_form(form.get("fee_fixed"), field="fixed fee") or 0
        days = catalog_admin.int_from_form(form.get("dispatch_days"), default=2, field="dispatch days")
        with session_scope() as db:
            ch = channel_sync.get_channel(db, code)
            ch.fee_percent_bp, ch.fee_fixed_pence, ch.dispatch_days = bp, fixed, days
            ch.enabled = bool(form.get("enabled"))
            audit(db, session.email, "channel.updated", "channel", code, fee_bp=bp, fee_fixed=fixed, enabled=ch.enabled)
    except (ValueError, catalog_admin.CatalogEditError, channel_sync.ChannelError) as exc:
        return _redirect("/admin/channels", err=str(exc))
    return _redirect("/admin/channels", msg="Platform settings saved.")

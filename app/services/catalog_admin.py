"""Admin catalogue editing: products, variants (price, cost, stock), photos; customers (GDPR)."""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select

from app.db import models
from app.db.base import session_scope
from app.services.db_checkout import enqueue_outbox
from app.services import inventory
from app.services.order_ops import audit

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_EDGE = 1600
CONDITIONS = ["New with tags", "New", "Pre-loved – Excellent", "Pre-loved – Very good", "Pre-loved – Good"]
STATUSES = ["draft", "live", "archived"]


class CatalogEditError(ValueError):
    pass


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:180] or "product"


def pence_from_form(value: Any, *, required: bool = False, field: str = "price") -> int | None:
    raw = str(value or "").strip().replace("£", "").replace(",", "")
    if not raw:
        if required:
            raise CatalogEditError(f"{field.capitalize()} is required.")
        return None
    try:
        amount = round(float(raw) * 100)
    except ValueError as exc:
        raise CatalogEditError(f"{field.capitalize()} must be a number, e.g. 19.99") from exc
    if amount < 0:
        raise CatalogEditError(f"{field.capitalize()} can't be negative.")
    return int(amount)


def int_from_form(value: Any, default: int = 0, *, field: str = "value") -> int:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        number = int(raw)
    except ValueError as exc:
        raise CatalogEditError(f"{field.capitalize()} must be a whole number.") from exc
    if number < 0:
        raise CatalogEditError(f"{field.capitalize()} can't be negative.")
    return number


def _unique_slug(db, base: str, exclude_id: int | None = None) -> str:
    slug, n = base, 2
    while True:
        q = select(models.Product.id).where(models.Product.slug == slug)
        if exclude_id:
            q = q.where(models.Product.id != exclude_id)
        if db.scalar(q) is None:
            return slug
        slug = f"{base}-{n}"
        n += 1


def save_product(form: dict, *, actor: str, product_id: int | None = None) -> int:
    """Create or update a product and its variants from the admin form."""
    name = (form.get("name") or "").strip()
    if len(name) < 3:
        raise CatalogEditError("Product name is required.")
    status = form.get("status") or "draft"
    if status not in STATUSES:
        raise CatalogEditError("Unknown status.")
    variants_in = form.get("variants") or []
    clean_variants = []
    for v in variants_in:
        sku = (v.get("sku") or "").strip().upper()
        if not sku and not (v.get("price") or "").strip():
            continue  # empty "add variant" row
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-_.]{1,60}", sku or ""):
            raise CatalogEditError("Each variant needs a SKU (letters, numbers, dashes).")
        clean_variants.append(
            {
                "id": int(v["id"]) if str(v.get("id") or "").isdigit() else None,
                "sku": sku,
                "size": (v.get("size") or "").strip()[:60],
                "colour": (v.get("colour") or "").strip()[:60],
                "price_pence": pence_from_form(v.get("price"), required=True, field="price"),
                "cost_pence": pence_from_form(v.get("cost"), field="cost") or 0,
                "stock_quantity": int_from_form(v.get("stock"), field="stock"),
                "low_stock_threshold": int_from_form(v.get("threshold"), default=1, field="low-stock alert"),
            }
        )
    if status == "live" and not clean_variants:
        raise CatalogEditError("A live product needs at least one variant with a price.")

    with session_scope() as db:
        if product_id is None:
            product = models.Product(external_id=f"web-{datetime.now(timezone.utc):%Y%m%d%H%M%S%f}", slug="tmp", name=name)
            db.add(product)
            db.flush()
            product.external_id = f"web-{product.id}"
        else:
            product = db.get(models.Product, product_id)
            if product is None:
                raise CatalogEditError("Product not found.")
        before = {v.sku: v.stock_quantity for v in product.variants}
        product.name = name[:300]
        wanted_slug = slugify(form.get("slug") or name)
        product.slug = _unique_slug(db, wanted_slug, product.id)
        product.description = (form.get("description") or "").strip()
        product.brand = (form.get("brand") or "").strip()[:200]
        product.condition = (form.get("condition") or "").strip()[:100]
        product.gtin = (form.get("gtin") or "").strip()[:50]
        product.mpn = (form.get("mpn") or "").strip()[:100]
        product.tags = [t.strip() for t in (form.get("tags") or "").split(",") if t.strip()][:20]
        product.is_new_arrival = bool(form.get("is_new_arrival"))
        product.is_on_sale = bool(form.get("is_on_sale"))
        product.sale_price_pence = pence_from_form(form.get("sale_price"), field="sale price")
        if product.is_on_sale and not product.sale_price_pence:
            raise CatalogEditError("Enter a sale price or untick 'On sale'.")
        category_slug = form.get("category") or ""
        product.category = (
            db.scalar(select(models.Category).where(models.Category.slug == category_slug)) if category_slug else None
        )
        product.status = status

        existing = {v.id: v for v in product.variants}
        for cv in clean_variants:
            clash = db.scalar(select(models.Variant).where(models.Variant.sku == cv["sku"]))
            if clash is not None and clash.id != cv["id"]:
                raise CatalogEditError(f"SKU {cv['sku']} is already used by another product.")
            variant = existing.get(cv["id"]) if cv["id"] else None
            if variant is None:
                variant = models.Variant(sku=cv["sku"], price_pence=0)
                product.variants.append(variant)
            for key in ("sku", "size", "colour", "price_pence", "cost_pence", "low_stock_threshold"):
                setattr(variant, key, cv[key])
            if variant.id is None:
                variant.stock_quantity = 0
                db.flush()
            inventory.set_stock(db, variant, cv["stock_quantity"], actor=actor)
        db.flush()
        after = {v.sku: v.stock_quantity for v in product.variants}
        changes = {sku: [before.get(sku), qty] for sku, qty in after.items() if before.get(sku) != qty}
        audit(db, actor, "product.created" if product_id is None else "product.updated", "product", product.id,
              name=product.name, status=status, stock_changes=changes)
        enqueue_outbox(db, "product.updated", {"product_id": product.id, "slug": product.slug, "status": status})
        if changes:
            enqueue_outbox(db, "stock.adjusted", {"product_id": product.id, "changes": changes, "by": actor})
        return product.id


def delete_variant(product_id: int, variant_id: int, *, actor: str) -> None:
    with session_scope() as db:
        variant = db.get(models.Variant, variant_id)
        if variant is None or variant.product_id != product_id:
            raise CatalogEditError("Variant not found.")
        sold = db.scalar(select(func.count(models.OrderItem.id)).where(models.OrderItem.variant_id == variant_id))
        if sold:
            raise CatalogEditError("This variant has orders — set its stock to 0 instead of deleting it.")
        audit(db, actor, "variant.deleted", "product", product_id, sku=variant.sku)
        db.delete(variant)


def add_image(product_id: int, upload: bytes, *, alt: str, actor: str) -> int:
    if not upload:
        raise CatalogEditError("Choose a photo to upload.")
    if len(upload) > MAX_UPLOAD_BYTES:
        raise CatalogEditError("Photo is larger than 10 MB.")
    try:
        image = Image.open(io.BytesIO(upload))
        image.verify()
        image = Image.open(io.BytesIO(upload))
    except (UnidentifiedImageError, OSError) as exc:
        raise CatalogEditError("That file isn't a supported photo (JPEG, PNG or WebP).") from exc
    if image.format not in ("JPEG", "PNG", "WEBP", "MPO"):
        raise CatalogEditError("Upload a JPEG, PNG or WebP photo.")
    # Re-encode: applies phone rotation, strips EXIF (incl. GPS location), resizes for fast pages.
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85, optimize=True, progressive=True)
    with session_scope() as db:
        product = db.get(models.Product, product_id)
        if product is None:
            raise CatalogEditError("Product not found.")
        row = models.ProductImage(
            url="pending", alt=(alt or product.name)[:300], position=len(product.images),
            data=out.getvalue(), content_type="image/jpeg",
        )
        product.images.append(row)
        db.flush()
        row.url = f"/media/{row.id}.jpg"
        audit(db, actor, "image.added", "product", product_id, image_id=row.id)
        return row.id


def delete_image(product_id: int, image_id: int, *, actor: str) -> None:
    with session_scope() as db:
        row = db.get(models.ProductImage, image_id)
        if row is None or row.product_id != product_id:
            raise CatalogEditError("Photo not found.")
        db.delete(row)
        audit(db, actor, "image.deleted", "product", product_id, image_id=image_id)


def move_image_first(product_id: int, image_id: int, *, actor: str) -> None:
    with session_scope() as db:
        product = db.get(models.Product, product_id)
        images = sorted(product.images, key=lambda i: (i.id != image_id, i.position))
        for pos, img in enumerate(images):
            img.position = pos
        audit(db, actor, "image.reordered", "product", product_id, first=image_id)


def get_image_bytes(image_id: int) -> tuple[bytes, str] | None:
    with session_scope() as db:
        row = db.execute(
            select(models.ProductImage.data, models.ProductImage.content_type).where(models.ProductImage.id == image_id)
        ).first()
        if row is None or row[0] is None:
            return None
        return bytes(row[0]), row[1] or "image/jpeg"


# ------------------------------------------------------------------ customers (UK GDPR)


def export_customer(customer_id: int) -> dict:
    """Subject access request: everything we hold about one customer."""
    with session_scope() as db:
        c = db.get(models.Customer, customer_id)
        if c is None:
            raise CatalogEditError("Customer not found.")
        orders = db.scalars(select(models.Order).where(models.Order.email == c.email)).all()
        return {
            "customer": {"email": c.email, "name": c.name, "phone": c.phone, "marketing_opt_in": c.marketing_opt_in,
                         "created_at": c.created_at.isoformat()},
            "orders": [
                {
                    "order_number": o.order_number, "status": o.status, "placed": o.created_at.isoformat(),
                    "total_gbp": o.total_pence / 100, "shipping_address": o.shipping_address, "phone": o.phone,
                    "items": [{"name": i.product_name, "sku": i.sku, "quantity": i.quantity,
                               "unit_price_gbp": i.unit_price_pence / 100} for i in o.items],
                    "tracking_number": o.tracking_number,
                }
                for o in orders
            ],
        }


def anonymise_customer(customer_id: int, *, actor: str) -> int:
    """Right to erasure: remove personal data but keep order/financial records (needed for tax law).

    Orders are kept (HMRC requires records for 6 years) with name, email, phone and address removed.
    """
    with session_scope() as db:
        c = db.get(models.Customer, customer_id)
        if c is None:
            raise CatalogEditError("Customer not found.")
        open_orders = db.scalar(
            select(func.count(models.Order.id)).where(
                models.Order.email == c.email, models.Order.status.in_(("pending_payment", "paid", "packed", "shipped"))
            )
        )
        if open_orders:
            raise CatalogEditError("This customer has orders still in progress — finish them first.")
        token = f"erased-{c.id}@deleted.invalid"
        orders = db.scalars(select(models.Order).where(models.Order.email == c.email)).all()
        for o in orders:
            o.email, o.name, o.phone, o.shipping_address = token, "Erased customer", "", {}
            o.notes = ""
        c.email, c.name, c.phone, c.marketing_opt_in = token, "Erased customer", "", False
        audit(db, actor, "customer.erased", "customer", customer_id, orders=len(orders))
        return len(orders)

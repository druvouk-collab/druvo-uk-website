"""Shop, catalog, cart, and checkout routes."""

from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.config import get_settings
from app.services.seo_service import organization_json_ld, product_json_ld, website_json_ld
from app.services.seo_metadata import (
    breadcrumb_json_ld,
    catalog_brands,
    categories_document_title,
    categories_meta_description,
    category_document_title,
    category_meta_description,
    home_document_title,
    home_meta_description,
    item_list_json_ld,
    product_breadcrumbs,
    product_document_title,
    product_meta_description,
    shop_document_title,
    shop_meta_description,
)
from app.templating import templates
from app.services.catalog_service import CatalogFilters, CatalogService

router = APIRouter()
catalog = CatalogService()


def _filter_params(
    q: str = "",
    category: str | None = None,
    size: str | None = None,
    colour: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    in_stock: bool = False,
    sort: str = "featured",
) -> CatalogFilters:
    return CatalogFilters(
        query=q.strip(),
        category_slug=category or None,
        size=size or None,
        colour=colour or None,
        min_price=min_price,
        max_price=max_price,
        in_stock_only=in_stock,
        sort=sort,
    )


async def _shop_context(request: Request, filters: CatalogFilters, page_title: str, heading: str):
    snapshot = await catalog.load_snapshot(filters)
    products = snapshot.products
    categories = snapshot.categories
    return {
        "request": request,
        "page_title": page_title,
        "heading": heading,
        "products": products,
        "categories": categories,
        "filters": filters,
        "sizes": catalog.available_sizes(products),
        "colours": catalog.available_colours(products),
        "catalog_degraded": snapshot.degraded,
        "catalog_notice": snapshot.notice,
    }


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    snapshot = await catalog.load_snapshot()
    products = snapshot.products
    categories = snapshot.categories
    new_arrivals = [p for p in products if p.is_new_arrival][:4]
    sale_items = [p for p in products if p.is_on_sale][:4]

    return templates.TemplateResponse(
        request,
        "pages/home.html",
        {
            "page_title": "Premium UK Resale",
            "document_title": home_document_title(products),
            "seo_description": home_meta_description(products),
            "catalog_brands": catalog_brands(products),
            "categories": categories,
            "new_arrivals": new_arrivals,
            "sale_items": sale_items,
            "featured": products[:6],
            "catalog_degraded": snapshot.degraded,
            "catalog_notice": snapshot.notice,
            "organization_json_ld": organization_json_ld(),
            "website_json_ld": website_json_ld(),
            "item_list_json_ld": item_list_json_ld(products[:12], "Featured products", "/"),
        },
    )


@router.get("/shop", response_class=HTMLResponse)
async def shop_page(
    request: Request,
    q: str = "",
    category: str | None = None,
    size: str | None = None,
    colour: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    in_stock: bool = False,
    sort: str = "featured",
):
    filters = _filter_params(q, category, size, colour, min_price, max_price, in_stock, sort)
    ctx = await _shop_context(request, filters, "Shop", "Shop All")
    ctx["document_title"] = shop_document_title(ctx["products"])
    ctx["seo_description"] = shop_meta_description(ctx["products"])
    ctx["item_list_json_ld"] = item_list_json_ld(ctx["products"][:12], "Shop all products", "/shop")
    return templates.TemplateResponse(request, "pages/shop.html", ctx)


@router.get("/new-arrivals", response_class=HTMLResponse)
async def new_arrivals(request: Request, sort: str = "featured"):
    filters = CatalogFilters(new_arrivals_only=True, sort=sort)
    ctx = await _shop_context(request, filters, "New Arrivals", "New Arrivals")
    ctx["document_title"] = f"New Arrivals | Shop Online UK | DRUVO UK"
    ctx["seo_description"] = shop_meta_description(ctx["products"])
    ctx["item_list_json_ld"] = item_list_json_ld(ctx["products"][:12], "New arrivals", "/new-arrivals")
    return templates.TemplateResponse(request, "pages/shop.html", ctx)


@router.get("/sale", response_class=HTMLResponse)
async def sale(request: Request, sort: str = "price-asc"):
    filters = CatalogFilters(on_sale_only=True, sort=sort)
    ctx = await _shop_context(request, filters, "Sale", "Offers & Sale")
    ctx["document_title"] = f"Sale Offers | Shop Online UK | DRUVO UK"
    ctx["seo_description"] = shop_meta_description(ctx["products"])
    ctx["item_list_json_ld"] = item_list_json_ld(ctx["products"][:12], "Sale offers", "/sale")
    return templates.TemplateResponse(request, "pages/shop.html", ctx)


@router.get("/categories", response_class=HTMLResponse)
async def categories_page(request: Request):
    categories = await catalog.list_categories()
    products = await catalog.list_products()
    return templates.TemplateResponse(
        request,
        "pages/categories.html",
        {
            "page_title": "Categories",
            "document_title": categories_document_title(),
            "seo_description": categories_meta_description(products),
            "categories": categories,
        },
    )


@router.get("/categories/{slug}", response_class=HTMLResponse)
async def category_detail(
    request: Request,
    slug: str,
    q: str = "",
    size: str | None = None,
    colour: str | None = None,
    in_stock: bool = False,
    sort: str = "featured",
):
    category = await catalog.get_category(slug)
    if not category:
        return templates.TemplateResponse(request, "pages/404.html", {"page_title": "Not found"}, status_code=404)
    filters = _filter_params(q, slug, size, colour, None, None, in_stock, sort)
    ctx = await _shop_context(request, filters, category.name, category.name)
    ctx["category"] = category
    ctx["document_title"] = category_document_title(category)
    ctx["seo_description"] = category_meta_description(category, ctx["products"])
    ctx["item_list_json_ld"] = item_list_json_ld(
        ctx["products"][:12], f"{category.name} products", f"/categories/{slug}"
    )
    return templates.TemplateResponse(request, "pages/category.html", ctx)


@router.get("/product/{slug}", response_class=HTMLResponse)
async def product_detail(request: Request, slug: str):
    product = await catalog.get_product(slug)
    if not product:
        return templates.TemplateResponse(request, "pages/404.html", {"page_title": "Not found"}, status_code=404)
    related = await catalog.list_products(CatalogFilters(category_slug=product.category_slug))
    related = [p for p in related if p.slug != slug][:4]
    default_variant = product.first_in_stock_variant()
    from app.services.seo_service import canonical_site_url

    base = canonical_site_url()
    image = product.images[0] if product.images else "/static/images/placeholder-product.svg"
    og_image_url = image if image.startswith("http") else f"{base}{image}"

    breadcrumbs = product_breadcrumbs(product)
    return templates.TemplateResponse(
        request,
        "pages/product.html",
        {
            "page_title": product.name,
            "document_title": product_document_title(product),
            "seo_description": product_meta_description(product),
            "product": product,
            "related": related,
            "breadcrumbs": breadcrumbs,
            "variants_json": json.dumps([asdict(v) for v in product.variants]),
            "default_size": default_variant.size if default_variant else "",
            "default_colour": default_variant.colour if default_variant else "",
            "product_json_ld": product_json_ld(product),
            "breadcrumb_json_ld": breadcrumb_json_ld(breadcrumbs),
            "og_image_url": og_image_url,
        },
    )


@router.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    q: str = Query("", min_length=0),
    sort: str = "featured",
):
    filters = CatalogFilters(query=q, sort=sort)
    ctx = await _shop_context(request, filters, f'Search: "{q}"' if q else "Search", "Search")
    ctx["search_query"] = q
    return templates.TemplateResponse(request, "pages/search.html", ctx)


@router.get("/cart", response_class=HTMLResponse)
async def cart_page(request: Request):
    return templates.TemplateResponse(request, "pages/cart.html", {"page_title": "Basket"})


@router.get("/checkout", response_class=HTMLResponse)
async def checkout_page(request: Request):
    settings = get_settings()
    checkout_ready = (
        settings.catalog_source == "druvo_api"
        and bool(settings.druvo_api_base_url)
        and bool(settings.druvo_api_key)
    )
    payments_enabled = settings.payments_enabled
    return templates.TemplateResponse(
        request,
        "pages/checkout.html",
        {
            "page_title": "Checkout",
            "checkout_ready": checkout_ready,
            "payments_enabled": payments_enabled,
            "stripe_publishable_key": settings.stripe_publishable_key if payments_enabled else "",
        },
    )


@router.get("/checkout/success", response_class=HTMLResponse)
async def checkout_success(request: Request, session_id: str = ""):
    from app.services.stripe_service import StripeCheckoutService

    context = {
        "page_title": "Payment successful",
        "session_id": session_id,
        "paid": False,
        "order": None,
        "external_order_id": "",
        "customer_email": "",
    }
    if session_id and get_settings().stripe_enabled:
        try:
            context.update(await StripeCheckoutService().get_success_context(session_id))
        except Exception:
            pass
    return templates.TemplateResponse(request, "pages/checkout_success.html", context)


@router.get("/checkout/cancel", response_class=HTMLResponse)
async def checkout_cancel(request: Request, external_order_id: str = ""):
    return templates.TemplateResponse(
        request,
        "pages/checkout_cancel.html",
        {"page_title": "Checkout cancelled", "external_order_id": external_order_id},
    )

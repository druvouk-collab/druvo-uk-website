"""Shop, catalog, cart, and checkout routes."""

from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.config import get_settings
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
            "categories": categories,
            "new_arrivals": new_arrivals,
            "sale_items": sale_items,
            "featured": products[:6],
            "catalog_degraded": snapshot.degraded,
            "catalog_notice": snapshot.notice,
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
    return templates.TemplateResponse(request, "pages/shop.html", ctx)


@router.get("/new-arrivals", response_class=HTMLResponse)
async def new_arrivals(request: Request, sort: str = "featured"):
    filters = CatalogFilters(new_arrivals_only=True, sort=sort)
    ctx = await _shop_context(request, filters, "New Arrivals", "New Arrivals")
    return templates.TemplateResponse(request, "pages/shop.html", ctx)


@router.get("/sale", response_class=HTMLResponse)
async def sale(request: Request, sort: str = "price-asc"):
    filters = CatalogFilters(on_sale_only=True, sort=sort)
    ctx = await _shop_context(request, filters, "Sale", "Offers & Sale")
    return templates.TemplateResponse(request, "pages/shop.html", ctx)


@router.get("/categories", response_class=HTMLResponse)
async def categories_page(request: Request):
    categories = await catalog.list_categories()
    return templates.TemplateResponse(
        request,
        "pages/categories.html",
        {"page_title": "Categories", "categories": categories},
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
    return templates.TemplateResponse(request, "pages/category.html", ctx)


@router.get("/product/{slug}", response_class=HTMLResponse)
async def product_detail(request: Request, slug: str):
    product = await catalog.get_product(slug)
    if not product:
        return templates.TemplateResponse(request, "pages/404.html", {"page_title": "Not found"}, status_code=404)
    related = await catalog.list_products(CatalogFilters(category_slug=product.category_slug))
    related = [p for p in related if p.slug != slug][:4]
    default_variant = product.first_in_stock_variant()
    return templates.TemplateResponse(
        request,
        "pages/product.html",
        {
            "page_title": product.name,
            "product": product,
            "related": related,
            "variants_json": json.dumps([asdict(v) for v in product.variants]),
            "default_size": default_variant.size if default_variant else "",
            "default_colour": default_variant.colour if default_variant else "",
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
    return templates.TemplateResponse(
        request,
        "pages/checkout.html",
        {"page_title": "Checkout", "checkout_ready": checkout_ready},
    )

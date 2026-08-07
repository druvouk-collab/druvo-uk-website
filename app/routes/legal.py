"""Legal, contact, and information pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templating import templates

router = APIRouter()


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse(request, "pages/about.html", {"page_title": "About DRUVO"})


@router.get("/contact", response_class=HTMLResponse)
async def contact(request: Request):
    return templates.TemplateResponse(request, "pages/contact.html", {"page_title": "Contact"})


@router.get("/faq", response_class=HTMLResponse)
async def faq(request: Request):
    return templates.TemplateResponse(request, "pages/faq.html", {"page_title": "FAQ"})


@router.get("/delivery", response_class=HTMLResponse)
async def delivery(request: Request):
    return templates.TemplateResponse(request, "pages/delivery.html", {"page_title": "Delivery Information"})


@router.get("/returns", response_class=HTMLResponse)
async def returns_policy(request: Request):
    return templates.TemplateResponse(request, "pages/returns.html", {"page_title": "Returns Policy"})


@router.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse(request, "pages/terms.html", {"page_title": "Terms & Conditions"})


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse(request, "pages/privacy.html", {"page_title": "Privacy Policy"})

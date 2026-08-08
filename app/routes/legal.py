"""Legal, contact, and information pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services.seo_metadata import (
    about_document_title,
    about_meta_description,
    contact_document_title,
    contact_meta_description,
    delivery_document_title,
    delivery_meta_description,
    faq_document_title,
    faq_meta_description,
    privacy_document_title,
    privacy_meta_description,
    returns_document_title,
    returns_meta_description,
    shipping_returns_document_title,
    shipping_returns_meta_description,
    terms_document_title,
    terms_meta_description,
)
from app.templating import templates

router = APIRouter()


def _legal_ctx(page_title: str, document_title: str, seo_description: str) -> dict:
    return {
        "page_title": page_title,
        "document_title": document_title,
        "seo_description": seo_description,
    }


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse(
        request,
        "pages/about.html",
        _legal_ctx("About DRUVO", about_document_title(), about_meta_description()),
    )


@router.get("/contact", response_class=HTMLResponse)
async def contact(request: Request):
    return templates.TemplateResponse(
        request,
        "pages/contact.html",
        _legal_ctx("Contact", contact_document_title(), contact_meta_description()),
    )


@router.get("/faq", response_class=HTMLResponse)
async def faq(request: Request):
    return templates.TemplateResponse(
        request,
        "pages/faq.html",
        _legal_ctx("FAQ", faq_document_title(), faq_meta_description()),
    )


@router.get("/delivery", response_class=HTMLResponse)
async def delivery(request: Request):
    return templates.TemplateResponse(
        request,
        "pages/delivery.html",
        _legal_ctx("Delivery Information", delivery_document_title(), delivery_meta_description()),
    )


@router.get("/shipping-returns", response_class=HTMLResponse)
async def shipping_returns(request: Request):
    return templates.TemplateResponse(
        request,
        "pages/shipping-returns.html",
        _legal_ctx(
            "Shipping & Returns",
            shipping_returns_document_title(),
            shipping_returns_meta_description(),
        ),
    )


@router.get("/returns", response_class=HTMLResponse)
async def returns_policy(request: Request):
    return templates.TemplateResponse(
        request,
        "pages/returns.html",
        _legal_ctx("Returns Policy", returns_document_title(), returns_meta_description()),
    )


@router.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse(
        request,
        "pages/terms.html",
        _legal_ctx("Terms & Conditions", terms_document_title(), terms_meta_description()),
    )


@router.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse(
        request,
        "pages/privacy.html",
        _legal_ctx("Privacy Policy", privacy_document_title(), privacy_meta_description()),
    )

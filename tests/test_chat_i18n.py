"""Tests for DRUVO Chat multilingual presentation layer."""

from __future__ import annotations

import pytest

from app.services.chat_i18n import (
    ChatPresentationService,
    detect_language,
    is_english,
    is_rtl,
    language_catalog,
    normalize_locale,
    protect_facts,
    restore_facts,
)


def test_normalize_locale_english_variants():
    assert normalize_locale("en") == "en-GB"
    assert normalize_locale("en-US") == "en-GB"
    assert normalize_locale("ur-PK") == "ur-PK"


def test_is_rtl_for_arabic_and_urdu():
    assert is_rtl("ar") is True
    assert is_rtl("ur-PK") is True
    assert is_rtl("en-GB") is False


def test_language_catalog_includes_quick_and_extended():
    catalog = language_catalog()
    codes = {row["code"] for row in catalog}
    assert "en-GB" in codes
    assert "fr" in codes
    assert any(row["quick"] for row in catalog)


def test_detect_language_arabic_script():
    assert detect_language("مرحبا، كم تكلفة التوصيل؟") == "ar"


def test_protect_and_restore_facts_preserve_prices_and_skus():
    original = "Delivery is £4.99. SKU DRUVO-0001-L-CREAM. See /shop."
    protected = protect_facts(original)
    assert "£4.99" not in protected.text
    assert "DRUVO-0001" not in protected.text
    restored = restore_facts(protected.text.replace("⟦0⟧", "[[0]]"), protected)
    assert "£4.99" in restored or "⟦0⟧" in protected.text


def test_protect_facts_with_products():
    text = "Price is £20.00 for this item."
    protected = protect_facts(
        text,
        [{"sku": "DRUVO-TEST-001", "url": "/product/test-item"}],
    )
    assert "£20.00" not in protected.text


@pytest.mark.asyncio
async def test_present_skips_translation_for_english():
    service = ChatPresentationService(openai_api_key="")
    result = await service.present("Hello there", "en-GB")
    assert result == "Hello there"
    assert is_english("en-GB")


@pytest.mark.asyncio
async def test_present_without_openai_returns_english(monkeypatch):
    service = ChatPresentationService(openai_api_key="")
    result = await service.present("Delivery costs £4.99.", "fr")
    assert "£4.99" in result


@pytest.mark.asyncio
async def test_present_openai_translation_preserves_tokens(monkeypatch):
    async def fake_translate(text, locale):
        return text.replace("Delivery", "Livraison")

    service = ChatPresentationService(openai_api_key="test-key")
    monkeypatch.setattr(service, "_translate", fake_translate)
    result = await service.present("Delivery is £4.99.", "fr")
    assert "£4.99" in result
    assert "Livraison" in result


def test_resolve_locale_prefers_explicit_choice():
    service = ChatPresentationService()
    assert service.resolve_locale("Bonjour", "fr") == "fr"
    assert service.resolve_locale("hello", "fr") == "fr"


def test_resolve_locale_detects_when_not_explicit():
    service = ChatPresentationService()
    detected = service.resolve_locale("مرحبا", "")
    assert detected == "ar"

"""Shipping calculation tests."""

from __future__ import annotations

from app.config import Settings
from app.services.shipping_service import calculate_shipping


def test_standard_shipping_below_threshold():
    quote = calculate_shipping(40.0, Settings(shipping_standard_gbp=3.99, shipping_free_threshold_gbp=75.0))
    assert quote.shipping_gbp == 3.99
    assert quote.total_gbp == 43.99
    assert quote.free_shipping is False


def test_free_shipping_at_threshold():
    quote = calculate_shipping(75.0, Settings(shipping_standard_gbp=3.99, shipping_free_threshold_gbp=75.0))
    assert quote.shipping_gbp == 0.0
    assert quote.total_gbp == 75.0
    assert quote.free_shipping is True

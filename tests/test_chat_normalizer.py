"""Tests for chat message normalization."""

from app.services.chat_message_normalizer import normalize_customer_message


def test_typo_tracksuit():
    assert "tracksuit" in normalize_customer_message("got any tracksut")


def test_abbreviation_delivery():
    assert "how much delivery" in normalize_customer_message("how mch delivery")


def test_have_u_got():
    normalized = normalize_customer_message("hav u got large")
    assert "do you have" in normalized or "have" in normalized

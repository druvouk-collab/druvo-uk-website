"""Live Stripe keys stay inactive until the owner explicitly confirms live mode."""

from app.config import Settings


def test_test_keys_enabled():
    assert Settings(stripe_secret_key="sk_test_x", stripe_publishable_key="pk_test_x").stripe_enabled


def test_live_keys_locked_without_confirmation():
    s = Settings(stripe_secret_key="sk_live_x", stripe_publishable_key="pk_live_x")
    assert s.stripe_mode == "live" and not s.stripe_enabled


def test_live_keys_enabled_after_confirmation():
    s = Settings(stripe_secret_key="sk_live_x", stripe_publishable_key="pk_live_x", stripe_live_mode_confirmed=True)
    assert s.stripe_enabled

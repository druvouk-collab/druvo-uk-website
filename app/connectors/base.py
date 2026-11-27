"""Connector contract every marketplace integration implements, plus listing readiness checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class ConnectorError(Exception):
    """A marketplace rejected or failed a request. ``retryable`` tells the worker whether to try again."""

    def __init__(self, message: str, *, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class PublishResult:
    external_listing_id: str
    external_url: str = ""


class Connector:
    channel_code = ""

    def __init__(self, credentials: dict) -> None:
        self.credentials = credentials

    # Listings -----------------------------------------------------------
    def publish(self, listing: dict) -> PublishResult:
        raise NotImplementedError

    def update_quantity(self, listing: dict, quantity: int) -> None:
        raise NotImplementedError

    def update_price(self, listing: dict, price_pence: int) -> None:
        raise NotImplementedError

    def end(self, listing: dict) -> None:
        raise NotImplementedError

    # Orders -------------------------------------------------------------
    def fetch_orders(self, since: datetime | None) -> list[dict]:
        """Return sales in the record_marketplace_sale shape: external_order_id, lines, fees, buyer, dispatch_by."""
        raise NotImplementedError

    def submit_tracking(self, external_order_id: str, carrier: str, tracking_number: str) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------- readiness

# Only requirements we're sure of are hard-coded; platform category/item-specific rules come with each connector.
TITLE_LIMITS = {"ebay": 80}


def readiness_problems(listing: dict, channel_code: str) -> list[str]:
    """What must be fixed before this product can be listed on the platform (empty list = ready)."""
    problems = []
    title = (listing.get("title") or "").strip()
    real_images = [i for i in listing.get("images") or [] if "placeholder" not in i]
    if len(title) < 10:
        problems.append("Add a fuller title (brand, item, colour, size).")
    limit = TITLE_LIMITS.get(channel_code)
    if limit and len(title) > limit:
        problems.append(f"Title is {len(title)} characters; {channel_code} allows {limit}.")
    if not real_images:
        problems.append("Add at least one real photo.")
    if (listing.get("price_pence") or 0) <= 0:
        problems.append("Set a price.")
    if (listing.get("quantity") or 0) <= 0:
        problems.append("Stock is 0.")
    if channel_code != "druvo.uk":
        if len((listing.get("description") or "").strip()) < 30:
            problems.append("Write a description (condition, measurements, material).")
        if not (listing.get("condition") or "").strip():
            problems.append("Choose a condition.")
        if not (listing.get("brand") or "").strip():
            problems.append("Add the brand (or 'Unbranded').")
        if not (listing.get("category") or "").strip():
            problems.append("Choose a category.")
    if channel_code == "amazon" and not (listing.get("gtin") or "").strip():
        problems.append("Amazon usually needs a barcode (GTIN/EAN) unless you have a GTIN exemption or Brand Registry.")
    return problems

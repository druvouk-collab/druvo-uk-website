"""Single source of customer-facing policy summaries for website + DRUVO Chat.

Delivery/shipping amounts are injected from Settings at runtime so chat and checkout stay aligned.
Static delivery times and returns rules mirror published pages at /delivery and /returns.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class WebsitePolicies:
    delivery_summary: str
    returns_summary: str
    payment_methods: str
    contact_email: str
    faq_url: str
    delivery_url: str
    returns_url: str
    shop_url: str
    sale_url: str
    new_arrivals_url: str


def build_website_policies(settings: Settings) -> WebsitePolicies:
    standard = settings.shipping_standard_gbp
    threshold = settings.shipping_free_threshold_gbp
    email = settings.contact_email
    return WebsitePolicies(
        delivery_summary=(
            f"Standard UK delivery: 2–4 working days — £{standard:.2f} "
            f"(free on orders over £{threshold:.2f}), dispatched within 1–2 working days. "
            "No express or international delivery at the moment (see /delivery)."
        ),
        returns_summary=(
            "You can cancel and return any item within 14 days of receiving it, for any reason. "
            f"Contact {email} with your order number to start a return. "
            "We refund the item and standard delivery within 14 days of getting it back (or proof of postage). "
            "Return postage is paid by the customer unless the item is faulty. See /returns."
        ),
        payment_methods=(
            f"We take orders by email at {email}. We'll reply to confirm stock, the delivery cost "
            "and how to pay before we accept your order. No payment is taken on this website."
            if settings.email_orders_enabled
            else "Secure card payments via Stripe at checkout."
        ),
        contact_email=email,
        faq_url="/faq",
        delivery_url="/delivery",
        returns_url="/returns",
        shop_url="/shop",
        sale_url="/sale",
        new_arrivals_url="/shop?sort=new",
    )

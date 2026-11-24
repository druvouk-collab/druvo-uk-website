"""Google rich results / Merchant listings and UK price display (DMCC Act)."""

import json

from fastapi.testclient import TestClient

from app.data import mock_catalog
from app.main import app
from app.services.merchant_service import build_merchant_feed_items, merchant_feed_xml
from app.services.seo_service import organization_json_ld, product_json_ld, website_json_ld


def _product():
    product = mock_catalog.get_product("navy-wool-blazer")
    assert product is not None
    return product


def test_product_offer_has_shipping_and_return_policy():
    data = json.loads(product_json_ld(_product()))
    offers = data["offers"]
    offer = offers["offers"][0] if offers["@type"] == "AggregateOffer" else offers
    ship = offer["shippingDetails"]
    assert ship["shippingRate"]["currency"] == "GBP"
    assert ship["shippingDestination"]["addressCountry"] == "GB"
    assert ship["deliveryTime"]["transitTime"]["unitCode"] == "DAY"
    policy = offer["hasMerchantReturnPolicy"]
    assert policy["merchantReturnDays"] == 14
    assert policy["applicableCountry"] == "GB"


def test_brand_names_for_branded_search():
    org = json.loads(organization_json_ld())
    site = json.loads(website_json_ld())
    assert "DRUVO" in org["alternateName"]
    assert "DRUVO" in site["alternateName"]
    assert site["publisher"]["@id"] == org["@id"]
    assert org["hasMerchantReturnPolicy"]["merchantReturnDays"] == 14


def test_merchant_feed_has_apparel_attributes_and_identifier_flag():
    from app.data import static_catalog

    product = static_catalog.get_product("balance-cream-2-piece-sweatshirt-jogger-tracksuit-set-l")
    assert product is not None
    xml = merchant_feed_xml(build_merchant_feed_items([product]))
    assert "<item>" in xml
    assert "gender>male<" in xml
    assert "identifier_exists>no<" in xml
    assert "age_group>adult<" in xml
    assert "google_product_category>" in xml
    assert "DRUVO AI" not in xml


def test_product_page_shows_delivery_next_to_price():
    client = TestClient(app)
    resp = client.get("/product/navy-wool-blazer")
    assert resp.status_code == 200
    assert "standard UK delivery" in resp.text
    assert "data-delivery-price" in resp.text


def test_sitemap_lists_product_images_for_google_images():
    from app.services.seo_service import sitemap_xml

    xml = sitemap_xml([{"loc": "https://druvo.uk/product/x", "lastmod": "2026-11-24", "changefreq": "daily",
                        "priority": "0.8", "images": ["https://druvo.uk/media/1.jpg"]}])
    assert 'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"' in xml
    assert "<image:loc>https://druvo.uk/media/1.jpg</image:loc>" in xml

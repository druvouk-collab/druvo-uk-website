"""Phase 1 — products, categories and stock live in the cloud database."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.data.static_catalog import CATALOG_PATH, get_product as static_get_product
from app.db import catalog_repo, models
from app.db.base import session_scope
from tests.db_support import db_url  # noqa: F401

SLUG = "balance-cream-2-piece-sweatshirt-jogger-tracksuit-set-l"


def test_import_matches_static_catalogue(db_url):
    counts = catalog_repo.import_catalog_json(CATALOG_PATH)
    assert counts["products"] >= 1
    db_product = catalog_repo.get_product(SLUG)
    static_product = static_get_product(SLUG)
    assert db_product is not None and static_product is not None
    assert db_product.name == static_product.name
    assert db_product.images == static_product.images
    assert db_product.min_price == static_product.min_price
    assert [v.sku for v in db_product.variants] == [v.sku for v in static_product.variants]
    assert db_product.variants[0].variant_id is not None
    assert db_product.category_name == static_product.category_name
    assert db_product.is_live


def test_reimport_keeps_database_stock(db_url):
    catalog_repo.import_catalog_json(CATALOG_PATH)
    with session_scope() as s:
        variant = s.scalar(select(models.Variant))
        variant.stock_quantity = 0
        sku = variant.sku
    catalog_repo.import_catalog_json(CATALOG_PATH)
    with session_scope() as s:
        assert s.scalar(select(models.Variant).where(models.Variant.sku == sku)).stock_quantity == 0


def test_draft_products_hidden(db_url):
    catalog_repo.import_catalog_json(CATALOG_PATH)
    with session_scope() as s:
        s.scalar(select(models.Product).where(models.Product.slug == SLUG)).status = "draft"
    assert catalog_repo.get_product(SLUG) is None
    assert all(p.slug != SLUG for p in catalog_repo.all_products())


def test_storefront_renders_from_database(db_url):
    catalog_repo.import_catalog_json(CATALOG_PATH)
    client = TestClient(_app())
    page = client.get(f"/product/{SLUG}")
    assert page.status_code == 200
    assert "Sweatshirt" in page.text
    assert "standard UK delivery" in page.text
    sitemap = client.get("/sitemap.xml")
    assert SLUG in sitemap.text
    feed = client.get("/google-merchant-feed.xml")
    assert SLUG in feed.text


def test_database_outage_degrades_gracefully(monkeypatch, db_url):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(catalog_repo, "all_products", boom)
    client = TestClient(_app())
    assert client.get("/shop").status_code == 200


def _app():
    from app.main import app

    return app

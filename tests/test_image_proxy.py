"""Image proxy URL rewrite tests."""

from app.lib.druvo_api.image_proxy import extract_image_relative_path, to_website_proxy_path, to_website_proxy_url


def test_extract_relative_path():
    assert extract_image_relative_path("http://127.0.0.1:8790/api/v1/images/product_1/a.jpg") == "product_1/a.jpg"


def test_to_website_proxy_path():
    assert to_website_proxy_path("product_8/img_9.png") == "/api/catalog/images/product_8/img_9.png"


def test_to_website_proxy_url():
    url = "http://127.0.0.1:8790/api/v1/images/product_2/photo.png"
    assert to_website_proxy_url(url) == "/api/catalog/images/product_2/photo.png"


def test_external_url_unchanged():
    url = "https://cdn.example.com/item.jpg"
    assert to_website_proxy_url(url) == url

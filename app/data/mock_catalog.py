"""Mock UK resale catalog — replaced by DRUVO AI API when CATALOG_SOURCE=druvo_api."""

from __future__ import annotations

from dataclasses import replace

from app.types.commerce import Category, Product, ProductVariant

# Self-hosted catalog images (Render-safe — no external hotlink dependency)
_CAT = "/static/images/catalog/categories"
_PROD = "/static/images/catalog/products"

_CATEGORIES: list[Category] = [
    Category(
        slug="womens-clothing",
        name="Women's Clothing",
        description="Curated pre-loved and new-with-tags womenswear.",
        image=f"{_CAT}/womens-clothing.jpg",
    ),
    Category(
        slug="mens-clothing",
        name="Men's Clothing",
        description="Premium streetwear, tailoring, and everyday essentials.",
        image=f"{_CAT}/mens-clothing.jpg",
    ),
    Category(
        slug="footwear",
        name="Footwear",
        description="Trainers, boots, and seasonal shoes.",
        image=f"{_CAT}/footwear.jpg",
    ),
    Category(
        slug="accessories",
        name="Accessories",
        description="Bags, belts, jewellery, and more.",
        image=f"{_CAT}/accessories.jpg",
    ),
    Category(
        slug="designer",
        name="Designer",
        description="Authenticated designer pieces at resale prices.",
        image=f"{_CAT}/designer.jpg",
    ),
]

_PRODUCTS: list[Product] = [
    Product(
        id="p001",
        slug="navy-wool-blazer",
        name="Navy Wool Blazer",
        description="Classic single-breasted navy blazer in excellent pre-loved condition. Fully lined with functional button cuffs.",
        category_slug="mens-clothing",
        category_name="Men's Clothing",
        brand="Reiss",
        condition="Excellent",
        images=[f"{_PROD}/navy-wool-blazer-1.jpg", f"{_PROD}/navy-wool-blazer-2.jpg"],
        variants=[
            ProductVariant("RB-NVY-38", "38R", "Navy", 2, 89.00),
            ProductVariant("RB-NVY-40", "40R", "Navy", 1, 89.00),
            ProductVariant("RB-NVY-42", "42R", "Navy", 0, 89.00),
        ],
        tags=["blazer", "formal", "office"],
        is_new_arrival=True,
    ),
    Product(
        id="p002",
        slug="cashmere-roll-neck",
        name="Cashmere Roll Neck",
        description="Soft grey cashmere roll neck. Minimal pilling, perfect for layering through the UK winter.",
        category_slug="womens-clothing",
        category_name="Women's Clothing",
        brand="John Lewis",
        condition="Very Good",
        images=[f"{_PROD}/cashmere-roll-neck-1.jpg", f"{_PROD}/cashmere-roll-neck-2.jpg"],
        variants=[
            ProductVariant("CN-GRY-S", "S", "Grey", 3, 54.00),
            ProductVariant("CN-GRY-M", "M", "Grey", 2, 54.00),
            ProductVariant("CN-GRY-L", "L", "Grey", 1, 54.00),
        ],
        tags=["knitwear", "winter", "cashmere"],
        is_new_arrival=True,
        is_on_sale=True,
        sale_price_gbp=44.00,
    ),
    Product(
        id="p003",
        slug="white-leather-trainers",
        name="White Leather Trainers",
        description="Clean white leather low-top trainers. Light wear on sole, uppers in great shape.",
        category_slug="footwear",
        category_name="Footwear",
        brand="Common Projects",
        condition="Good",
        images=[f"{_PROD}/white-leather-trainers-1.jpg", f"{_PROD}/white-leather-trainers-2.jpg"],
        variants=[
            ProductVariant("CP-WHT-41", "UK 8", "White", 1, 165.00),
            ProductVariant("CP-WHT-42", "UK 9", "White", 2, 165.00),
            ProductVariant("CP-WHT-43", "UK 10", "White", 0, 165.00),
        ],
        tags=["trainers", "minimal"],
    ),
    Product(
        id="p004",
        slug="leather-crossbody-bag",
        name="Leather Crossbody Bag",
        description="Compact crossbody in black pebbled leather with adjustable strap and gold-tone hardware.",
        category_slug="accessories",
        category_name="Accessories",
        brand="Coach",
        condition="Excellent",
        images=[f"{_PROD}/leather-crossbody-bag-1.jpg", f"{_PROD}/leather-crossbody-bag-2.jpg"],
        variants=[
            ProductVariant("CB-BLK-OS", "One Size", "Black", 4, 120.00),
            ProductVariant("CB-CML-OS", "One Size", "Caramel", 2, 120.00),
        ],
        tags=["bag", "leather"],
        is_on_sale=True,
        sale_price_gbp=99.00,
    ),
    Product(
        id="p005",
        slug="silk-midi-dress",
        name="Silk Midi Dress",
        description="Emerald silk midi with subtle sheen. Ideal for events or elevated everyday wear.",
        category_slug="womens-clothing",
        category_name="Women's Clothing",
        brand="Whistles",
        condition="Like New",
        images=[f"{_PROD}/silk-midi-dress-1.jpg", f"{_PROD}/silk-midi-dress-2.jpg"],
        variants=[
            ProductVariant("SD-EMR-8", "UK 8", "Emerald", 1, 78.00),
            ProductVariant("SD-EMR-10", "UK 10", "Emerald", 2, 78.00),
            ProductVariant("SD-EMR-12", "UK 12", "Emerald", 1, 78.00),
        ],
        tags=["dress", "silk", "evening"],
        is_new_arrival=True,
    ),
    Product(
        id="p006",
        slug="designer-wool-coat",
        name="Designer Wool Coat",
        description="Double-breasted camel wool coat. Authenticated designer resale with DRUVO condition grading.",
        category_slug="designer",
        category_name="Designer",
        brand="Max Mara",
        condition="Excellent",
        images=[f"{_PROD}/designer-wool-coat-1.jpg", f"{_PROD}/designer-wool-coat-2.jpg"],
        variants=[
            ProductVariant("MM-CML-12", "UK 12", "Camel", 1, 295.00),
            ProductVariant("MM-CML-14", "UK 14", "Camel", 1, 295.00),
        ],
        tags=["coat", "designer", "winter"],
    ),
    Product(
        id="p007",
        slug="selvedge-denim-jeans",
        name="Selvedge Denim Jeans",
        description="Japanese selvedge denim in a straight fit. Natural fade developing on thighs.",
        category_slug="mens-clothing",
        category_name="Men's Clothing",
        brand="Nudie Jeans",
        condition="Good",
        images=[f"{_PROD}/selvedge-denim-jeans-1.jpg", f"{_PROD}/selvedge-denim-jeans-2.jpg"],
        variants=[
            ProductVariant("NJ-IND-30", "W30 L32", "Indigo", 2, 72.00),
            ProductVariant("NJ-IND-32", "W32 L32", "Indigo", 1, 72.00),
            ProductVariant("NJ-IND-34", "W34 L32", "Indigo", 0, 72.00),
        ],
        tags=["denim", "selvedge"],
        is_on_sale=True,
        sale_price_gbp=58.00,
    ),
    Product(
        id="p008",
        slug="merino-crew-jumper",
        name="Merino Crew Jumper",
        description="Forest green merino wool crew neck. Soft, breathable, and easy to care for.",
        category_slug="mens-clothing",
        category_name="Men's Clothing",
        brand="Uniqlo",
        condition="Very Good",
        images=[f"{_PROD}/merino-crew-jumper-1.jpg", f"{_PROD}/merino-crew-jumper-2.jpg"],
        variants=[
            ProductVariant("MC-FGR-S", "S", "Forest Green", 3, 32.00),
            ProductVariant("MC-FGR-M", "M", "Forest Green", 4, 32.00),
            ProductVariant("MC-FGR-L", "L", "Forest Green", 2, 32.00),
        ],
        tags=["knitwear", "merino"],
        is_new_arrival=True,
    ),
    Product(
        id="p009",
        slug="cream-tracksuit",
        name="Cream Tracksuit",
        description="Premium cream tracksuit set. Soft fleece lining, perfect for casual wear.",
        category_slug="mens-clothing",
        category_name="Men's Clothing",
        brand="DRUVO",
        condition="New with tags",
        images=[f"{_PROD}/cream-tracksuit-1.jpg"],
        variants=[
            ProductVariant("CTS-CRM-M", "M", "Cream", 2, 45.00),
            ProductVariant("CTS-CRM-L", "L", "Cream", 1, 45.00),
            ProductVariant("CTS-CRM-XL", "XL", "Cream", 3, 45.00),
        ],
        tags=["tracksuit", "cream", "loungewear"],
        is_on_sale=True,
        sale_price_gbp=30.00,
        compare_at_price_gbp=40.00,
    ),
]


def _as_live_catalog(product: Product) -> Product:
    return replace(product, catalog_status="live")


def all_categories() -> list[Category]:
    return list(_CATEGORIES)


def all_products() -> list[Product]:
    return [_as_live_catalog(p) for p in _PRODUCTS]


def get_category(slug: str) -> Category | None:
    return next((c for c in _CATEGORIES if c.slug == slug), None)


def get_product(slug: str) -> Product | None:
    product = next((p for p in _PRODUCTS if p.slug == slug), None)
    return _as_live_catalog(product) if product else None

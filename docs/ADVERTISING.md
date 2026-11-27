# Advertising on Facebook, Instagram, TikTok and Snapchat

Everything below is free to set up; you only pay when you run ads.

## Built (live)
- Consent banner (Accept / Reject, equal weight) shown only when at least one pixel is set; nothing from
  Meta/TikTok/Snapchat/Google loads before Accept. "Cookie settings" in the footer. Privacy policy lists
  the providers automatically.
- Events sent after consent: PageView, ViewContent, AddToCart, InitiateCheckout, Purchase (Purchase starts
  once online checkout is live). Product ids match the catalogue feed (variant SKU).
- Catalogue feed for all three: `https://druvo.uk/feeds/social-catalog.csv` (Google feed also works for Meta).

## Switch a pixel on (per platform, one at a time)
Render → https://dashboard.render.com → **druvo-uk** → **Environment** → **Add environment variable** →
**Save, rebuild and deploy**:
| Platform | Where to find the ID | Render key |
|---|---|---|
| Meta (Facebook + Instagram) | business.facebook.com → Events Manager → Connect data → Web → Pixel ID (digits) | `META_PIXEL_ID` |
| TikTok | ads.tiktok.com → Tools → Events → Web events → Pixel ID (letters+digits) | `TIKTOK_PIXEL_ID` |
| Snapchat | ads.snapchat.com → Events Manager → New event source → Web → Pixel ID | `SNAP_PIXEL_ID` |
| Google Analytics 4 (optional) | analytics.google.com → Admin → Data streams → Measurement ID (G-…) | `GA4_MEASUREMENT_ID` |

## Catalogue (product ads)
- Meta: Commerce Manager → Catalogue → Data sources → Data feed → Scheduled → URL above, daily.
- TikTok: Catalogue manager → Add products → Data feed → URL above.
- Snapchat: Catalogs → New catalog → Product feed URL → URL above.

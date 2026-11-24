# DRUVO — Development Roadmap

Prepared 24 Nov 2026 · Updated 24 Nov 2026 (session 4) · Lives in the website repo · Status labels: ✅ exists & verified · 🟡 exists, not yet verified
· 🔨 in development on `develop/online-checkout` · ⬜ not started

The goal is an intelligent, automated, multichannel UK retail business run through our own **DRUVO Manager**
(also called DRUVO AI). The website is one sales channel. Prices checked 24 Nov 2026 must be re-confirmed
before buying anything. Nothing is purchased, deployed or switched to live payments without owner approval.

---

## 1. What exists today

### Website — druvo.uk (repo `druvouk-collab/druvo-uk-website`, audited ✅)
| Feature | Status | Notes |
|---|---|---|
| Storefront, categories, product pages, search, basket | ✅ | FastAPI + Jinja2, Render Free plan |
| Order by email (static catalogue) | ✅ live | `CATALOG_SOURCE=static` |
| Live catalogue from DRUVO Manager API | ✅ code | `CATALOG_SOURCE=druvo_api`; needs the Mac online |
| Stripe test-mode checkout | ✅ code, not live | Depends on DRUVO Manager API for stock and orders |
| DRUVO Chat assistant (multilingual, order tracking) | ✅ live | |
| SEO: sitemap, robots, canonical, structured data, Merchant feed | ✅ live | improved on branch |
| Account / order history | ✅ code | via DRUVO Manager API |
| Cloud PostgreSQL database | 🔨 | Phase 1 done on branch (schema, migrations, import, tests) |
| Mac-independent checkout (Stripe, stock holds, webhooks) | 🔨 built & tested on branch | needs staging test with real Stripe test keys |
| Order emails (confirmation, shop alert, dispatch, refund) | 🔨 built & tested on branch | Resend; needs API key + domain DNS |
| Dispatch/tracking and refund operations (service layer) | 🔨 built & tested on branch | admin screens still to build |

### DRUVO Manager / DRUVO AI (on the MacBook — **not yet audited**)
What the website code proves exists: a local REST API (`/api/v1/products`, `/categories`, `/orders`,
`/stock/check`, `/promotions`) with API-key auth, a master inventory, order creation and status history,
promotions, product images served to the website, and local eBay OAuth (`127.0.0.1:8765`).
The README refers to an eBay **Sandbox** RuName, so production eBay status must be checked.

| Channel (owner-reported) | Status | To verify in audit |
|---|---|---|
| DRUVO.uk | 🟡 connected | API contract above ✅ |
| eBay | 🟡 connected | production vs sandbox, order import, stock push |
| Amazon | 🟡 connected | SP-API? listings, orders, FBA/FBM |
| Vinted | 🟡 in progress | method used must be the official API (see §4) |

**The audit can't start until Claude can read the DRUVO Manager source** — see §9.

---

## 2. Target architecture — "DRUVO Cloud" hub

```
                 ┌──────────────────────────── DRUVO Cloud (Render, 24/7) ───────────────────────────┐
 Customers ────► │ druvo.uk storefront + checkout ─┐                                                 │
                 │                                  ├─► PostgreSQL: products, variants, STOCK LEDGER, │
 Stripe ◄──────► │ webhooks (signed, idempotent) ───┘    orders, reservations, customers, audit log   │
                 │ Channel sync worker (in-process scheduler, no extra service)                      │
                 │   eBay ◄─► Amazon ◄─► Vinted Pro* ◄─► Depop* ◄─► TikTok Shop*                     │
                 │ Sync API (authenticated) ◄──────────────────────────────────────────┐             │
                 └─────────────────────────────────────────────────────────────────────┼─────────────┘
                                                                                       │
                                     DRUVO Manager (Mac) — management UI, AI research, │ listing creation,
                                     photos, pricing, purchasing recommendations ──────┘ works offline, syncs when online
```

Principles:
1. **One stock ledger in the cloud.** Every channel sale decrements the same row with an atomic
   `UPDATE … WHERE stock >= qty`. Selling the last unit anywhere immediately sets the others to 0.
2. **DRUVO Manager stays the management interface.** It pushes listings, prices and photos to the cloud and reads
   orders back. It's never needed for a customer to buy.
3. **Reuse, don't rebuild.** Manager's working eBay and Amazon code moves into (or is called by) the cloud worker after the audit.
4. **Every inbound event is idempotent**: Stripe event IDs, marketplace order IDs and an idempotency key on
   every write.
5. **Reconciliation job** every 15 minutes: compare each channel's listed quantity with the ledger and fix
   drift. Alert on conflicts, e.g. two channels sold the same one-off item within seconds.

### Oversell protection for one-off items
- Website: stock is reserved when a Stripe session is created and released when the session expires (built).
- Marketplaces: poll new orders every 2–5 minutes (eBay Sell Fulfillment API, Amazon SP-API Orders), or use
  push notifications where they're free. On a sale, decrement the ledger, then set quantity 0 on every other channel.
- The remaining risk is two near-simultaneous sales on different marketplaces. The reconciliation job detects
  it and DRUVO Manager prompts a cancel-and-refund on the later order, with the customer told promptly.

---

## 3. Website & payments (priority 1)

| # | Work | Status |
|---|---|---|
| W1 | Cloud PostgreSQL schema, migrations, catalogue import | 🔨 done on branch |
| W2 | Checkout: stock reservation, idempotent webhooks, orders in DB, oversell test with 8 concurrent buyers | ✅ on branch |
| W3 | Cards, Apple Pay, Google Pay, Link via Stripe Checkout (dynamic payment methods, test mode) | ✅ on branch |
| W4 | PayPal via Stripe: prepared; enabled once the fee is confirmed | ⬜ |
| W5 | Resend emails: order confirmation, shop alert, dispatched with tracking, refund | ✅ on branch |
| W6 | Secure admin: 2FA, products, prices, stock, orders, dispatch and tracking, refunds, audit log | ⬜ |
| W7 | Refunds (full or partial, optional restock, Stripe dashboard refunds mirrored) | ✅ service on branch; returns form ⬜ |
| W8 | Compliance pages: verified company details, returns wording review, privacy update | ⬜ owner input |
| W9 | Staging service on Render Free + Neon Free DB for end-to-end tests | ⬜ |
| W11 | Business dashboard: sales, fees, expenses, net profit, stock, pending orders | ⬜ (needs Manager audit for marketplace data) |
| W12 | Error reporting, uptime monitoring, automated DB backup export | ⬜ |
| W10 | Go-live: Render Starter + Postgres, Stripe live keys **after approval** | ⬜ approval |

## 4. Marketplaces (priority 2 — after the audit)

| Channel | Official route | Notes |
|---|---|---|
| eBay | Sell APIs (Inventory, Fulfillment) | Review the Manager code; move order polling to the cloud |
| Amazon | Selling Partner API | Review the Manager code; check app registration and roles |
| Vinted | **Vinted Pro Integrations** (allowlisted API) | Only official route. Needs Vinted Pro (business registration) plus allowlist approval |
| Depop | Selling API (partner access by invitation) | Listings, orders, refunds; UK selling fee removed, payment processing fee applies |
| TikTok Shop UK | TikTok Shop Partner API (OAuth app in Partner Center) | Seller registration needs company details; UK size charts mandatory |
| Facebook / Instagram | Meta Commerce Manager catalogue (product feed) | Native checkout ended Sept 2025, so shoppers check out on druvo.uk. Reuse the Merchant feed |
| Facebook Marketplace | No general listing API for retailers | Not recommended |

No scraping or unofficial automation of any marketplace: it breaks platform terms and risks account bans.

## 5. Intelligence & profitability (priority 3 — after the audit)

The audit decides what Manager already does. Proposed data model per product opportunity: wholesale cost,
inbound delivery, packaging, marketplace fee (per channel), payment fee, outbound postage, VAT position, expected
price, net profit, margin %, demand signal, sell-through time, risk score. Data sources must be official APIs or
licensed data (eBay Marketplace Insights / Browse API, Amazon SP-API pricing, Google Trends, supplier price lists).
The AI recommends; the **owner approves every purchase**.

Reports: slow-moving stock (no sale in 30/60/90 days), price-drop suggestions, channel profitability, weekly
sales summary emailed from the cloud.

## 6. Google ranking — 30 / 60 / 90-day plan (priority 1, alongside the website)

Baseline (24 Nov 2026): druvo.uk not yet confirmed in Google's index; Render Free spin-down risks a
"disallow all" robots.txt; 1 live product; no Search Console data yet. Brand risk: "DRUVO" is close to bigger
names (e.g. Druva, Drovo), so Google may treat "druvo" as a misspelling until brand signals build up.

**Days 0–30: foundations**
- Search Console (Domain property) verified; sitemap submitted; homepage and product indexing requested.
- Starter hosting at go-live (no spin-down, faster pages).
- Structured data: Organization and WebSite with "DRUVO" names (done on branch), Product with shipping and returns (done).
- Merchant Center: free listings live with the feed. Needs verified business details on the site.
- Google Business Profile (if eligible as an online-only business with a service area) and consistent NAP details.
- Brand profiles linked from the site and back (`sameAs`): Instagram, TikTok, eBay shop, Amazon storefront.
- Google Analytics 4 with a consent banner (UK GDPR/PECR). Core Web Vitals checked with PageSpeed Insights.
- **KPIs:** homepage indexed; ≥90% of sitemap URLs indexed; Merchant Center 0 disapprovals; mobile PSI ≥ 90.

**Days 31–60: content and products**
- At least 20 live products, each with a unique title (brand, item, size, colour, condition), 300+ word
  description, measurements, 3+ photos with descriptive file names and alt text.
- Category pages get unique intro copy; FAQ, About, Delivery and Returns pages cover the brand story.
- Image sitemap entries so products appear in Google Images.
- Internal linking: related products, "more from BALANCE", new arrivals.
- **KPIs:** #1 for "druvo uk" and "druvo.uk"; top 3 for "druvo"; 50+ product URLs indexed; first Shopping impressions.

**Days 61–90: authority and growth**
- Legitimate backlinks only: marketplace storefront links, supplier and brand pages, UK sustainable-fashion
  directories, local business listings, PR around pre-loved fashion. No paid or spam links, no fake reviews.
- Collect genuine reviews after purchase through a compliant review service (DMCC Act rules on reviews apply).
- Keyword research from Search Console queries; build pages for proven long-tail terms (e.g. "men's cream
  tracksuit set UK").
- **KPIs:** #1 for "druvo"; 500+ monthly organic clicks; 10+ referring domains; Merchant clicks growing month on month.

## 7. Running costs (fixed target < £15/month)

| Item | Monthly |
|---|---|
| Render Starter web service (incl. in-process sync worker) | $7 |
| Render Postgres Basic-256mb + 1 GB storage | ~$6.30 |
| Resend (free tier 3,000 emails/month) | $0 |
| Staging: Render Free + Neon Free | $0 |
| ICO data protection fee (£52/year) | ~£4.33 |
| **Total** | **≈ £14–15** (USD items at roughly £0.75–0.80 per $) |

Variable costs: Stripe 1.5% + 20p (standard UK cards), marketplace fees per channel, postage.
Database backups: confirm the recovery features of the chosen Render Postgres plan before go-live; a weekly logical export to private storage is also planned.

## 8. Security baseline
Admin 2FA (TOTP), hashed passwords (argon2/bcrypt), lockout after failed logins, CSRF, secure cookies, roles,
audit log, secrets only in Render environment variables, least-privilege API keys between Manager and Cloud,
HTTPS everywhere, customer data minimised and never logged, backups, error logging without personal data.

## 9. What Claude needs from the owner

1. **DRUVO Manager source code**, either:
   - a. **Preferred:** push the "Druvo AI" project to a *private* GitHub repo under `druvouk-collab` and add it to the
     Claude GitHub App (Repository access → select it). Before pushing, make sure `.gitignore` excludes `.env`,
     token files, `*.db`/`*.sqlite`, logs and customer exports; or
   - b. open this chat in the **Claude desktop app** on the MacBook and use **+ → Add folder** for
     `~/Desktop/Druvo AI` so Claude can read it directly; or
   - c. a ZIP of the project **without** `.env`, credentials, tokens, databases and customer data.
2. Database **schema only** (e.g. `sqlite3 druvo.db .schema > schema.sql`), not customer data.
3. Which eBay, Amazon and Vinted accounts are production, and whether the eBay app has production keys.
4. Verified company details for the website footer and Terms.
5. Stripe, Resend and Search Console set up per `docs/SETUP_GUIDE.md`.

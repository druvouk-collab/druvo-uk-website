# DRUVO — Master progress tracker

Governing plan: `docs/MASTER_ROADMAP.md` (owner's 13 phases). Last updated **24 Nov 2026, session 6**.

**Status key** (from the master roadmap):
⬜ Not started · 🔨 In development · 🧪 Built but untested in staging (automated code tests pass) ·
✅ Tested in staging · 🚀 Verified in production · ⛔ Blocked by external requirements

> Nothing is 🚀 yet: no change from this programme is live. druvo.uk still runs the old order-by-email site.
> 🧪 means the feature has automated tests (328 passing on PostgreSQL 16) but hasn't been exercised on staging
> with real Stripe/Resend test accounts or real marketplace sandboxes.

## Architecture decision (needs owner confirmation)
DRUVO Manager must run 24/7 without the MacBook and be usable from a phone, so its **central system now lives in
the cloud** (Render web service + PostgreSQL). The dashboard at `/admin` is branded **DRUVO Manager**, and DRUVO.uk
is one of its five channels. The existing Mac application is **not being rebuilt**: once its source is shared,
its working eBay/Amazon code is moved into the cloud, or keeps running and talks to the cloud through the
**Manager sync API**, whichever the audit shows is less work. Until then, eBay/Amazon jobs queue for it.

---

## Phase 1 — Review and consolidate
| Item | Status | Notes |
|---|---|---|
| Review website repo and all branches | ✅ | `main`, `email-orders`, `email-orders-preview`, `chat-assistant` reviewed; `develop/online-checkout` is the active branch |
| Review DRUVO Manager source | ⛔ | Source not shared yet (Mac only) |
| Verify eBay and Amazon integrations | ⛔ | Needs Manager source + account access. Website README mentions an eBay **sandbox** RuName |
| Vinted API history | 🔨 | Official route = Vinted Pro Integrations (allowlist). Need the history of previous attempts from the owner |
| Depop requirements | ✅ researched | Selling API is partner/invitation-only (developers@depop.com) |
| Duplication: website admin vs Manager | 🔨 | Resolved by the decision above: one cloud DRUVO Manager. Final merge after the audit |

## Phase 2 — Central cloud infrastructure
| Item | Status |
|---|---|
| PostgreSQL schema: products, unique SKUs, categories, brands, sizes, conditions, costs, prices | 🧪 |
| Product photos stored centrally (resized, EXIF/GPS stripped) | 🧪 |
| Available + reserved stock, stock movement history | 🧪 |
| Marketplace listing IDs/URLs/status per platform | 🧪 |
| Orders (all platforms), payments, refunds, shipping and tracking, marketplace fees, expenses | 🧪 |
| Migrations (Alembic), auto-migrate and seed on start | 🧪 |
| Runs 24/7 without the Mac | 🧪 design; ⛔ needs Render Starter + Postgres (owner approval at go-live) |
| Secure access from phone/tablet/computer (responsive dashboard, 2FA) | 🧪 |

## Phase 3 — Universal product listing
| Item | Status |
|---|---|
| Create a product once: name, brand, category, description, size/colour, condition, cost, price, quantity, photos, SKU/barcode | 🧪 |
| Choose platforms per product, platform-specific price | 🧪 |
| Listing status per platform: not listed / pending / published / failed / sold / ended / needs attention | 🧪 |
| Adapt listing to each marketplace (categories, item specifics, image rules) | ⛔ eBay/Amazon after audit · 🧪 basic listing pack for Vinted/Depop |
| Delivery information per listing (shipping profiles) | ⬜ |
| Photograph on phone → create → publish | 🧪 upload works from a phone browser; publishing via API ⛔ |

## Phase 4 — Marketplace integrations
| Platform | Capability | Status |
|---|---|---|
| DRUVO.uk | Product publishing from central DB, stock, checkout, Stripe cards/Apple Pay/Google Pay, confirmation/dispatch/refund emails, discount codes | 🧪 |
| DRUVO.uk | PayPal | ⛔ owner to check fee in Stripe (no code needed) |
| eBay | Create/update/price/quantity/end listings, import orders, fees, tracking | ⛔ existing Manager code to audit; cloud side ready (sync API, queued jobs, order import) |
| Amazon | Listings, inventory, pricing, orders, fees, shipping (SP-API, private app for own account) | ⛔ same as eBay. SP-API fees for developers were cancelled in May 2026 |
| Vinted | Official: Vinted Pro Integrations (allowlist). Now: **assisted** listing pack, listing tracking, manual-removal tasks, sale recording | 🧪 assisted · ⛔ API needs Vinted Pro + allowlist approval |
| Depop | Official: Selling API (invitation). Now: **assisted**, same as Vinted | 🧪 assisted · ⛔ API needs partner approval |

## Phase 5 — Intelligent stock management
| Item | Status |
|---|---|
| One physical stock figure for all platforms | 🧪 |
| Import order → update central stock immediately | 🧪 (Manager sync API / manual "record a sale") |
| Update other platforms after a sale | 🧪 queued; eBay/Amazon jobs wait for the connector ⛔; Vinted/Depop become manual tasks |
| Block further website purchases | 🧪 (also blocked while the item is held in someone's checkout) |
| Notify owner of each sale | 🧪 email |
| Record transaction and expected profit (estimated vs actual fees) | 🧪 |
| Webhooks + scheduled reconciliation (5-minute worker) | 🧪 |
| Duplicate order prevention (Stripe events, marketplace order ids) | 🧪 |
| Website checkout reservation | 🧪 (concurrency-tested) |
| Automatic retries with backoff, failed-sync alerts | 🧪 |
| Low-stock notifications (daily digest + dashboard) | 🧪 |
| Oversell detection and conflict handling (order kept, flagged, alerted) | 🧪 (race-tested website vs eBay) |
| Complete stock movement history | 🧪 |

Honest limit: when two marketplaces sell the same one-off item within the seconds or minutes before either
reports the sale, both sales can happen. DRUVO detects it, flags the later order and alerts you to cancel or refund it.

## Phase 6 — Central order management
| Item | Status |
|---|---|
| All platforms in one order list (platform, number, items, customer, price, fees, status, dispatch deadline, address, tracking, profit) | 🧪 |
| Pack / dispatch / tracking / delivered | 🧪 website; marketplace tracking upload queued for the connector ⛔ |
| Cancellations / returns / refunds | 🧪 website (Stripe); marketplace refunds happen on the marketplace |
| Royal Mail Click & Drop (free; API creates orders, marks despatched, labels) | ⬜ needs a Click & Drop account |
| Evri / DPD | ⬜ research |

## Phase 7 — Financial management
| Item | Status |
|---|---|
| Today/week/month/year sales, revenue and profit by platform | 🧪 |
| Purchase costs, marketplace commissions, payment fees (actual Stripe fee), postage, packaging, refunds, expenses | 🧪 |
| Gross and net profit, inventory value (cost and retail), best sellers | 🧪 |
| Estimated vs confirmed fees clearly labelled | 🧪 |
| Accounting CSVs (orders; monthly/yearly summary) | 🧪 |
| VAT handling | ⬜ (not VAT registered — confirm) |

## Phase 8 — AI features
⬜ All. Planned after the core is operational. The existing DRUVO Chat already uses OpenAI on the website.

## Phase 9 — Marketing and growth
| Item | Status |
|---|---|
| Search Console | ⛔ owner verification |
| Merchant Center / free Shopping listings (feed with shipping, returns, apparel attributes) | 🧪 feed · ⛔ account + verified company details |
| Google Images (image sitemap, alt text) | 🧪 |
| Facebook/Instagram catalogue (same feed) | 🧪 feed · ⛔ Meta account |
| Discount codes | 🧪 |
| Email marketing with consent, abandoned basket recovery (opt-in only) | ⬜ |
| Genuine customer reviews | ⬜ |

## Phase 10 — Mobile dashboard
Built (🧪): overview, tasks/notifications, orders, record sale, products, add product, listings per platform,
inventory and history, customers, discounts, sales and profit, expenses, reports, platforms (connections and fees),
activity log, account security. ⬜ Settings page (business details, delivery profiles).

## Phase 11 — Security and reliability
| Item | Status |
|---|---|
| Admin auth: argon2, TOTP 2FA, recovery codes, lockout, rate limits, CSRF, strict headers | 🧪 |
| API credentials only in environment variables; Manager API key auth | 🧪 |
| Nightly encrypted backups | 🧪 workflow · ⛔ GitHub secrets |
| Backup restoration tested | ✅ local round trip (encrypt → decrypt → restore → identical) on 24 Nov 2026 |
| Error monitoring (Sentry optional), alert emails | 🧪 |
| Activity/audit log | 🧪 |
| GDPR: export, erasure, minimal logging | 🧪 · ⬜ retention schedule, privacy policy update |
| Background processing with automatic retries | 🧪 |
| Repo private | ⛔ owner |

## Phase 12 — Operational testing
| Layer | Status |
|---|---|
| Automated code tests (328, PostgreSQL + SQLite, incl. concurrency) | ✅ |
| Stripe test-mode end-to-end on staging | ⛔ staging + Stripe test keys |
| Marketplace sandbox tests (eBay sandbox, Amazon SP-API sandbox) | ⛔ Manager audit + developer accounts |
| Mobile check on a real phone | ⛔ staging |
| Operation without the MacBook | ⛔ staging |

## Phase 13 — Production launch
⬜ After phase 12 and owner approval: Render Starter ($7) + Render Postgres Basic (~$6.30) ≈ £10–11/month
+ ICO £52/year ≈ £14–15/month in total.

---
## What's needed from the owner → `docs/OWNER_ACTIONS.md`

# DRUVO — Master progress tracker

Governing plan: `docs/MASTER_ROADMAP.md` (owner's 13 phases). Last updated **27 Nov 2026, session 12**. Owner activation steps: `docs/ACTIVATION_GUIDE.md`. Launch checklist (40 items) and customer journey test: https://claude.ai/artifact/QPK2maXuGnpTw8b5EPiNvY

**Status key** (from the master roadmap):
⬜ Not started · 🔨 In development · 🧪 Built but untested in staging (automated code tests pass) ·
✅ Tested in staging · 🚀 Verified in production · ⛔ Blocked by external requirements

> Nothing is 🚀 yet: no change from this programme is live. druvo.uk still runs the old order-by-email site.
> 🧪 means the feature has automated tests (328 passing on PostgreSQL 16) but hasn't been exercised on staging
> with real Stripe/Resend test accounts or real marketplace sandboxes.

## Architecture decision — ✅ approved by owner 24 Nov 2026
DRUVO Manager must run 24/7 without the MacBook and be usable from a phone, so its **central system now lives in
the cloud** (Render web service + PostgreSQL). The dashboard at `/admin` is branded **DRUVO Manager**, and DRUVO.uk
is one of its five channels. The existing Mac application is **not being rebuilt**: once its source is shared,
its working eBay/Amazon code is **moved into the cloud** as connectors. Owner requirement: the Mac app must
**not** be needed for sync, orders, stock or listing. The Manager sync API remains only as a temporary bridge.

---

## Live site status — 26 Nov 2026 (session 9)
| Item | Status | Evidence / notes |
|---|---|---|
| druvo.uk up; every sitemap page, image, robots, sitemap, feeds 200 | 🚀 | site monitor run 45776049124 |
| Real browser, iPhone-size + desktop, 14 pages + add-to-basket | 🚀 | browser check after PR #5: 0 JS errors, 0 broken images, no sideways scroll |
| Speed (Lighthouse mobile, live) | 🚀 PR #3 | home 96 · shop 100 · product 96 (was 80); SEO 100; accessibility 98–100 |
| Security headers, API docs hidden, config endpoint protected | 🚀 PR #4 + #6 | monitor checks headers and 404s; pip-audit clean |
| Ads readiness: consent banner, Meta/TikTok/Snapchat/GA4 pixels (off until IDs set), `/feeds/social-catalog.csv` | 🚀 PR #5 | browser test: nothing loads before Accept or after Reject |
| Keep-awake every 10 min (and ALL scheduled jobs incl. nightly backups) | ⛔ | 27 Nov: schedules now fire but only 9 times in 36 h (should be 216), so Render Free still sleeps → 503 / "waking up" screen. Hourly full check never fired (fixed in PR #9). Permanent fix: Render Starter (owner approval) |
| Google Merchant feed uses `g:` prefix | 🚀 PR #9 (27 Nov 20:33) | site monitor run 46064854299: all checks passed, feed `g:` only |
| `*.onrender.com` copies noindex / disallow-all | 🚀 PR #9 | druvo.uk verified indexable: no X-Robots-Tag on any sitemap page, meta robots index,follow, robots.txt unchanged |
| Full customer journey (browse → pay → emails → track → dispatch → return → refund + restock → last-item race → expiry) | ✅ real Stripe test mode | run 46072987131 (27 Nov 21:53): 15/15 with real Stripe API, hosted page + card 4242, real webhooks (completed, charge.refunded, 2× expired, all 200). Emails not tested (no `RESEND_API_KEY` secret) |
| Oversell prevention (8 buyers, 1 item) | ✅ | 340 tests on PostgreSQL 16 in CI (`tests.yml`) |
| Order confirmation / dispatch / refund emails | ✅ rendered | templates checked on a phone-width screen; sending ⛔ Resend account |
| Ads Purchase event on paid-order page | 🧪 develop | once per order |
| UK policies: returns (CCR 2013 + CRA 2015 + model form), delivery (Express removed), terms, privacy (UK GDPR); seller identity shown once set | 🚀 PR #7 + #8 | monitor checks the content on druvo.uk |
| Safety: live Stripe key locked until STRIPE_LIVE_MODE_CONFIRMED; db mode without DATABASE_URL falls back to static shop; MAINTENANCE_INTERVAL_SECONDS for Neon Free | 🧪 develop | 352 tests |
| Customer order page (private link in emails, find by number + email), online returns, Return received in Manager | 🧪 develop | journey test browse→refund passes; 344 tests on PostgreSQL (run 45777732229) |
| Search Console | ⛔ owner verification | |
| Merchant Center | ⛔ | needs online checkout live (see docs/MERCHANT_CENTER.md) |
| DRUVO Manager / eBay / Amazon / Vinted audit | ⛔ | MacBook not connected to this chat |

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
| **Publish everywhere in one action** ("upload once") with per-platform readiness checks | 🧪 (end-to-end test with simulated marketplaces) |
| Adapt listing to each marketplace (categories, item specifics, image rules) | ⛔ eBay/Amazon after audit · 🧪 generic checks (title length, photos, price, condition, brand, category, Amazon barcode) |
| Delivery information per listing (shipping profiles) | ⬜ |
| Photograph on phone → create → publish | 🧪 upload works from a phone browser; publishing via API ⛔ |

## Phase 4 — Marketplace integrations
| Platform | Capability | Status |
|---|---|---|
| DRUVO.uk | Product publishing from central DB, stock, checkout, Stripe cards/Apple Pay/Google Pay, confirmation/dispatch/refund emails, discount codes | 🧪 |
| DRUVO.uk | PayPal | ⛔ owner to check fee in Stripe (no code needed) |
| All API platforms | Cloud connector framework: publish / quantity / price / end / import orders / submit tracking, encrypted credential vault (sandbox vs production recorded), retries, permanent-error handling | 🧪 |
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
| Facebook/Instagram, TikTok, Snapchat catalogues | 🚀 `/feeds/social-catalog.csv` · ⛔ ad accounts |
| Ad pixels with UK-compliant consent | 🚀 off until IDs set (docs/ADVERTISING.md) |
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
| Automated code tests (331, PostgreSQL + SQLite, incl. concurrency; 329 passed / 2 skipped on SQLite 26 Nov) | ✅ |
| Full journey with **simulated** marketplaces, no Mac (create → publish everywhere → eBay order → stock 0 → other listings updated/tasks → website blocked → dispatch → tracking back to eBay → actual profit) | ✅ automated simulation, not a real marketplace test |
| Stripe test-mode end-to-end on staging | ⛔ staging + Stripe test keys |
| Marketplace sandbox tests (eBay sandbox, Amazon SP-API sandbox) | ⛔ Manager audit + developer accounts |
| Mobile check on a real phone | ⛔ staging |
| Operation without the MacBook | ⛔ staging |

## Phase 13 — Production launch
⬜ After phase 12 and owner approval. Full costs: `docs/COSTS.md` (≈ £14.30–15.00/month, including worker,
database, photo storage, backups, email and monitoring).

---
## What's needed from the owner → `docs/OWNER_ACTIONS.md`

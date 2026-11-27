# DRUVO UK — Project Handover

> Read this first at the start of every working session. Update the session log and task lists at the end of
> every session. **Never put passwords, API keys, tokens or other secrets in this file or anywhere in the repo.**

Last updated: 27 Nov 2026 (session 12)

> **Start here:** `docs/MASTER_ROADMAP.md` (the owner's plan) → `docs/PROGRESS.md` (status of every feature)
> → `docs/OWNER_ACTIONS.md` (what's waiting on the owner). DRUVO Manager is the product; DRUVO.uk is one of
> five channels (DRUVO.uk, eBay, Amazon, Vinted, Depop).

## 1. Business objectives
- DRUVO UK sells new, new-with-tags and pre-loved clothing, footwear and accessories to UK customers.
- Goal: a fully functional, automated, scalable online retail business, independent of the owner's MacBook.
- The website works alongside **DRUVO AI Enterprise** (desktop app, master inventory, eBay/Vinted), but must
  never depend on it.
- Preserve the existing design, products, branding and SEO.
- Contact: druvo.uk@gmail.com

## 2. Where everything lives
| Item | Value |
|---|---|
| Live site | https://druvo.uk (www → bare domain) |
| Legacy URL | https://druvo-uk-website.onrender.com |
| GitHub | `druvouk-collab/druvo-uk-website` — `main` = live |
| Development branch | `develop/online-checkout` |
| Hosting | Render, Blueprint `render.yaml`, service `druvo-uk`, Free plan, Frankfurt; pushes to `main` deploy |
| Local copy (Mac) | `/Users/siamkhalil/Desktop/DRUVO_Website/` |
| Desktop app (Mac) | `/Users/siamkhalil/Desktop/Druvo AI/` |
| Not used | Netlify, Higgsfield (checked 24 Nov 2026 — empty) |

Secrets live **only** in Render → Environment. `.env` is never committed.

## 2b. DRUVO Manager / DRUVO AI (MacBook) — NOT YET AUDITED
- Central management app on the owner's MacBook (`/Users/siamkhalil/Desktop/Druvo AI/`). Source not yet shared
  with Claude — see `docs/ROADMAP.md` §9 for how to share it safely.
- Known from the website code: local REST API `/api/v1/products|categories|orders|stock/check|promotions`
  (API-key auth), master inventory, order status history, promotions, local eBay OAuth on 127.0.0.1:8765
  (README mentions an eBay **Sandbox** RuName).
- Marketplace status (owner-reported, unverified): DRUVO.uk connected · eBay connected · Amazon connected ·
  Vinted in progress.
- Long-term vision: trend research, supplier discovery, profit calculation, SEO listings, multichannel
  publishing, central stock/price sync, orders/returns, AI recommendations — owner approves all spending.
- Target architecture: cloud hub (Render + PostgreSQL) holds the single stock ledger and orders; Manager remains
  the management UI and syncs with the cloud; website never depends on the Mac. Details: `docs/ROADMAP.md`.

## 3. Technical summary
- Python 3.12, FastAPI, Jinja2 SSR, custom CSS, no Node build. Start: `bash scripts/start.sh`. Health: `/health`.
- Basket in browser localStorage.
- `CATALOG_SOURCE=db` (new, branch only): cloud PostgreSQL is the source of truth for products, stock and
  orders. Code: `app/db/` (models, migrations in `alembic/`, `catalog_repo.py`),
  `app/services/db_checkout.py` (stock holds + Stripe Checkout + webhooks),
  `app/services/order_ops.py` (dispatch, tracking, refunds), `app/services/notifications.py` + `app/templates/emails/`
  (Resend emails), `app/services/background.py` (5-minute sweep: release abandoned holds, retry emails).
  Start script runs migrations and seeds an empty database from `catalog.json`.
- **Admin dashboard** (`/admin`, branch only, needs `CATALOG_SOURCE=db`): `app/routes/admin_panel.py`,
  `app/admin/security.py`, templates `app/templates/admin/`, CSS `static/css/admin.css`. Argon2 passwords,
  TOTP 2FA with replay protection and 8 one-time recovery codes, signed HttpOnly SameSite=Strict cookies,
  CSRF on every POST, 5-failure account lockout (15 min), 10/15 min per-IP limit, strict CSP and no-store on
  /admin. First admin created once via `/admin/setup?token=ADMIN_SETUP_TOKEN`. Product photos stored in
  PostgreSQL (resized to 1600px, EXIF/GPS stripped) and served at `/media/<id>.jpg`.
- Reporting: `app/services/reporting.py` (London-time buckets; profit = sales − refunds − item cost − Stripe fee −
  marketplace fee − postage − packaging − expenses). Stripe's actual fee is fetched per order.
- Alerts: `app/services/alerts.py` emails the shop on webhook failures, stock conflicts, maintenance failures
  (throttled 1/hour per issue) and a daily 08:00 digest (to dispatch + low stock). Optional Sentry (`SENTRY_DSN`).
- Backups: `.github/workflows/db-backup.yml` nightly pg_dump → AES-256 gpg → 30-day artifact.
- Owner checklist: `docs/OWNER_ACTIONS.md`.
- **Multichannel core** (session 6): `app/services/inventory.py` (central stock ledger — every change is atomic,
  recorded in `stock_movements`, and queues `listing.sync_quantity` jobs), `app/services/channel_sync.py`
  (platforms, listings, idempotent marketplace sale import with oversell detection, sync worker with backoff,
  reconciliation, tasks), `app/routes/manager_api.py` (Bearer `MANAGER_API_KEY`; the existing Mac DRUVO Manager
  can push eBay/Amazon sales and listing states and pull queued jobs). Channel modes: internal (druvo.uk),
  automatic (eBay/Amazon, "awaiting_manager" until audited), assisted (Vinted/Depop).
- **Cloud connectors** (session 7): `app/connectors/` — `Connector` contract (publish, update_quantity,
  update_price, end, fetch_orders, submit_tracking) + `readiness_problems()`; register a class and store
  credentials to switch a platform from "via Manager" to fully cloud. `app/services/credentials.py` encrypts
  marketplace credentials with `CREDENTIALS_KEY` (Fernet) and records sandbox vs production.
  `channel_sync.crosslist_product()` = "publish everywhere"; `poll_marketplace_orders()` runs every 5 minutes.
- **Owner decision 24 Nov 2026:** cloud DRUVO Manager approved; the Mac app must not be required for anything.
  Full costs in `docs/COSTS.md`.
- `CATALOG_SOURCE`: `static` (catalog.json, order-by-email — **live today**), `druvo_api` (DRUVO AI API on the
  Mac; only mode where Stripe test checkout works), `mock` (dev).
- Stripe test-mode checkout exists (`app/services/stripe_service.py`, `app/routes/checkout_api.py`,
  `app/routes/stripe_webhook.py`) but depends on DRUVO AI for stock/orders; SQLite at `/tmp` (ephemeral).
- No PayPal code yet.
- Tests: `pytest -q` (284 passing on 24 Nov 2026).

## 4. Completed work
- **7–11 Aug 2026** — Initial build + Render deploy; DRUVO AI API client; Stripe test checkout with webhook;
  shipping (£3.99, free over £75); admin launch checklist; druvo.uk canonical domain; DRUVO Chat; SEO, indexing
  and Google Merchant feed; demo items hidden.
- **23 Nov 2026** — Static catalogue + order-by-email mode; BALANCE cream tracksuit set (L) £20 listed; Chat as
  email-ordering assistant; FAQ/Delivery updated; "Live stock" → "Availability confirmed by email"; meta
  description and plurals fixed; desktop/mobile check; Stripe & PayPal discussed.
- **24 Nov 2026 (session 7)** — Owner approved the cloud architecture. Built the cloud connector framework,
  encrypted credential vault, publish-everywhere with readiness checks, cloud order polling and tracking upload,
  and an end-to-end simulated journey test (no Mac). Complete cost breakdown. Backups kept 7 days to stay free.
- **24 Nov 2026 (session 6)** — Owner issued the master roadmap. Built the multichannel core (central stock
  ledger and history, listings per platform with platform prices/status, marketplace sale import, cross-platform
  propagation, assisted Vinted/Depop workflow, retries and alerts, reconciliation, tasks), the Manager sync API, and
  screens for inventory value, platforms and fees, tasks, revenue by platform, best sellers and accounting CSVs.
  Dashboard rebranded DRUVO Manager. Encrypted backup restore verified. 328 tests passing on PostgreSQL.
- **24 Nov 2026 (session 5)** — Admin dashboard (orders, dispatch, refunds, products and photos, stock and
  low-stock alerts, customers with GDPR export/erase, discount codes applied at checkout via Stripe coupons,
  expenses, daily/weekly/monthly/yearly sales and profit, CSV export, activity log); 2FA security; security
  headers site-wide; Stripe fee capture; owner alerts and daily digest; optional Sentry; nightly encrypted
  backups; image sitemap. 318 tests passing on PostgreSQL.
- **24 Nov 2026 (session 4)** — Mac-independent checkout built: stock reserved atomically when payment
  starts (8 simultaneous buyers for 1 item → exactly 1 succeeds, tested on PostgreSQL), Stripe Checkout with
  cards/Apple Pay/Google Pay/Link (PayPal appears once enabled in Stripe), browser prices ignored, idempotent
  webhooks, expiry returns stock, late payment after expiry flagged as STOCK CONFLICT. Resend emails: order
  confirmation (incl. 14-day cancellation info), shop alert, dispatch with tracking, refund — each sent once.
  Dispatch/refund service with audit log and DRUVO Manager outbox. Staging guide added. 307 tests passing.
- **24 Nov 2026 (session 2)** — Owner approved technical direction (see §6b). Google SEO work on branch:
  delivery charge shown next to every product price (DMCC Act); product structured data now includes
  shipping details and 14-day return policy (Google merchant listings); Organization/WebSite schema adds
  "DRUVO" alternate names and links; Merchant feed adds identifier_exists, google_product_category,
  gender, age_group and drops internal "DRUVO AI" wording. 4 new tests (288 passing).
  Owner setup guide written (`docs/SETUP_GUIDE.md`).
- **24 Nov 2026** — Project recovered and reviewed; hosting/database/payment/compliance research; solution
  proposal written (`docs/SOLUTION_PROPOSAL.md`); this handover added on `develop/online-checkout`.

## 5. Outstanding tasks
See `docs/SOLUTION_PROPOSAL.md` §8 for the phased plan.
0. **Audit DRUVO Manager** once source is shared (ROADMAP §9).
1. Owner decisions (proposal §9): hosting upgrade at go-live, business details, Stripe/Resend accounts,
   PayPal yes/no, delivery options, GitHub push access for Claude.
2. Phase 1 — Postgres schema, migrations, catalogue import.
3. Phase 2 — Stripe Checkout with stock reservation, idempotent webhooks, Apple Pay/Google Pay.
4. Phase 3 — Automated emails via Resend.
5. Phase 4 — Secure admin dashboard (2FA) incl. refunds.
6. Phase 5 — Delivery rates, tracking, UK compliance pages (company details, 14-day cancellation, DMCC pricing).
7. Phase 6 — Non-blocking DRUVO AI sync.
8. Phase 7 — Staging sign-off, owner approval, go-live.

## 6. Known issues
- **Google crawling:** live robots.txt and sitemap.xml are correct when the site is awake (checked 24 Nov:
  robots allows the site, blocks only private paths; sitemap lists 18 URLs incl. the product). Render's
  docs confirm a sleeping Free service answers robots.txt with "disallow all", so Google may intermittently
  be blocked — confirm in Search Console → Settings → robots.txt report. Fixed permanently by Starter plan.
- druvo.uk did not appear in a `site:druvo.uk` web search on 24 Nov — confirm real Google index status in
  Search Console.
- Returns page: "unworn items with tags attached" and "5–10 working days after inspection" need legal
  review — the 14-day cancellation right applies to all distance sales and refunds are due within 14 days of
  receiving goods back.
- Render Free plan: spins down after 15 min; serves "disallow all" robots.txt while asleep (SEO risk);
  blocks SMTP; ephemeral disk. Likely cause of the 503 reported 26 Nov. Mitigation (free): keep-alive +
  monitor in PR #1. Permanent fix: Render Starter at go-live (already approved in principle).
- No company name/address on the site.
- Delivery charge shown only at checkout — review against DMCC Act drip-pricing rules. Fixed in PR #1
  (product pages show "+ £3.99 standard UK delivery (total …)"), live once merged.

- **Repository is PUBLIC** on GitHub. No secrets are in it, but making it private is recommended
  (GitHub → repo → Settings → Danger Zone → Change visibility). Render deploys private repos fine.
- PayPal-via-Stripe UK fee not yet confirmed (check Stripe dashboard → Settings → Payment methods → PayPal).
- `/health/druvo` reveals whether API keys are set and their lengths — harmless but should be trimmed or
  protected before go-live.
- Backup artifacts are encrypted, but the repo should be private before backups are enabled.

## 6a. Running costs
Fixed target < £15/month. Planned at go-live: Render Starter $7 + Render Postgres ~$6.30 + ICO £52/yr
≈ £14–15/month. Resend free tier, staging on free tiers. Variable: Stripe 1.5% + 20p (standard UK cards),
marketplace fees, postage. Currently paying: £0 hosting (Render Free).

## 6c. SEO performance log
| Date | Indexed pages | "druvo" position | "druvo uk" position | Notes |
|---|---|---|---|---|
| 24 Nov 2026 | unknown (Search Console not set up) | not found | not found | Baseline. Render Free spin-down robots risk. |

## 6b. Owner decisions (24 Nov 2026)
- Approved: Render Starter + Render Postgres (~£10–11/month) — **purchase only after final approval**.
- Approved: Stripe (cards, Apple Pay, Google Pay); PayPal prepared, enabled only after fees confirmed.
- Approved: Resend for automated emails; secure admin dashboard (products, prices, stock, orders, refunds,
  deliveries); £3.99 standard delivery shown compliantly.
- Priority: Google ranking — #1 for "DRUVO" / "DRUVO UK"; products in Google Search and Shopping.
- Legal company details NOT yet verified — do not publish until owner confirms.
- No subscriptions or live payments without final approval.

## 7. Working rules
- Never create a new website, repository or project.
- All work on a development branch; tests must pass; owner approval before merging to `main` (which deploys).
- Stripe test mode until launch sign-off.
- No secrets in the repo.

## 8. Session log
### 27 Nov 2026 (session 12)
Checked: no open PRs before today; #1–#8 merged and live; develop CI green; Stripe test keys still not in
GitHub secrets. Live: druvo.uk in order-by-email mode, robots.txt and sitemap (18 URLs) OK; Merchant feed
reachable but written with `ns0:` prefix. Wake-up screen cause: GitHub ran the 10-minute keep-alive only 9×
in 36 h, so Render Free sleeps; hourly full check never fired. PR #9 (→ main, awaiting approval): monitor fix,
feed `g:` prefix, noindex for *.onrender.com. develop: `scripts/staging_journey.py` (full journey incl.
/admin 2FA, real refund, last-item race, Stripe expiry) — 18/18 in CI with `tests/fake_stripe.py`; real Stripe
run waits for keys. `docs/STAGING.md`: staging settings, launch and rollback. Draft launch PR #10. 355 tests.

### 26 Nov 2026 (session 11)
Live (PR #7, #8): UK-compliant returns/delivery/terms/privacy; £6.99 Express removed (never offered at checkout);
seller identity appears once BUSINESS_* are set; monitor checks policy content. develop: live-Stripe lock,
static-catalogue fallback without DATABASE_URL, MAINTENANCE_INTERVAL_SECONDS, complete render.yaml, CREDENTIALS_KEY
accepts any long secret. Neon Free assessed (docs/COSTS.md): OK for staging/very low traffic with interval 900;
Render Postgres recommended for payments. Vinted: only Vinted Pro Integrations (allowlist) is allowed; new
Vinted terms (8 Oct 2026, per third-party report) ban unauthorised automation — keep assisted workflow.
Amazon: private SP-API app, self-authorised, needs Professional plan. GitHub schedules still never fired.
Owner guide: docs/ACTIVATION_GUIDE.md.

### 26 Nov 2026 (session 10)
Launch checklist + journey test doc: https://claude.ai/artifact/QPK2maXuGnpTw8b5EPiNvY (6 verified · 16 built ·
18 not done). Built on develop: secure customer order page (HMAC link from emails; lookup needs order number AND
email, rate-limited) replacing email-only lookup in DB mode; online returns (return_requests table, migration
0002, customer + shop emails, Return received/Reject in Manager, refund closes return); full journey test.
Next: MacBook session (see doc, section "MacBook session").

### 26 Nov 2026 (session 9)
Owner approved PR #2/#3 and publishing tested improvements. Merged and verified live: PR #2 browser check,
PR #3 speed (product Lighthouse 80→96), PR #4 security headers, PR #5 ads readiness (consent banner, pixels off
until IDs set, social catalogue CSV), PR #6 (live service has no PRODUCTION_MODE → protection keyed on RENDER;
monitor now checks headers and hidden pages). develop: merged main, Purchase event, email wrap fix, Postgres CI
(340 pass incl. oversell race). Found: GitHub schedules not firing (keep-awake inactive). Mac not connected →
Manager audit still blocked. New docs: MERCHANT_CENTER.md, ADVERTISING.md.

### 26 Nov 2026 (session 8b) — owner approved PR #1
PR #1 merged and verified live. Render Free keep-alive: Render support has called keep-awake pings on Free an
abuse of the free tier and pointed to paid instances, so treat it as temporary; recommend Starter ($7/mo) once
approved. Live real-browser test passed on mobile and desktop (PR #2 to keep it running). Speed work in PR #3.
Stripe test-mode end-to-end workflow added on develop (needs Stripe TEST keys as GitHub secrets). Claude can
merge only with owner approval per PR.

### 26 Nov 2026 (session 8) — 503 report
Owner reported a 503 on druvo.uk. At 01:30 UTC the live site was healthy from an outside GitHub runner: all
18 sitemap pages, images, robots.txt, sitemap and Merchant feed returned 200 in under 1.5 s. Cause: Render
Free spin-down (cold starts can return 503 and serve "disallow all" robots.txt). Fix built at no cost:
`site-monitor.yml` (keep-alive every 10 min + hourly full check that emails the owner on failure) and
`scripts/site_check.py`. Also brought the tested Google shipping/returns structured data and "+ £3.99 delivery"
line to the live branch. Both are in **PR #1** (`ops/site-monitor` → `main`), awaiting owner approval —
Claude was not permitted to push to `main` itself. Tests: 288 (main + PR), 329 passed / 2 skipped (develop).
Search Console, Merchant Center and real Stripe testing still need the owner (unchanged).

### 24 Nov 2026 (session 7)
MacBook not connected to the chat and Manager source not on GitHub → owner guided to add the "Druvo AI" folder
via the Claude desktop app (one step at a time). Next after access: audit, check sandbox vs live credentials,
port eBay then Amazon into `app/connectors/`, test in sandboxes, then staging.

### 24 Nov 2026 (session 6)
Master roadmap received and stored. Reviewed everything against it → `docs/PROGRESS.md`. Research: Amazon cancelled
SP-API developer fees (May 2026); Royal Mail Click & Drop is free with an API. Built Phase 2/3/5/6/7 foundations that
apply to every platform (see §4). Recommended architecture: one cloud DRUVO Manager (needs owner confirmation).
Next: owner actions 1–5 and 14–16; then staging tests; then the Manager audit and eBay/Amazon connection.

### 24 Nov 2026 (session 5)
Built the admin dashboard and security/reliability layer (see §4). Couldn't validate Stripe calls with stripe-mock
(running the locally built tool was blocked in this environment), so validation happens on staging with real test
keys. Couldn't read Stripe's PayPal pricing page (needed approval). Next: owner completes `docs/OWNER_ACTIONS.md`
(private repo, Manager source, Stripe/Resend, staging, admin login); Claude runs the staging test plan, then
builds the Manager sync API after the audit, and abandoned-basket recovery for opted-in customers.

### 24 Nov 2026 (session 4)
Owner priorities: checkout, Stripe, emails, Manager audit, central stock, marketplace verification, dashboard,
SEO, backups/monitoring, £15 budget. DRUVO Manager source still not shared → items 4–7 blocked. Built and
tested checkout, emails, dispatch/refund services (SQLite + PostgreSQL 16, app booted end-to-end in db mode).
Next: owner sets up staging (SETUP_GUIDE Step 6) + Stripe/Resend test keys; Claude builds admin dashboard
(products, stock, orders, dispatch, refunds, sales/profit) and error reporting; audit Manager when shared.

### 24 Nov 2026 (session 3)
GitHub write access confirmed (Claude GitHub App). Pushed branch. Phase 1 database built and tested on
PostgreSQL 16 + SQLite (293 tests passing). Owner sent full project brief (DRUVO Manager vision, marketplaces,
SEO, costs < £15). Wrote `docs/ROADMAP.md` (existing vs to-build, cloud hub architecture, marketplace API
research, 30/60/90 SEO plan, costs, security). Paused deep checkout/stock-sync design decisions that depend on
DRUVO Manager until its source is audited; website checkout (W2) continues. Next: owner shares DRUVO Manager
source; Claude completes W2 checkout and W5 emails.

### 24 Nov 2026 (session 2)
Verified robots.txt/sitemap on live site; confirmed Render Free spin-down robots risk from Render docs.
Implemented Google structured-data, Merchant feed and delivery-price display changes on
`develop/online-checkout`; tests pass. Wrote owner setup guide (GitHub, Stripe, Resend, Search Console,
Merchant Center). Push still blocked pending GitHub App install. Next: Phase 1 database.

### 24 Nov 2026
Recovered project (repo, Render, live site in static email-order mode). Researched Render, Supabase, Neon,
Stripe, PayPal, Resend, ICO and UK online-selling rules. Wrote solution proposal with cost breakdown.
Created `develop/online-checkout` with this file. No changes to the live site. Push to GitHub pending —
Claude's GitHub access to the repo needs enabling.

### 23 Nov 2026
See §4.

# DRUVO UK — Online Checkout & Operations: Solution Proposal

Status: **proposal, awaiting owner approval** · Prepared 24 Nov 2026 · Branch `develop/online-checkout`

Nothing in this document has been purchased, upgraded or deployed. Prices were checked on 24 Nov 2026
and must be re-confirmed on each provider's pricing page before buying. This is not legal or financial advice.

---

## 1. Goals (owner requirements)

1. Website and checkout available 24/7, independent of the MacBook.
2. Persistent cloud database: products, stock, customers, orders.
3. Automatic stock decrement after successful payment.
4. No duplicate orders, no overselling (important: most items are one-off pre-loved pieces).
5. Stripe checkout: debit/credit cards, Apple Pay, Google Pay. Investigate PayPal.
6. Automatic customer confirmation emails and shop notifications.
7. Secure admin dashboard: products, prices, stock, orders, refunds.
8. Proper delivery charges and order tracking.
9. UK online-selling compliance.
10. Integration with DRUVO AI where practical, without the website depending on it.
11. Preserve current design, products, branding and SEO.

## 2. Problems with the current setup (found 24 Nov 2026)

| Issue | Impact |
|---|---|
| Render **Free** web service spins down after 15 min idle; ~1 min cold start | Not 24/7. First visitor after idle waits ~1 min. |
| While spun down, Render answers `/robots.txt` with **"disallow all"** | Search engines are intermittently told not to crawl druvo.uk — hurts SEO. |
| Free web services block outbound SMTP ports (25/465/587) | Order emails via SMTP cannot work on the free plan. |
| Filesystem is ephemeral; checkouts stored in SQLite at `/tmp` | Pending checkouts lost on every restart/deploy. |
| Existing Stripe flow checks stock and creates orders via the DRUVO AI API on the Mac | Mac off = no checkout. |
| No PayPal code | — |
| No company name/address on the site | Required for UK distance selling. |
| Delivery (£3.99) added only at checkout | Needs review against DMCC Act drip-pricing rules (see §7). |

## 3. Hosting & database comparison

| Option | Monthly cost (USD) | 24/7? | Notes |
|---|---|---|---|
| **Render Starter web service** | $7 | Yes | Same platform, repo, Blueprint and domain as today. No migration. |
| Render Free web service (today) | $0 | No | Spin-down, robots.txt issue, SMTP blocked. |
| Render Standard web service | $25 | Yes | 1 CPU / 2 GB. Upgrade path, not needed yet. |
| **Render Postgres Basic-256mb** | $6 + $0.30/GB storage | Yes | Same region (Frankfurt) as the app, private network, managed. |
| Render Postgres Basic-1gb | $19 + storage | Yes | Upgrade path. |
| Render Postgres Free | $0 | — | **Expires after 30 days**, then deleted after 14-day grace. Not usable. |
| Supabase Free | $0 | No | Projects **pause after 1 week of inactivity**. Not usable for a shop. |
| Supabase Pro | $25 + compute (−$10 credit) | Yes | Good product (auth, storage, dashboard) but ~4× the cost of Render Postgres for what we need. |
| Neon Free | $0 | Yes* | Scale-to-zero (fast resume), 100 CU-hours/month, small storage cap. Good for a **staging** database. |
| Neon Launch | Pay-as-you-go ($0.106/CU-hr, $0.35/GB-month) | Yes | Viable production alternative; cost varies with traffic. |

**Recommendation:** stay on **Render** and add **Render Postgres Basic-256mb**. One provider, one bill, no
migration risk, database next to the app. Use **Neon Free** for a separate staging database at $0.

Product images: a 1 GB Render persistent disk ($0.25/month) for admin uploads, or object storage
(e.g. Cloudflare R2) — decided during build.

## 4. Payments

### Stripe (recommended primary)
- **Stripe Checkout** (Stripe-hosted, PCI handled by Stripe) with automatic payment methods:
  Visa/Mastercard/Amex debit & credit, **Apple Pay**, **Google Pay** (no extra Stripe fee for wallets), Link.
- UK fees (standard pricing, no monthly fee):

| Card type | Fee |
|---|---|
| Standard UK cards | 1.5% + 20p |
| Premium UK cards (corporate, Amex) | 1.9% + 20p |
| EEA cards | 2.5% + 20p |
| Other international cards | 3.25% + 20p (+2% if currency conversion) |
| Dispute (chargeback) | £20 per lost dispute |
| Refunds | Original processing fee is not returned |

### PayPal — investigated
- **PayPal through Stripe is available to UK-based Stripe accounts** (B2C direct businesses). It appears as
  another option inside the same Stripe Checkout, funds can settle to the Stripe balance, refunds up to 180 days.
  Requires connecting a PayPal business account in the Stripe dashboard. Confirm the exact fee in the
  Stripe dashboard before enabling (not published on the UK pricing page we checked).
- PayPal direct (own integration) UK rates: PayPal Checkout ~**2.9% + 30p**; PayPal Advanced card processing
  1.2% + 30p (blended); disputes £12–£14.
- **Recommendation:** Stripe first (cards + Apple Pay + Google Pay), then enable PayPal via Stripe — one
  integration, one dashboard, one webhook.

### Worked example: £20 item + £3.99 delivery = £23.99
| Payment | Fee | You receive |
|---|---|---|
| Standard UK card (Stripe) | £0.56 | £23.43 |
| Premium UK card (Stripe) | £0.66 | £23.33 |
| EEA card (Stripe) | £0.80 | £23.19 |
| PayPal direct (2.9% + 30p) | £1.00 | £22.99 |

## 5. Monthly running costs

| Item | Recommended start | Growth stage |
|---|---|---|
| Render web service | $7 (Starter) | $25 (Standard) |
| Render Postgres | ~$6.30 (Basic-256mb, 1 GB) | ~$19–20 (Basic-1gb) |
| Image storage | ~$0.25 | ~$1 |
| Render workspace | $0 (Hobby) | $0 (Pro $25 only if team features needed) |
| Transactional email (Resend) | $0 (3,000/month, 100/day) | $20 (50,000/month) |
| Staging DB (Neon Free) | $0 | $0 |
| **Total hosting** | **≈ $13.55/month (≈ £10–11)** | ≈ $65/month |

Other expenses:
- **ICO data protection fee** (UK GDPR): Tier 1 micro-business **£52/year** (£47 by Direct Debit) ≈ £4/month, unless exempt (check ICO self-assessment).
- Domain druvo.uk renewal (existing; registrar unknown — owner to confirm).
- Stripe/PayPal per-transaction fees (above).
- Postage (Royal Mail etc.) — passed to customer via delivery charge.
- Optional: accountant/legal review of Terms & Returns.

## 6. Target architecture

```
Customer ──► druvo.uk (Render Starter, FastAPI)
                │  ├── Postgres (Render) — products, variants, stock, customers,
                │  │                         orders, payments, refunds, shipments, audit log
                │  ├── Stripe Checkout ◄─► Stripe webhooks (signed, idempotent)
                │  ├── Resend (email API) — customer + shop notifications
                │  └── /admin (secure dashboard)
                │
                └── Sync API (optional, async) ◄──► DRUVO AI on the Mac
                     (website never waits for DRUVO AI)
```

### Overselling & duplicate protection
- Stock is **reserved atomically** when a Stripe Checkout Session is created
  (`UPDATE stock SET qty = qty - n WHERE qty >= n` inside a transaction).
- Stripe sessions expire after 30 min; `checkout.session.expired` releases the reservation.
- `checkout.session.completed` marks the order paid. Webhook event IDs stored with a unique constraint,
  so a replayed webhook can't create a second order. Unique constraint on Stripe session ID.
- Prices and delivery always recalculated server-side from the database, never trusted from the browser.
- Stripe idempotency keys on API calls.

### Admin dashboard
- Login with hashed passwords + **two-factor (TOTP)**, secure cookies, CSRF protection, rate-limited login,
  audit log of every change.
- Products: create/edit, images, prices, sale prices, condition, sizes/variants, stock, publish/hide.
- Orders: list/filter, view, mark packed/shipped, add carrier + tracking number (customer emailed automatically),
  cancel, **full/partial refunds via Stripe**, restock on refund.

### Delivery & tracking
- Configurable UK delivery rates (e.g. standard £3.99, free over £75 — existing values), optional tracked/express.
- Tracking number + carrier link stored per order, shown in account page, chat "Track my order" and emails.
- Later: Royal Mail Click & Drop integration for labels.

### DRUVO AI integration (non-blocking)
- Website database becomes the **master for website stock**.
- Outbox table: paid orders and stock changes are queued and pushed to DRUVO AI when it is online;
  retries automatically; never blocks checkout.
- Authenticated endpoint so DRUVO AI can push new listings and mark items sold on eBay/Vinted,
  preventing a one-off item selling twice across channels.

## 7. UK compliance checklist
- [ ] Business identity on site: trading name, **registered company name, company number, registered office,
      place of registration**, email (and VAT number if registered). Owner to confirm details.
- [ ] Pre-contract information: main characteristics, total price incl. delivery, payment and delivery
      arrangements, delivery within 30 days unless agreed.
- [ ] **14-day cancellation right** after delivery (applies to pre-loved goods too), model cancellation form,
      refund within 14 days of receiving goods back. Failing to inform customers extends the cancellation
      period to up to 12 months.
- [ ] Order confirmation on a durable medium (email) — automated.
- [ ] **DMCC Act 2024 price transparency** (in force since 6 Apr 2025): mandatory charges must be in the
      headline price. Review how delivery is shown on product pages; take advice if unsure.
- [ ] No fake/incentivised reviews (DMCC Act).
- [ ] UK GDPR: privacy policy update (Stripe, Resend, Render as processors), **ICO fee**, cookie banner if any
      non-essential cookies/analytics are used (PECR).
- [ ] Consumer Rights Act 2015: goods as described; accurate condition grading for pre-loved items.
- [ ] VAT registration if taxable turnover exceeds the threshold (currently £90,000).

## 8. Delivery plan (all on `develop/online-checkout`, tested before any live deploy)

| Phase | Scope | Exit check |
|---|---|---|
| 0 | Owner approvals, accounts (Stripe, Resend), business details | Decisions recorded in HANDOVER.md |
| 1 | Postgres schema + migrations (Alembic), import current catalogue, `CATALOG_SOURCE=db` | Site identical to today on staging |
| 2 | Stripe Checkout (test mode), reservations, webhooks, idempotency | Automated tests incl. concurrent-purchase test |
| 3 | Emails (Resend): confirmation, shop alert, shipped, refunded | Test emails received |
| 4 | Admin dashboard (2FA), products/stock/orders/refunds | Manual walkthrough + tests |
| 5 | Delivery rates, tracking, compliance pages & wording | Checklist §7 ticked |
| 6 | DRUVO AI sync (outbox + API) | Works with Mac on and off |
| 7 | Staging sign-off → owner approval → upgrade Render → deploy → Stripe live keys | Live test purchase + refund |

Rollback: the live site keeps running in email-order mode until Phase 7; going back is a redeploy of `main`.

## 9. Decisions needed from the owner
1. Approve Render Starter ($7) + Render Postgres Basic ($6) — **only at go-live**; build/testing costs $0.
2. Confirm the legal business details for the site (is it Druvo Ltd, company no. 16815569?).
3. Create/confirm a Stripe account (UK) and a Resend account; add keys in Render (never in GitHub).
4. PayPal via Stripe: yes/no (needs a PayPal business account).
5. Delivery options and prices (standard/tracked/express, free-delivery threshold).
6. Enable GitHub push access for Claude (Claude GitHub App) so work can be pushed to the branch.

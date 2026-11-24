# DRUVO UK — Project Handover

> Read this first at the start of every working session. Update the session log and task lists at the end of
> every session. **Never put passwords, API keys, tokens or other secrets in this file or anywhere in the repo.**

Last updated: 24 Nov 2026

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

## 3. Technical summary
- Python 3.12, FastAPI, Jinja2 SSR, custom CSS, no Node build. Start: `bash scripts/start.sh`. Health: `/health`.
- Basket in browser localStorage.
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
- **24 Nov 2026** — Project recovered and reviewed; hosting/database/payment/compliance research; solution
  proposal written (`docs/SOLUTION_PROPOSAL.md`); this handover added on `develop/online-checkout`.

## 5. Outstanding tasks
See `docs/SOLUTION_PROPOSAL.md` §8 for the phased plan.
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
- Render Free plan: spins down after 15 min; serves "disallow all" robots.txt while asleep (SEO risk);
  blocks SMTP; ephemeral disk.
- No company name/address on the site.
- Delivery charge shown only at checkout — review against DMCC Act drip-pricing rules.

## 7. Working rules
- Never create a new website, repository or project.
- All work on a development branch; tests must pass; owner approval before merging to `main` (which deploys).
- Stripe test mode until launch sign-off.
- No secrets in the repo.

## 8. Session log
### 24 Nov 2026
Recovered project (repo, Render, live site in static email-order mode). Researched Render, Supabase, Neon,
Stripe, PayPal, Resend, ICO and UK online-selling rules. Wrote solution proposal with cost breakdown.
Created `develop/online-checkout` with this file. No changes to the live site. Push to GitHub pending —
Claude's GitHub access to the repo needs enabling.

### 23 Nov 2026
See §4.

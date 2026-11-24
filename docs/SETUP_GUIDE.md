# DRUVO UK — Owner Setup Guide

Step-by-step instructions for the accounts the website needs. **Never paste keys, passwords or tokens into
GitHub, chat, email or this repo.** Secrets go only into Render → your service → **Environment**.
Everything here is free to set up; nothing is purchased and live payments stay off until you approve.

---

## Step 1 — Give Claude write access to the GitHub repo (free)

Claude can read `druvouk-collab/druvo-uk-website` but pushing is refused until the Claude GitHub App is installed.

1. Sign in to GitHub as the owner of the `druvouk-collab` account.
2. Open **https://github.com/apps/claude** → **Install** (or **Configure** if already installed).
3. Choose the **druvouk-collab** account.
4. Select **Only select repositories** → tick **druvo-uk-website** → **Install / Save**.
5. In claude.ai: **Settings → Connectors → GitHub** → connect / reconnect, signing in as the same GitHub user.
6. Tell Claude "GitHub access done". Claude pushes the `develop/online-checkout` branch.

Safety: `main` is what Render deploys. Claude only pushes to the development branch; merging to `main`
happens only after your approval. Optional extra protection: GitHub → repo → **Settings → Branches →
Add branch protection rule** for `main` → tick **Require a pull request before merging**.

---

## Step 2 — Stripe (free account, test mode only)

1. Go to **https://dashboard.stripe.com/register** and create the account with `druvo.uk@gmail.com`
   (or sign in if one exists). Country: **United Kingdom**.
2. You can stay in **test mode** (toggle top-right / "Sandbox") without completing business verification.
   Do **not** activate live payments yet.
3. **API keys (test):** Developers → **API keys**. You will need:
   - Publishable key `pk_test_…`
   - Secret key `sk_test_…` (click *Reveal*). Treat it like a password.
4. **Payment methods (test):** Settings → **Payment methods** → make sure **Cards**, **Apple Pay**,
   **Google Pay** and **Link** are on. Stripe-hosted Checkout handles Apple Pay/Google Pay without
   extra domain setup.
5. **Webhook (test mode):** Developers → **Webhooks** → **Add endpoint** →
   `https://<staging-url>/webhooks/stripe` → select events:
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`,
   `checkout.session.async_payment_failed`, `checkout.session.expired`, `charge.refunded`.
   Stripe then shows a signing secret `whsec_…` → Render staging → `STRIPE_WEBHOOK_SECRET`.
6. **Where the keys go:** Render dashboard → the **staging** service (not live) → **Environment** →
   `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`. Never into GitHub or chat.
7. **PayPal (later, optional):** Settings → Payment methods → **PayPal** → connect a PayPal *business*
   account. Before enabling, note the PayPal fee Stripe shows there and send it to Claude for the cost sheet.

Before go-live (needs your final approval): complete Stripe account activation (business details, bank
account, ID), then swap to live keys.

---

## Step 3 — Resend (free plan: 3,000 emails/month, 100/day)

1. Sign up at **https://resend.com/signup** with `druvo.uk@gmail.com`.
2. **Domains → Add domain** → enter `druvo.uk` (Resend may suggest a subdomain such as `send.druvo.uk`;
   accept the default). Region: **EU (Ireland)** if offered.
3. Resend shows DNS records (MX / TXT for SPF and DKIM, optionally DMARC). Add them **exactly** at the
   company where druvo.uk's DNS is managed (your domain registrar or Cloudflare). If you're not sure where
   that is, tell Claude the registrar name.
4. Back in Resend click **Verify DNS records** (can take minutes to a few hours).
5. **API Keys → Create API key** → name `druvo-website` → permission **Sending access** → domain
   `druvo.uk`. Copy the key `re_…` once.
6. Put it in Render → staging service → **Environment** → `RESEND_API_KEY`. Also set
   `EMAIL_FROM` = `DRUVO UK <orders@druvo.uk>` and `SHOP_NOTIFICATION_EMAIL` = `druvo.uk@gmail.com`.
   Until the domain is verified, Resend only lets you send test emails to your own address.

---

## Step 4 — Google Search Console (free) — top priority for ranking

1. Go to **https://search.google.com/search-console** → **Add property** → **Domain** → `druvo.uk`.
2. Google shows a **TXT record** → add it at your DNS provider → **Verify**.
   (Alternative: URL-prefix property `https://druvo.uk/` with the HTML-tag method — set the token in
   Render as `GOOGLE_SITE_VERIFICATION`; the site already outputs the meta tag.)
3. **Sitemaps** → submit `https://druvo.uk/sitemap.xml`.
4. **Settings → robots.txt report**: check whether Google ever fetched a "Disallow: /" version
   (this happens while Render's Free plan is asleep). Screenshot it for Claude.
5. **URL Inspection** → enter `https://druvo.uk/` → **Request indexing**. Repeat for the product page
   `https://druvo.uk/product/balance-cream-2-piece-sweatshirt-jogger-tracksuit-set-l`.
6. **Pages** report: send Claude a screenshot after a few days (shows indexed / not indexed and why).

## Step 5 — Google Merchant Center (free listings)

1. **https://merchants.google.com** → create account → business name **DRUVO UK**, country UK,
   website `https://druvo.uk` → verify/claim the site (easiest once Search Console is verified with the
   same Google account).
2. **Shipping & returns:** add UK shipping £3.99 (free over £75), handling 1–2 working days, transit
   2–4 working days; return policy 14 days, customer pays return postage unless faulty — matching the site.
3. **Products → Add products → Add from a file → Scheduled fetch** →
   `https://druvo.uk/google-merchant-feed.xml`, daily.
4. Make sure **free listings** (Google Shopping tab / Search) is enabled under *Growth → Manage programs*.
5. Merchant Center requires business name/address and contact details to be visible on the site — this is
   blocked until you've verified the legal company details (see HANDOVER).

---

## Step 6 — Staging site for end-to-end testing ($0)

Lets you place real **test-mode** orders on a private copy of the site before anything goes live.

1. **Neon** (free database): https://neon.com → sign up → create project `druvo-staging`, region
   **Europe (Frankfurt or London)** → copy the connection string (`postgresql://…`).
2. **Render** → **New + → Web Service** → connect `druvouk-collab/druvo-uk-website` → branch
   **`develop/online-checkout`** → name `druvo-uk-staging` → instance type **Free** → build
   `pip install -r requirements.txt`, start `bash scripts/start.sh`.
3. Environment variables for the staging service:
   `CATALOG_SOURCE=db`, `DATABASE_URL=<Neon string>`, `SITE_URL=https://druvo-uk-staging.onrender.com`,
   `PRODUCTION_MODE=false`, `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` (**test** keys),
   `STRIPE_WEBHOOK_SECRET`, `RESEND_API_KEY`, `EMAIL_FROM`, `SHOP_NOTIFICATION_EMAIL`, `SESSION_SECRET`
   (Render → "Generate").
4. On first start the site creates its tables and loads the products from `catalog.json` automatically
   (only when the database is empty).
5. Tell Claude the staging URL. Test with Stripe test card `4242 4242 4242 4242`, any future date, any CVC.

The live site (`main`, druvo.uk) is unaffected by the staging service.

# DRUVO — staging, launch and rollback

Never paste a key or password into chat, email or this repo. Keys go only where a step says.

## 1. Automatic staging (free, already running)
Workflow **Stripe test checkout** (`.github/workflows/stripe-e2e.yml`) runs on every push to
`develop/online-checkout`. The GitHub runner acts as the staging server: the shop from this branch, its own
throwaway PostgreSQL (never the live database), Stripe **test mode**, and Resend's test inbox
(`delivered@resend.dev`, reaches no real person).

- **rehearsal** job: runs now, no keys needed. Uses a stand-in Stripe (`tests/fake_stripe.py`).
- **checkout** job: the same journey against real Stripe test mode. Starts working as soon as these
  GitHub secrets exist (https://github.com/druvouk-collab/druvo-uk-website/settings/secrets/actions →
  **New repository secret**):

| Secret | Where to get it |
|---|---|
| `STRIPE_TEST_SECRET_KEY` | Stripe → **Test mode** on → Developers → API keys → Secret key `sk_test_…` |
| `STRIPE_TEST_PUBLISHABLE_KEY` | same page, `pk_test_…` |
| `RESEND_API_KEY` (optional) | resend.com → API keys → Create (Sending access). No domain needed for the test inbox |

Journey checked (`scripts/staging_journey.py`): browse → basket → pay with 4242 card on Stripe's page →
order paid by webhook, stock −1, confirmation + shop emails → customer finds the order → owner signs in to
`/admin` with a 2-step code → dispatch with tracking (email) → delivered → customer requests a return →
return received → refund with restock through `/admin` (real Stripe test refund; webhook not double-counted;
refund email) → stock back → two buyers race for the last item (one checkout, one "sold out") → Stripe
expires the checkout → stock released → item can be bought again.

## 2. Optional clickable staging site (free)
Only needed if you want to click through it yourself on your phone.
1. **Database:** https://console.neon.tech → New project `druvo-staging`, region **AWS Europe (Frankfurt)** →
   copy the connection string. (Separate from the live database; Neon Free costs £0.)
2. **Render:** https://dashboard.render.com → **New + → Web Service** → `druvo-uk-website` → branch
   `develop/online-checkout` → name `druvo-uk-staging` → region Frankfurt → **Instance type: Free** →
   Build `pip install -r requirements.txt` → Start `bash scripts/start.sh` → Health check path `/health`.
3. **Environment** (same page, "Add environment variable"):

| Key | Value |
|---|---|
| `CATALOG_SOURCE` | `db` |
| `DATABASE_URL` | the Neon string |
| `SITE_URL` | `https://druvo-uk-staging.onrender.com` |
| `PRODUCTION_MODE` | `false` |
| `SESSION_SECRET` | click **Generate** |
| `CREDENTIALS_KEY` | click **Generate** |
| `ADMIN_SETUP_TOKEN` | any 24+ random characters (delete after creating your admin login) |
| `STRIPE_SECRET_KEY` / `STRIPE_PUBLISHABLE_KEY` | the **test** keys (`sk_test_…` / `pk_test_…`) |
| `STRIPE_WEBHOOK_SECRET` | from step 4 |
| `RESEND_API_KEY` | from Resend |
| `EMAIL_FROM` | `DRUVO UK staging <onboarding@resend.dev>` (until druvo.uk is verified in Resend) |
| `SHOP_NOTIFICATION_EMAIL` | the email you signed up to Resend with |
| `MAINTENANCE_INTERVAL_SECONDS` | `900` (keeps Neon Free within its hours) |
| `CHAT_ENABLED` | `false` |

4. **Stripe webhook (test mode):** Stripe → Developers → Webhooks → **Add endpoint** →
   `https://druvo-uk-staging.onrender.com/webhooks/stripe` → events `checkout.session.completed`,
   `checkout.session.expired`, `checkout.session.async_payment_succeeded`,
   `checkout.session.async_payment_failed`, `charge.refunded` → copy the **Signing secret** `whsec_…` into
   `STRIPE_WEBHOOK_SECRET`.
5. Admin login: open `https://druvo-uk-staging.onrender.com/admin/setup?token=<your token>` (see
   OWNER_ACTIONS.md §6). Customer emails in tests: use `delivered@resend.dev`.

Staging is never indexed by Google: every `*.onrender.com` address sends `noindex` and a disallow-all
robots.txt. Don't keep staging awake (the free hours are shared with the live service).

## 3. Launch — only after the owner's written approval
Prerequisites: staging journey green with real Stripe test keys; 💷 Render Starter + database approved;
Resend domain druvo.uk verified; business details confirmed.
1. 💷 Render → `druvo-uk` → **Settings → Instance type → Starter**. Create the database
   (Render → New + → Postgres, Frankfurt, Basic) and copy its **Internal Database URL**.
2. `druvo-uk` → **Environment**: add everything from the table in §2 with live-site values
   (`SITE_URL=https://druvo.uk`, `PRODUCTION_MODE=true`, `EMAIL_FROM=DRUVO UK <orders@druvo.uk>`,
   `SHOP_NOTIFICATION_EMAIL=druvo.uk@gmail.com`, `MAINTENANCE_INTERVAL_SECONDS=300`, Stripe **test** keys and
   a test-mode webhook for `https://druvo.uk/webhooks/stripe`), but set **`CATALOG_SOURCE=static`** for now.
   The shop keeps taking orders by email.
3. Merge the develop PR into `main` → Render deploys. Check druvo.uk still shows **Order by email**.
4. Switch **`CATALOG_SOURCE=db`** → Save. The start script creates the tables and loads the catalogue.
   Create the admin login at `/admin/setup`, then delete `ADMIN_SETUP_TOKEN`.
5. One test-mode purchase on druvo.uk with card 4242 → dispatch → refund in `/admin`. Check the emails.
6. 💷 Stripe → activate the account → live keys and a live webhook into Render, plus
   `STRIPE_LIVE_MODE_CONFIRMED=true` (live keys are refused without it). Real £1 purchase on your phone,
   refund it from `/admin`.

## 4. Rollback
- **Back to order-by-email in about 1 minute (no code change):** Render → `druvo-uk` → Environment →
  `CATALOG_SOURCE` = `static` → **Save, rebuild and deploy**. Orders and stock stay safe in the database;
  refunds still work from the Stripe dashboard.
- **Stop card payments only:** remove `STRIPE_LIVE_MODE_CONFIRMED` (live keys are then locked) or put the
  test keys back.
- **Previous code:** Render → `druvo-uk` → **Events** → the last deploy before the merge → **Rollback** →
  confirm. Render turns auto-deploy off after a dashboard rollback; then revert the merge on GitHub (PR page
  → **Revert**) and turn auto-deploy back on (Settings → Auto-Deploy → On Commit).
- The database is never deleted by any of these steps.

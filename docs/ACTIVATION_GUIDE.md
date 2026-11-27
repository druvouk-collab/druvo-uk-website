# DRUVO — account activation guide (one step at a time)

Do one step, tell Claude "done", and Claude checks it before the next. Never paste a password or secret key
into chat or email. Keys go only where the step says (Render → Environment, or GitHub → Secrets).
Steps 1–5 are free and change nothing customers see. Steps marked 💷 need your approval first.

## Step 1 — Google Search Console (10 min)
1. https://search.google.com/search-console/welcome → sign in as druvo.uk@gmail.com.
2. **URL prefix** → `https://druvo.uk/` → **Continue** → **HTML tag** → copy the code inside `content="…"`.
3. https://dashboard.render.com → **druvo-uk** → **Environment** → add `GOOGLE_SITE_VERIFICATION` = that code,
   and `PRODUCTION_MODE` = `true` → **Save, rebuild and deploy**.
4. When it says **Live**: Search Console → **Verify** → **Sitemaps** → `sitemap.xml` → **Submit**.

## Step 2 — Stripe in test mode (15 min, no money moves)
1. https://dashboard.stripe.com/register → sign up with druvo.uk@gmail.com. Skip "activate payments" for now.
2. Top right: make sure **Test mode** is on. **Developers → API keys**.
3. GitHub → https://github.com/druvouk-collab/druvo-uk-website/settings/secrets/actions → **New repository
   secret**: `STRIPE_TEST_SECRET_KEY` = the `sk_test_…` key; again for `STRIPE_TEST_PUBLISHABLE_KEY` = `pk_test_…`.
4. Tell Claude. Claude runs the automatic test purchase (card 4242…) and sends you the screenshots.
5. While in Stripe: **Settings → Payment methods** → note the PayPal fee shown (don't switch it on).

## Step 3 — Resend for order emails (20 min)
1. https://resend.com/signup → sign up with druvo.uk@gmail.com (free plan).
2. **Domains → Add domain** → `druvo.uk` → region **EU (Ireland)**.
3. Resend shows 3–4 DNS records. Add them where druvo.uk's DNS is managed (the company you bought the domain
   from). Tell Claude the company's name and Claude gives you exact clicks.
4. When Resend shows **Verified**: **API keys → Create** (permission: Sending access) → copy it once.
5. GitHub secrets (same page as Step 2): `RESEND_API_KEY` = that key. Claude sends a test email to you.

## Step 4 — Wake up GitHub's timers, then make the code private (5 min)
GitHub hasn't run any scheduled job (keep-awake, hourly check, nightly backups) since 26 Nov. A commit made by
you usually restarts them:
1. Open https://github.com/druvouk-collab/druvo-uk-website/actions — if a yellow banner offers to enable
   workflows, click **Enable**.
2. Open https://github.com/druvouk-collab/druvo-uk-website/edit/main/.github/workflows/site-monitor.yml →
   in the first line add a space at the end → **Commit changes** → **Commit changes**.
3. Tell Claude; Claude checks a "schedule" run appears within the hour.
4. Then: **Settings** → bottom **Danger zone** → **Change visibility → Private**. Render keeps working.

## Step 5 — Business details (5 min)
Send Claude (in chat, these are public details, not secrets): legal name, company number, registered office
address to show on the site, VAT registered (yes/no + number), returns address if different. Claude adds them
to Render as `BUSINESS_LEGAL_NAME`, `COMPANY_NUMBER`, `BUSINESS_ADDRESS`, `VAT_NUMBER` with your OK.

## Step 6 💷 — Database and always-on hosting (decision)
Choose one (see the Neon assessment in docs/COSTS.md):
- **Lowest cost, £0:** Neon Free database + Render Free (site can sleep; background jobs pause while asleep).
- **Recommended for taking payments, ≈ $13/month:** Render Starter ($7) + Render Postgres Basic (~$6).
Claude gives the exact upgrade clicks only after your yes.

## Step 7 — Launch day (with Claude, ~1 hour)
1. Database connected (`DATABASE_URL`), shop data loaded, DRUVO Manager login created with 2-step codes.
2. Claude merges the online shop into the live site and runs the full journey test in Stripe test mode on druvo.uk.
3. 💷 Stripe → activate your account (identity, bank) → live keys into Render, plus
   `STRIPE_LIVE_MODE_CONFIRMED` = `true` (live payments stay locked without it).
4. You buy a £1 test product on your phone, Claude dispatches and refunds it. Then Merchant Center.

## Step 8 — On the MacBook: DRUVO Manager, eBay, Amazon, Vinted
Open this chat in the Claude desktop app → **+ → Add folder → Desktop → Druvo AI**. Claude audits the code and
walks you through eBay and Amazon developer keys (sandbox first).

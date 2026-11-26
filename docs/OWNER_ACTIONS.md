# DRUVO UK — Owner action list

## 👉 Current step (one at a time)
**Verify druvo.uk in Google Search Console** (free, ~10 min):
1. Open https://search.google.com/search-console/welcome (sign in as druvo.uk@gmail.com).
2. Right-hand box **URL prefix** → `https://druvo.uk/` → **Continue** → **HTML tag** → copy only the code
   inside `content="…"`.
3. https://dashboard.render.com → **druvo-uk** → **Environment** → **Add environment variable**:
   `GOOGLE_SITE_VERIFICATION` = that code. While there, also add `PRODUCTION_MODE` = `true`.
   **Save, rebuild and deploy**.
4. When the deploy shows **Live**, Search Console → **Verify** → tell Claude.

**Queue after that (Claude will guide each one):**
1. Keep-awake: GitHub isn't running the 10-minute schedule. Choose: free pinger at cron-job.org
   (Render discourages this on Free) **or** approve Render Starter $7/mo (no sleeping at all).
2. Stripe TEST keys → GitHub secrets, so Claude can run the full test purchase.
3. Business details for Merchant Center (docs/MERCHANT_CENTER.md).
4. Open this chat on the MacBook and add the Druvo AI folder (DRUVO Manager audit).

---
Reference list (Claude will walk you through these one by one after the current step):

Everything Claude needs from you, in order. **All steps are free.** Nothing here buys a subscription, takes live
payments or changes druvo.uk. Never paste passwords, keys or tokens into chat, email or GitHub. They go only into
Render → service → **Environment**, or GitHub → repo → **Settings → Secrets**.

Detailed click-by-click instructions for steps marked 📘 are in `docs/SETUP_GUIDE.md`.

| # | Action | Time | Unblocks |
|---|---|---|---|
| 1 | Make the GitHub repo **private** | 2 min | Security, backups |
| 2 | Share the **DRUVO Manager** source | 15 min | Audit, central stock, marketplaces |
| 3 | Create a **Stripe** account (test mode) 📘 Step 2 | 15 min | Payments testing |
| 4 | Create a **Resend** account + verify druvo.uk 📘 Step 3 | 20 min | Order emails |
| 5 | Create the free **staging** site (Neon + Render Free) 📘 Step 6 | 20 min | End-to-end testing |
| 6 | Create your **admin login** on staging (below) | 5 min | Dashboard |
| 7 | Stripe **webhook** for staging 📘 Step 2.5 | 5 min | Orders confirmed after payment |
| 8 | Optional: **Sentry** error monitoring (free plan) | 10 min | Error alerts |
| 9 | **Backup** secrets in GitHub (after go-live DB exists) | 5 min | Nightly backups |
| 10 | **Google Search Console** 📘 Step 4 | 10 min | Ranking |
| 11 | Verify **company details** for footer and Terms | — | Merchant Center, legal |
| 12 | **Merchant Center** and **Meta Commerce Manager** feeds 📘 Step 5 | 20 min | Free Google Shopping, Facebook/Instagram |
| 13 | Check the **PayPal** fee in Stripe | 2 min | PayPal decision |
| 14 | Confirm the **architecture decision** (one cloud DRUVO Manager; see PROGRESS.md) | 1 min | Everything |
| 15 | Tell Claude the **Vinted history** (what was tried, any error or refusal) and whether you'll apply for **Vinted Pro** | 5 min | Vinted |
| 16 | eBay/Amazon **account facts**: production or sandbox keys? Amazon Professional seller account? | 5 min | Integration audit |
| 17 | Optional: **Royal Mail Click & Drop** account (free) | 10 min | Labels and tracking |
| 18 | Set `MANAGER_API_KEY` (40+ random characters) on staging | 2 min | Mac Manager ↔ cloud |

---

### 1. Make the repository private
GitHub → `druvouk-collab/druvo-uk-website` → **Settings** → scroll to **Danger Zone** → **Change visibility**
→ **Private**. Render keeps deploying (it uses the GitHub connection you already authorised). The Claude
GitHub App keeps working.

### 2. Share DRUVO Manager (choose one)
- **Private GitHub repo (recommended):** create `druvouk-collab/druvo-manager` (Private). On the Mac, check the
  project's `.gitignore` lists `.env`, `*.db`, `*.sqlite`, `tokens*`, `*.log`, `exports/`, then push. Then
  GitHub → Settings → Applications → **Claude** → Configure → add `druvo-manager`.
- **Claude desktop app:** open this chat on the MacBook → **+ → Add folder** → `Desktop/Druvo AI`.
- Also send the database **schema only**: `sqlite3 <your db file> .schema > schema.sql` (no customer data).

### 6. Create your admin login (staging first)
1. Render → `druvo-uk-staging` → **Environment** → add:
   - `SESSION_SECRET` → click **Generate** (long random value)
   - `ADMIN_SETUP_TOKEN` → any random 24+ character string (e.g. from your password manager's generator)
2. Wait for the redeploy, then open `https://druvo-uk-staging.onrender.com/admin/setup?token=<that token>`.
3. Install an authenticator app (Google Authenticator / Microsoft Authenticator / 1Password), scan the QR
   code, choose a 12+ character password and enter the 6-digit code.
4. **Save the 8 recovery codes** (print or password manager).
5. Delete `ADMIN_SETUP_TOKEN` from Render's environment. Sign in at `/admin/login`.

### 7. Testing payments on staging (after steps 3–7)
- Card: `4242 4242 4242 4242`, any future expiry, any CVC, any UK postcode → should succeed.
- Declined: `4000 0000 0000 0002` → Stripe shows a decline and no order is confirmed; stock is released when
  the session expires.
- 3-D Secure: `4000 0025 0000 3155` → authentication pop-up.
- Abandon: open payment, close the tab → item returns to stock within about 40 minutes.
- Apple Pay: open the staging checkout in **Safari on an iPhone/Mac** with a card in Wallet. Google Pay: **Chrome**
  signed in with a saved card. In test mode Stripe doesn't charge the real card.
- Refund: in `/admin/orders/<order>` → Refund → check the customer refund email arrives.
Tell Claude the results (screenshots welcome) and Claude fixes anything that fails.

### 8. Sentry (optional, free)
sentry.io → sign up (Developer/free plan) → **Create project** → platform **FastAPI** → copy the **DSN** → Render
→ Environment → `SENTRY_DSN`. Personal data and cookies are stripped before anything is sent.

### 9. Nightly encrypted backups (once the live database exists)
GitHub → repo → **Settings → Secrets and variables → Actions → New repository secret**:
- `BACKUP_DATABASE_URL` = Render → your Postgres → **Connect → External Database URL**
- `BACKUP_PASSPHRASE` = a long random passphrase. **Also save it in your password manager**, because backups
  can't be restored without it.
Then **Actions → Database backup → Run workflow** to test. Backups are kept 7 days.

### 11. Company details
Confirm the exact legal name, company number, registered office address and whether you're VAT registered.
Claude adds them to the footer, Terms and emails through `BUSINESS_LEGAL_NAME`, `COMPANY_NUMBER` and
`BUSINESS_ADDRESS`. These are required for UK online selling and for Merchant Center approval.

### 12. Facebook and Instagram product feed
Meta Commerce Manager → **Catalogue → Data sources → Add items → Data feed → Scheduled feed** → URL
`https://druvo.uk/google-merchant-feed.xml` (Meta accepts the Google feed format), daily. Shoppers check out
on druvo.uk. Do this after go-live.

### 13. PayPal
Stripe Dashboard (test mode) → **Settings → Payment methods → PayPal**. Note the fee shown and tell Claude.
Don't activate it until we've compared costs. Once it's enabled, PayPal appears in checkout with no code change.

---
**Approvals Claude will ask for later** (nothing is bought until you say yes):
Render Starter ($7/mo) + Render Postgres Basic (~$6.30/mo) at go-live · Stripe live mode · merging to `main`.

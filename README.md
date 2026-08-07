# DRUVO UK — Public E-commerce Website

Standalone website project for **DRUVO UK**, designed to work alongside **DRUVO AI Enterprise 4.0** on your Mac without modifying the desktop application.

## Location

```
/Users/siamkhalil/Desktop/DRUVO_Website/   ← this project
/Users/siamkhalil/Desktop/Druvo AI/        ← desktop app (unchanged)
```

## Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Runtime | Python 3.10+ / FastAPI | Same ecosystem as DRUVO AI; easy future API bridge |
| Templates | Jinja2 (SSR) | SEO-friendly HTML, fast first paint |
| Styling | Custom CSS (DRUVO brand) | Premium dark theme, no Node build step required |
| Cart | Browser localStorage | Client-side basket until checkout API exists |
| Catalog | Mock module → DRUVO API | `CATALOG_SOURCE=mock` today, `druvo_api` later |
| Tests | pytest + httpx | Route and catalog coverage |

> **Note:** Node.js is not installed on this Mac, so we use FastAPI instead of Next.js. The architecture supports the same future integration points. You can migrate the frontend to Next.js later if desired.

## Run locally

```bash
cd "/Users/siamkhalil/Desktop/DRUVO_Website"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python3 run.py
```

Open: **http://127.0.0.1:8080**

Privacy policy (for eBay OAuth): **http://127.0.0.1:8080/privacy**

## Deploy on Render (recommended for eBay Privacy Policy URL)

Production uses `scripts/start.sh`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Render sets `$PORT` automatically. Do **not** commit `.env` — configure secrets in the Render dashboard.

### Step-by-step

1. **Create a GitHub repo** (if you have not already):
   ```bash
   cd "/Users/siamkhalil/Desktop/DRUVO_Website"
   git init
   git add .
   git commit -m "DRUVO UK website with Render deployment config"
   gh repo create druvo-uk-website --public --source=. --push
   ```
   Or create the repo on github.com and push manually.

2. **Sign in to [Render](https://render.com)** → **New +** → **Blueprint**.

3. **Connect your GitHub repo** containing `DRUVO_Website`.

4. Render reads `render.yaml` and creates the **druvo-uk** web service.

5. After the first deploy, open the service URL (e.g. `https://druvo-uk.onrender.com`).

6. In Render → **Environment**, set:
   - `SITE_URL` = `https://<your-service>.onrender.com` (your exact Render URL)

7. **Verify** (replace with your URL):
   - `https://<your-service>.onrender.com/`
   - `https://<your-service>.onrender.com/shop`
   - `https://<your-service>.onrender.com/privacy`

8. **eBay Sandbox RuName** → **Privacy Policy URL**:
   ```
   https://<your-service>.onrender.com/privacy
   ```
   (Auth Accepted URL stays `https://127.0.0.1:8765/auth/ebay/callback` for DRUVO AI local OAuth.)

### Manual Render setup (without Blueprint)

If you prefer not to use `render.yaml`:

| Setting | Value |
|---------|--------|
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `bash scripts/start.sh` |
| Health Check Path | `/health` |

Add environment variables from `.env.example` in the Render dashboard.

## Deploy to HTTPS (other hosts)

## Future DRUVO AI connection

```
┌─────────────────┐     REST API (future)     ┌──────────────────────┐
│  DRUVO UK Web   │ ◄───────────────────────► │ DRUVO AI Enterprise  │
│  (sales channel)│                           │ (master inventory)   │
└────────┬────────┘                           └──────────┬───────────┘
         │                                               │
         │                                               ├── eBay
         │                                               ├── Vinted
         └────────────── customers / orders ─────────────┘
```

1. DRUVO AI exposes `/api/v1/products`, `/api/v1/orders`, etc. (to be built in desktop app or sidecar service).
2. Set `CATALOG_SOURCE=druvo_api`, `DRUVO_API_BASE_URL`, `DRUVO_API_KEY` in website `.env`.
3. `app/lib/druvo_api/client.py` maps DRUVO master inventory → website catalogue.
4. Website orders POST back to DRUVO AI; stock decrements centrally; marketplaces sync from same master.

No eBay/Vinted logic lives in the website — only DRUVO AI integration.

## Tests

```bash
pytest -q
```

## Key routes

| Route | Purpose |
|-------|---------|
| `/` | Home |
| `/shop` | All products + filters |
| `/new-arrivals` | New listings |
| `/sale` | Offers |
| `/categories` | Category index |
| `/product/{slug}` | Product detail + variants |
| `/search` | Search |
| `/cart` | Basket |
| `/checkout` | Checkout structure |
| `/account` | Account dashboard |
| `/privacy` | **Public privacy policy (eBay OAuth)** |

Contact: **druvo.uk@gmail.com**

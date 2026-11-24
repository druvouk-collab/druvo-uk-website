# DRUVO Manager — complete running costs

Checked 24 Nov 2026. USD prices are converted at roughly £0.75–0.80 per $1. **Nothing below is active yet**:
today you pay £0 for hosting (Render Free). Each paid item needs your approval at go-live.

## Fixed monthly costs (production)

| Item | What it does | Monthly |
|---|---|---|
| Render **Starter** web service (512 MB, always on, no sleep) | Website, DRUVO Manager dashboard, Stripe webhooks, **and the background worker** (marketplace order import, stock sync, retries, reconciliation, emails every 5 minutes, all in the same service) | **$7.00** |
| Render **Postgres Basic-256mb** | Central database: products, stock, listings, orders, customers, finances | **$6.00** |
| Database storage, 1 GB | Includes **product photos** (stored in the database, resized to ~200–300 KB each, so ~3,000 photos fit) | **$0.30** |
| Render workspace (Hobby) | — | $0.00 |
| Nightly encrypted **backups** (GitHub Actions) | ~2 minutes/night of the 2,000 free minutes; 7 copies kept within the free storage allowance | $0.00 |
| **Resend** email (free plan) | Order confirmations, dispatch, refunds, alerts (3,000/month, 100/day) | $0.00 |
| **Sentry** error monitoring (free developer plan, optional) | Error alerts | $0.00 |
| **Staging** (Render Free + Neon Free) | Testing copy, never used for real customers | $0.00 |
| ICO data protection fee | Legal requirement (£52/year, or £47 by Direct Debit) | ~£4.33 |
| **Total** | | **≈ $13.30 + £4.33 ≈ £14.30–15.00** |

## When you'd need to spend more (only with your approval)
| Trigger | Change | Extra per month |
|---|---|---|
| Photos/data pass ~1 GB | +1 GB database storage | +$0.30 per GB |
| Backups pass the free artifact allowance (database over ~60 MB compressed) | Keep fewer copies or move backups to free object storage | $0 (configuration) |
| More than ~100 order/confirmation emails a day | Resend Pro (50,000/month) | +$20 |
| Thousands of listings, or the dashboard feels slow | Render Standard (1 CPU / 2 GB) or a separate $7 worker | +$7 to +$18 |

## Not infrastructure (variable or selling costs)
- Stripe: 1.5% + 20p for standard UK cards (higher for premium/international cards); £20 per lost dispute.
- PayPal via Stripe: fee to be checked in your Stripe dashboard before enabling.
- Marketplace fees (eBay, Amazon, Vinted Pro, Depop) are set per platform in **Platforms** for profit estimates.
- Amazon API access: Amazon cancelled its planned SP-API developer fees (May 2026). API access needs an
  Amazon **Professional** selling plan, a selling cost you may already pay.
- Royal Mail Click & Drop: free; you pay postage only.
- Domain renewal for druvo.uk (your existing registrar).

## Is £15/month reliable enough?
Yes, for the current scale (a few hundred listings, tens of orders a day). The Starter service never sleeps,
so marketplace sync and webhooks run 24/7. The background jobs are light: one check every 5 minutes. The main
limit is a single instance: during a deploy (about 1 minute) sync pauses and then catches up automatically,
because jobs are queued in the database, retried and reconciled. Upgrade when the dashboard or sync becomes
noticeably slow, not before.

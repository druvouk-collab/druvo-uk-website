# Google Merchant Center — what's ready and what's needed

## Ready on druvo.uk (live)
- Product feed: `https://druvo.uk/google-merchant-feed.xml` (id, title, description, price, availability,
  condition, brand, colour, size, gender, age group, Google category, shipping £3.99 GB, item group).
- Product pages: Product structured data with price, availability, shipping details and 14-day return policy.
- Delivery (`/delivery`), returns (`/returns`), privacy and terms pages; contact email in every footer.

## Must happen before applying (or Google may reject the store)
1. **Online checkout live.** Merchant Center expects customers to be able to buy on the site. Today druvo.uk
   takes orders by email. Free route: Stripe test passes on GitHub → owner approves → live Stripe + free
   database (Neon free tier) or Render Postgres.
2. **Business details on the site**, confirmed by the owner (not published yet):
   - legal name (e.g. "Druvo Ltd") and company number
   - registered office address (Merchant Center needs it; it can be shown in Terms/footer)
   - customer-service email (have: druvo.uk@gmail.com) and optionally phone
   - VAT registered? (yes/no; if yes, the VAT number)
3. **Returns rules confirmed:** 14 days from delivery; who pays return postage; refund within 14 days of
   receiving the item back (UK law). Current page says "5–10 working days after inspection" — owner to confirm.
4. **Shipping times:** dispatch (handling) days and delivery days for £3.99 standard (site says 1–2 + 2–4).

## Owner steps (after the above)
1. https://merchants.google.com → sign in as druvo.uk@gmail.com → **Get started** → business name, country UK.
2. Website: `https://druvo.uk` → verify with the same Google account as Search Console.
3. **Products → Add products → Add products from a file → Enter a link to your file** →
   `https://druvo.uk/google-merchant-feed.xml`, daily.
4. **Shipping and returns**: £3.99 standard UK, free over £75; 14-day returns.
5. Tell Claude the result of the first product review (Products → Needs attention).

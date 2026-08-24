# Frontend release runbook

## Build variables

- Required for accounts: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_TELEGRAM_BOT_USERNAME`.
- Optional until AdSense approves the site: `VITE_ADSENSE_CLIENT`, `VITE_ADSENSE_SLOT`.

Do not configure an empty or placeholder AdSense slot. Without a complete client/slot pair, the ad container stays hidden.

## Release dependencies

1. Deploy the Supabase membership/RLS migration first.
2. Deploy and configure Stripe checkout, customer-portal, and webhook functions before enabling the VIP payment button in production.
3. Confirm `https://reytacopicks.com/ads.txt` contains the publisher ID associated with the AdSense account.
4. AdSense approval and ad demand are external decisions. Sports-betting-adjacent content can receive restricted demand even when the site is otherwise policy compliant.

## Build and smoke test

```powershell
npm --prefix frontend test -- --run
npm run build
```

Check these URLs after deployment:

- `/` — Salmo visible, one public pick at most, honest history, four-item mobile navigation.
- `/privacidad.html` and `/terminos.html` — return 200 and link back to the home page.
- `/robots.txt`, `/sitemap.xml`, `/ads.txt` — return 200 as plain/static resources.

At 1280, 390, 360, and 320 CSS pixels, confirm `scrollWidth <= clientWidth`, Salmo has no dismiss control, and mobile navigation has four links.

## Rollback

The root `dist/` is a complete static artifact. Restore the previous known-good `dist` commit and redeploy it. Leave the secure Supabase migration in place; rolling back the UI must never re-expose premium rows. If checkout itself is unhealthy, disable `STRIPE_PRICE_ID`/the checkout function while leaving authentication and history available.

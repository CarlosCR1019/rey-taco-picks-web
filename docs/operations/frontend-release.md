# Frontend release runbook

## Stripe-first SPEI handoff

Stripe Checkout remains the primary VIP purchase action. Customers who choose
SPEI can open the secondary WhatsApp options for the seven-day `$129 MXN` plan
or the monthly `$349 MXN` plan. Those links use the public commercial number
`+52 33 3964 3226` and contain only a prefilled plan request.

Do not place a CLABE, bank name, beneficiary, receipt, email address, Telegram
identifier, or other payment details in frontend source or analytics. WhatsApp
handles the manual handoff, and access is activated only after the deposit is
confirmed independently. The `spei_whatsapp_clicked` analytics event permits
only aggregate funnel context and `plan=weekly|monthly`; it never activates or
extends a membership.

## Build variables

- Required for accounts: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_TELEGRAM_BOT_USERNAME`.
- Required for anonymous funnel measurement: `VITE_UMAMI_WEBSITE_ID`.
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

## Editorial Royal and Umami release evidence

Production release recorded on 2026-09-12:

- Commit: `4f1537f52250a83057121bff24024c17f4d44819`.
- Build command: `npm run build` from the repository root; this runs the frontend typecheck and Vite build before copying the static artifact.
- Deployment: Render static service `rey-taco-picks-web`, auto-deployed successfully in 14.0 seconds.
- Production URL: `https://reytacopicks.com`.
- Umami Render setting: `VITE_UMAMI_WEBSITE_ID`.
- Tracker privacy boundary: `data-exclude-search="true"` and `data-exclude-hash="true"`; event properties are allow-listed and must never contain email, user IDs, Telegram IDs, Stripe IDs, tokens, or free-form text.

Required anonymous funnel events:

- `vip_offer_viewed`
- `vip_plan_selected`
- `vip_auth_required`
- `checkout_started`
- `checkout_cancelled`
- `subscription_confirmed`
- `miniapp_opened`
- `spei_whatsapp_clicked`

Production smoke evidence for this release:

- The weekly `$129 MXN` and monthly `$349 MXN/mes` offers render with the approved risk copy.
- Both unauthenticated purchase paths open the Supabase authentication gate and do not initiate a charge.
- `#vip-access-panel` remains hidden without an authoritative active-membership response.
- The Umami script is present with the production website ID and privacy attributes after the Render environment rebuild.
- The application and free picks remain usable when the test browser blocks the third-party analytics runtime.

The final hosted-Stripe cancellation and `subscription_confirmed` checks require an authenticated non-VIP test account. Stop before payment, cancel back to the site, and confirm the corresponding events in the Umami dashboard before treating those two paths as release-certified.

## Rollback

The root `dist/` is a complete static artifact. Restore the previous known-good `dist` commit and redeploy it. Leave the secure Supabase migration in place; rolling back the UI must never re-expose premium rows. If checkout itself is unhealthy, disable `STRIPE_PRICE_ID`/the checkout function while leaving authentication and history available.

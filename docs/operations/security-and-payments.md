# Security and payments runbook

## Required configuration

Keep real values in provider secret stores, never in Git.

- Backend: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ADMIN_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`, `TELEGRAM_FREE_CHANNEL_ID`, `TELEGRAM_VIP_CHANNEL_ID`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `SITE_URL`.
- Frontend build: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_TELEGRAM_BOT_USERNAME`, and optionally `VITE_ADSENSE_CLIENT`, `VITE_ADSENSE_SLOT`.
The Supabase anonymous key is public by design. VIP secrecy depends on deploying the RLS migration before publishing the new frontend.

## Deployment order

1. Rotate any Telegram, Meta, Stripe, or Supabase service credential that has ever appeared in source history.
2. Apply `supabase/migrations/20260820220000_secure_membership.sql` to the target Supabase project.
   Purge any legacy `backend/channel_queue.json` on the running host before restarting `telegram_dispatcher.py`.
3. Verify an anonymous query returns only the one public pending pick and settled history. Verify a signed free account cannot read pending premium rows.
4. Create a recurring Stripe price for `$299 MXN` and store its identifier in `STRIPE_PRICE_ID`.
5. Deploy `create-checkout`, `create-portal`, and `stripe-webhook` with their server secrets.
6. Configure the Stripe webhook endpoint for `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, and `customer.subscription.deleted`.
7. Build the frontend with the public Supabase configuration. Add AdSense variables only after Google supplies a real slot.

## SPEI operations

- Receipts go to `backend/private_receipts/`, which is ignored by Git and never copied to `dist`.
- OCR may flag amount/bank text but always creates `pending_review`.
- Confirm the deposit in the bank independently. Then `/vip REVISION_UUID correo@ejemplo.com` atomically approves that review and creates or extends a 30-day `spei` subscription.
- Use `/rechazar REVISION_UUID` for an invalid receipt. Both decisions record `reviewed_by` and `reviewed_at`.
- Do not use `/aprobar` as a substitute for membership; it only handles a Telegram join request.

## Promotional access

- An authenticated admin generates a code with `select public.create_promo_code(7, now() + interval '14 days', 100);`.
- The raw code is returned only to the admin. The database stores its SHA-256 hash, expiry, access days, usage limit, and usage count.
- Customers redeem it from **Mi cuenta**. Redemption is transactional and the same account cannot use the same code twice.

## Incident and rollback

1. Disable checkout by undeploying `create-checkout` or removing `STRIPE_PRICE_ID`. Existing VIP reads remain governed by RLS.
2. Keep the webhook online long enough to process cancellations and failed invoices; otherwise reconcile Stripe subscriptions before disabling it.
3. If RLS behaves unexpectedly, take the frontend offline or revert to the previous static build. Do not disable RLS and do not add a permissive `using (true)` policy.
4. Rotate the affected provider credential and redeploy from secret storage.
5. Review `subscriptions`, `payment_reviews`, and Stripe event logs before restoring checkout.

## Local verification

```powershell
python -m unittest discover -s tests -p 'test_*.py'
npm --prefix frontend test -- --run
npm run build
npx -y deno test supabase/functions/stripe-webhook/subscription.test.ts supabase/functions/create-checkout/checkout.test.ts supabase/functions/create-portal/portal.test.ts
```

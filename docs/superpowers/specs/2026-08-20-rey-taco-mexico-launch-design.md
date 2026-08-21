# Rey Taco Picks Mexico Launch Design

**Date:** 2026-08-20
**Status:** Approved for implementation
**Market:** Mexico
**Primary offer:** VIP membership at $299 MXN/month

## 1. Outcome

Turn Rey Taco Picks into a trustworthy, mobile-first sports-picks product that can acquire its first Mexican customers, protect paid content, publish an honest performance history, support Stripe/SPEI/Telegram operations, and create policy-conscious inventory for Google AdSense.

The release succeeds when a new visitor can understand the product, see one useful free pick and the complete record, join Telegram, create an account, purchase or request VIP access, and consume only the data their membership permits. Existing automation keeps publishing picks and results without exposing credentials or falsely marking outcomes.

## 2. Product Principles

1. **Picks first.** The daily free pick and real record appear before advertising or long-form content.
2. **Proof before purchase.** Wins, losses, pushes/voids, pending picks, odds, dates, and units are visible. Metrics are derived from rows, never hardcoded.
3. **Premium means server protected.** A free browser never receives premium pick text. Blur is presentation, not authorization.
4. **Salmo del día is permanent.** It remains visible without a dismiss action and has a navigation entry on desktop and mobile.
5. **No guaranteed-profit language.** Copy presents analysis as informational/entertainment content and includes +18/responsible-play messaging.
6. **Mexico first.** Currency is MXN, times are displayed for Mexico City, copy uses Mexican Spanish, and Liga MX is prominent.

## 3. Approved Visual Direction

The homepage uses the approved “Picks primero” layout.

- Brand palette: wine `#7F0F22`, red `#C51C32`, gold `#F2A91E`, light gold `#FFD56A`, cream `#FFF4DE`, espresso `#24120C`, and green `#769B36`.
- Existing `frontend/public/logo.jpg` is the source brand asset.
- Deliver optimized logo variants for the header, Open Graph, favicon, Apple touch icon, and PWA manifest.
- Replace the current generic Vite `favicon.svg`.
- The mobile layout uses a fixed four-item bottom navigation: Picks, Results, Salmo, VIP.
- Minimum supported viewport is 320 CSS pixels with no horizontal document overflow.
- Controls have keyboard focus, labels, sufficient contrast, and at least 44-by-44-pixel mobile targets.

## 4. Information Architecture

The first release remains a Vite single-page application but separates responsibilities into focused modules.

- **Home:** free pick, live picks summary, transparent performance, Telegram and VIP calls to action.
- **Results:** complete chronological history with status filters and derived metrics.
- **Salmo:** permanent daily verse surface with “next verse” and copy actions, but no close action.
- **How it works:** methodology, how odds/units work, limitations, and responsible-play language.
- **Articles:** policy-conscious educational content and AdSense inventory.
- **VIP:** benefits, $299 MXN/month price, account state, checkout/SPEI alternatives, and membership management.

## 5. Acquisition and Conversion Funnel

The approved funnel is:

`Reels/TikTok/SEO/referrals -> free pick + complete history -> Telegram -> seven-day trust sequence -> VIP offer -> secure account`

The site exposes conversion events without sensitive data:

- `free_pick_viewed`
- `history_viewed`
- `telegram_clicked`
- `vip_offer_viewed`
- `checkout_started`
- `subscription_confirmed`

The first 30 days emphasize organic publishing and message validation. Days 31–90 may use $1,000–$3,000 MXN/month for content production, micro-creators, and only platform-authorized promotion. Paid gambling-related campaigns are not launched until required Google/Meta approvals are confirmed.

## 6. Data and Authorization Architecture

Supabase is the source of truth. The browser uses the public anon key, while privileged operations use service credentials only inside server functions or trusted backend jobs.

### Core tables

- `profiles`: `id`, `email`, `role`, `telegram_id`, `telegram_username`, timestamps.
- `subscriptions`: `user_id`, `provider`, `provider_customer_id`, `provider_subscription_id`, `status`, `current_period_end`, timestamps.
- `picks`: event identity, market, selection, odds, confidence label, reasoning, publication tier, state, result details, timestamps.
- `promo_codes`: hashed code, access duration, expiration, usage limit, uses.
- `payment_reviews`: SPEI proof metadata and `pending|approved|rejected` status. Receipt files are private.

### Access rules

- Anonymous users can read only explicitly public picks and public result fields.
- Authenticated free users have the same pick visibility plus their own profile.
- Active subscribers can read premium picks through a membership-aware function/view.
- Admin operations require `profiles.role = 'admin'`; email strings and client storage never grant admin access.
- Row Level Security is enabled for all user-facing tables.
- The UI derives membership from the signed Supabase session and subscription query, not `localStorage` flags.

## 7. Membership and Payment Flows

### Stripe — primary

Stripe Checkout creates the $299 MXN recurring subscription. The webhook validates its signature and handles at least:

- `checkout.session.completed`
- `invoice.paid`
- `invoice.payment_failed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Webhook updates are idempotent, keyed by Stripe IDs, and keep `status` plus `current_period_end` synchronized. A completed checkout alone must not create permanent access.

### SPEI — backup

SPEI receipts enter a private pending-review queue. OCR may extract reference data for the administrator, but never approves VIP automatically. Only an authenticated admin approval changes membership state. Public ticket-gallery files contain winning-ticket evidence, not customer payment receipts.

### Promotional codes

Codes are generated and validated on the server, stored hashed, expire, and enforce usage limits. Remove the hardcoded browser list.

### Telegram

The website issues a short-lived, single-use linking token. The bot exchanges it for the authenticated user and stores the Telegram identity. Join requests are accepted only while the subscription is active.

## 8. Results Integrity

Automated grading only occurs when the source explicitly reports a final/completed event.

- Team matching requires both teams to match with a conservative normalized similarity rule; one shared token is insufficient.
- Each supported market has an explicit grading function: moneyline, totals, both teams to score, run line/spread, corners only when corner statistics exist, and parlays only after every leg is graded.
- Unsupported or ambiguous markets remain `pending_review`; they never default to won.
- Grading stores source, source event identifier, home/away scores, decision, and timestamp for auditability.
- Unit result is `odds - 1` for a one-unit win, `-1` for a loss, `0` for void/push/pending.
- ROI, record, streak, and total units are calculated from graded rows and include losses.

## 9. Frontend Behavior

- Public fetch requests select only public-safe fields. There is no local JSON fallback containing private selections.
- Premium requests include the Supabase bearer session and handle `401/403` as a locked state.
- The free pick is one complete selection, not a blurred premium object.
- History renders won, lost, void/push, pending, and pending-review states with accessible labels.
- Empty and offline states do not invent example picks or historical wins.
- Content is escaped before insertion into HTML; inline `onclick` handlers are removed.
- The existing parlay builder is labeled experimental or hidden until it uses real model output. It must not claim “IA” for fixed rules.

## 10. SEO, AdSense, and Policy Surfaces

- Spanish document language, Mexico-focused title/description, canonical URL, Open Graph tags, and SportsOrganization/WebSite structured data.
- Add `robots.txt`, a basic sitemap, and meaningful article routes/content blocks.
- AdSense units require a valid `data-ad-slot` configured through environment/build settings plus a single guarded `adsbygoogle.push({})` per unit.
- Ads appear only after substantial public content, never inside the Salmo banner, checkout, VIP gate, or directly adjacent to purchase controls.
- The site includes Privacy, Cookies, Terms, Responsible Play, Contact, and About/Methodology content.
- Consent management is prepared for regions where it is required; Mexico traffic receives non-misleading privacy/cookie disclosure.
- Ad approval is external and cannot be guaranteed by implementation.

## 11. Secrets and Operations

- Revoke and rotate the exposed Meta and Telegram tokens found in tracked Python files.
- Code reads tokens, Supabase service credentials, Stripe secrets, channel IDs, admin IDs, and optional AdSense slot only from environment variables.
- Add `.env.example` files with names but no values.
- The app fails closed when required privileged configuration is absent.
- `.superpowers/`, runtime tickets, browser/session data, and local artifacts remain ignored.

## 12. Acceptance Criteria

1. `npm test`, `npm run typecheck`, and `npm run build` pass from `frontend`.
2. Python unit tests pass for conservative team matching, final-state gating, market grading, and SPEI manual review.
3. Static security tests prove the known admin password, VIP codes, live Meta token, and live Telegram token are absent from tracked source.
4. An anonymous browser response never contains premium pick selection/reasoning fields.
5. Stripe webhook tests cover activation, renewal, failed payment, and cancellation semantics.
6. Desktop and 390/360/320-pixel browser checks show no horizontal overflow.
7. Salmo has no dismiss control and remains available in desktop and mobile navigation.
8. History contains losses and pending states when present, and metrics equal the underlying rows.
9. AdSense markup is complete only when a slot ID exists and is not rendered in prohibited conversion surfaces.
10. Production build has correct Mexico/Spanish metadata and branded icon references.

## 13. Rollout Order

1. Security containment and secret removal.
2. Results/domain tests and safe public/premium data contracts.
3. Membership/payment synchronization.
4. Approved responsive frontend and brand assets.
5. SEO, policy pages, AdSense slots, and analytics.
6. Full automated and browser verification, then controlled deployment.

Deployment, token rotation in provider consoles, Stripe product creation, AdSense approval, and paid-ad certifications require the corresponding external account access. Local implementation must leave each integration fail-closed and documented when those credentials are unavailable.

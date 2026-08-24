# Playdoit Scraper Autonomy Design

**Date:** 2026-08-21  
**Status:** Approved direction, awaiting written-spec review

## Goal

Make the existing Playdoit collector the platform's primary autonomous odds source without requiring another account, paid service, or manual browser intervention. Existing configured APIs remain optional fallbacks only. The scraper must never publish invented, stale, incomplete, or ambiguously identified markets.

This change is limited to collection reliability and operations. It does not modify the frontend, logo palette, Psalms feature, memberships, or supported betting markets.

## Current Baseline

The code already provides the most important market-integrity guarantees:

- stable source event identifiers are required;
- dates and times are resolved in `America/Mexico_City` without hardcoded dates;
- only complete full-game `h2h`, `totals`, and `spreads` markets are accepted;
- supported market tabs are opened sequentially with bounded Selenium waits;
- conflicting event revisions, unnamed prices, unsupported periods, and stale evidence fail closed;
- persistence is idempotent and a resumed batch is delivered before a new scrape starts;
- the browser is closed in a `finally` block.

The remaining weakness is operational visibility. `fase1_escaneo_superficie` uses fixed sleeps, catches broad browser errors, and can turn a blocked page, a changed DOM, and a genuinely empty schedule into the same result: zero events. That makes automatic recovery and useful alerting impossible.

## Chosen Approach

Use a small, explicit source-resilience boundary around Playdoit collection.

Two alternatives were considered and rejected:

1. **API-first collection:** easier to operate, but current free quotas and league restrictions do not cover the product reliably and would return the project to account creation.
2. **Aggressive browser evasion:** could add proxies, challenge solvers, or unbounded browser retries, but would be fragile, difficult to test, and could silently increase failures and maintenance.

The chosen approach keeps the current public-page browser collector, adds bounded recovery and diagnosis, and preserves the existing strict data validators.

## Components

### 1. Source health classification

Add a focused module that represents one Playdoit attempt with a typed status:

- `ok`: at least one structurally valid event was collected;
- `empty_schedule`: the event application rendered normally but exposed no eligible future markets;
- `challenge`: the visible document indicates an access/challenge page;
- `dom_unavailable`: the Playdoit/Altenar application did not render the expected host or shadow root;
- `navigation_error`: Selenium could not load or interact with the page;
- `invalid_events`: records were present but all failed strict normalization.

The diagnostic object contains only status, attempt count, event/rejection counts, and a sanitized error type. It must not contain cookies, page HTML, credentials, API keys, or full exception messages.

### 2. Bounded collection policy

Replace fixed page-load polling with explicit bounded waits. Run at most two Playdoit collection attempts during one scraper execution:

- return immediately on `ok` or a confirmed `empty_schedule`;
- retry once after `dom_unavailable`, `navigation_error`, or `invalid_events`;
- stop immediately on `challenge` so the job does not hammer a blocked page;
- make waiting and sleeping injectable so retry behavior is deterministic in tests;
- reuse or safely recreate the browser only when the failed attempt left it unusable.

Category discovery remains sequential because it mutates one browser page. One category failure is isolated and does not erase valid events already collected.

### 3. Fallback and fail-closed behavior

Playdoit remains the primary source. Existing configured fallback sources may be queried only after Playdoit returns fewer than the existing minimum of verified events. Missing, exhausted, or restricted fallback credentials are treated as unavailable, not as a reason to fabricate data or request another account.

If all sources return no verified candidates:

- do not call the ranking model;
- do not write picks to Supabase;
- do not send public or VIP pick messages;
- return a distinct source-unavailable/no-candidate outcome with the sanitized Playdoit diagnostic.

Previously persisted valid picks are not rewritten or reactivated by a failed collection run.

### 4. Operator visibility

Every run prints one machine-readable, sanitized source-health summary. In production, a non-`ok` terminal Playdoit status sends one concise message to the configured Telegram administrator. Alert delivery is best-effort and cannot turn an otherwise safe no-publication result into a partial publication.

Repeated category-level failures are summarized by count rather than producing noisy individual messages. Dry runs never contact Telegram.

### 5. Browser lifecycle

Browser ownership remains in `LegacyPipeline`. Every successfully created browser is closed exactly once, including failures during navigation, fallback collection, ranking, or persistence. A construction failure is reported without attempting cleanup on a nonexistent driver. Cleanup failures are surfaced without hiding the original collection failure.

No new background service, database table, or paid dependency is introduced.

## Data Flow

1. Resume and deliver any already persisted batch.
2. Create the browser and collect Playdoit with the bounded policy.
3. Strictly normalize and deduplicate source events.
4. If verified coverage is low, query only already-configured fallbacks.
5. Build candidates from supported verified markets.
6. Rank allow-listed candidate IDs and revalidate freshness.
7. Persist atomically, then deliver Telegram messages.
8. Emit the sanitized source-health summary and close every browser resource.

At no point can a diagnostic, fallback response, or model response introduce a factual market field that was not present in a verified source event.

## Error Handling

- Retry only failures classified as transient and only once.
- Never retry a challenge within the same run.
- Preserve `KeyboardInterrupt` and `SystemExit` behavior.
- Keep the first meaningful failure as the primary error if cleanup also fails.
- Convert broad silent exception handling in the collection boundary into explicit statuses while retaining per-event and per-market isolation inside the extractor.
- Redact exception text and configuration values from logs and alerts.

## Testing Strategy

Implementation follows test-driven development:

- unit tests for document-state classification and redaction;
- unit tests proving the retry count, retryable statuses, and immediate challenge cutoff;
- tests proving valid events from an early category survive later category failures;
- pipeline tests proving zero candidates cause zero persistence and zero public delivery;
- lifecycle tests proving every created driver is closed once;
- configuration tests proving no new API key is required;
- existing Playdoit normalization, workflow, publishing, frontend, Deno, typecheck, and build gates remain green;
- a local dry run verifies the operational summary without sending or persisting anything.

## Acceptance Criteria

- Playdoit is attempted first and no new provider account is required.
- A transient browser/DOM failure gets at most one bounded recovery attempt.
- A detected challenge stops Playdoit attempts immediately.
- Empty, blocked, and structurally broken pages are distinguishable in sanitized output.
- No terminal source failure can publish or message a pick.
- Existing APIs are optional fallbacks and absence/exhaustion is safe.
- Browser resources close exactly once on every tested path.
- Frontend behavior, Psalms, logo colors, and supported market scope are unchanged.
- All automated verification gates pass.

## Out of Scope

- new API registrations or paid subscriptions;
- new bookmakers or betting markets;
- proxy rotation, CAPTCHA solving, challenge bypass, or credentialed scraping;
- redesigning the frontend, Psalms, monetization, or customer acquisition;
- guaranteeing uninterrupted access when the upstream site intentionally blocks automated browsers.

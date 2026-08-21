# Scraper Reliability and Market Integrity Design

**Date:** 2026-08-20
**Status:** Direction approved; written-spec review pending
**Scope:** Production scraper, scheduled execution, Supabase publication, and Telegram delivery

## 1. Outcome

Make the Rey Taco Picks scraper safe to run unattended and ensure that every published selection is traceable to a real future event, an available market, and an observed price. The system must fail visibly without exposing or duplicating premium content when configuration, scraping, persistence, or notification delivery fails.

The implementation is intentionally split into two sequential releases:

1. **Reliability and safe operations:** make each run deterministic, idempotent, observable, and correctly configured.
2. **Market integrity and pick quality:** replace free-form market generation with structured, source-backed candidates that AI may rank but cannot invent.

## 2. Success Criteria

A production run is successful only when all of the following are true:

- Required configuration is present and the secure Supabase migration is available.
- Only future events within the configured Mexico City window are considered.
- One active publication batch is created atomically with exactly one public non-parlay pick.
- Every pick records its source event, source market, selection, observed price, and observation time.
- The public JSON and free Telegram channel contain only the public pick.
- VIP and administrator destinations receive only the active batch and do not receive duplicate deliveries on retries.
- Failures return a non-zero process exit code and prevent downstream social publication.
- A dry run exercises the complete pipeline without Supabase writes or Telegram delivery.

## 3. Non-Goals

- Guaranteeing wins, profit, or a specific win rate.
- Automatically placing wagers.
- Supporting every sportsbook or every possible market in the first release.
- Replacing the audited result grader.
- Automating Google AdSense approval or provider-side secret creation.

## 4. Architecture

The current `backend/scraper.py` remains the command entry point but becomes a thin orchestrator. Responsibilities move into focused modules with testable interfaces:

- `backend/scraper_config.py`: resolve repository-relative paths, load `backend/.env` explicitly, validate production configuration, and expose typed settings.
- `backend/scraper_domain.py`: define normalized events, markets, outcomes, candidate picks, publication batches, and validation results.
- `backend/playdoit_source.py`: extract structured events and markets from Playdoit with Selenium explicit waits.
- `backend/odds_source.py`: normalize The Odds API responses without fabricated prices.
- `backend/pick_selection.py`: construct eligible candidates deterministically, apply risk rules, calculate transparent confidence bands, and optionally ask AI to rank or explain candidates.
- `backend/pick_publisher.py`: claim a run, publish a batch atomically, write the public fallback file, and record delivery status.
- `backend/telegram_publisher.py`: format, split, send, retry, and record messages independently per destination.
- `backend/scraper.py`: coordinate phases, report a summary, close Chrome, and return the correct process exit code.

The refactor removes the duplicate phase-7, local-write, and Telegram definitions. There will be one implementation of each production behavior.

## 5. Normalized Data Model

### Event

Each event carries:

- `source`
- `source_event_id`
- `sport`
- `league`
- `home_team`
- `away_team`
- `starts_at` as an aware UTC timestamp
- `observed_at`
- `markets`

Events without a source identifier, two competitors, or a parseable future start time are rejected. A missing date never receives a hardcoded fallback date.

### Market and outcome

Each market carries a stable key such as `h2h`, `total`, or `spread`, its period, line where applicable, and named outcomes. Each outcome contains the source selection name and decimal price. Outcome order is never used to infer the home team.

Prices must be valid decimal odds observed from Playdoit or The Odds API. The current synthetic defaults such as `1.85`, `3.20`, and `2.10` are removed.

### Candidate pick

A candidate references the exact event, market, outcome, price, and observation timestamp from which it was constructed. Its display text is derived from those fields. AI output cannot replace the event, selection, line, or price.

### Publication batch

A batch has a UUID, run key, creation timestamp, source snapshot hash, active flag, and picks. A pick also stores the batch identifier and whether it is public or premium.

## 6. Reliability Release

### Configuration and paths

- Load `backend/.env` using a path based on `__file__`, independent of the current working directory.
- Write `frontend/public/picks.json` using a repository-relative absolute path.
- Production publishing requires `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
- Environment examples and the GitHub workflow use the same canonical names, including `TELEGRAM_ADMIN_ID`.
- `--dry-run` does not require write credentials but clearly labels every skipped side effect.

### Run lifecycle and idempotency

A new Supabase migration adds a run ledger and batch identity. A server-side function claims a unique run key and publishes the batch in one transaction. Retrying the same run key returns the existing batch instead of inserting new picks.

Publishing atomically:

1. Claims the run key.
2. Marks the previous batch inactive without deleting rows needed for grading or history.
3. Inserts the new batch and picks.
4. Enforces exactly one public, active, pending non-parlay pick.
5. Marks the run published.

The subscriber query returns active pending picks plus permitted settled history. Previous inactive pending rows remain available to the grader but do not appear as the current portfolio.

### Failure behavior

- Configuration or schema mismatch fails before Chrome starts.
- No events or no verified candidates produces a failed/no-publication run, not a success report.
- Supabase failure prevents local public-file and Telegram publication.
- Local-file failure is reported but cannot expose premium picks because the payload is constructed through `public_payload`.
- Telegram destinations are attempted independently. One failed destination does not suppress the others.
- Any required delivery failure marks the run partial and returns a non-zero exit code. Retrying sends only missing deliveries.
- Exceptions include the phase and run identifier in structured logs; secrets and full authorization headers are never logged.

### Telegram delivery

- All network calls use bounded timeouts and limited retry with backoff.
- Messages are split below Telegram's message-size limit without separating a pick from its header.
- Administrator, VIP, and free deliveries have independent statuses.
- The free channel receives only `public_payload(batch.picks)`.
- The legacy queue is not recreated and remains ignored.

### Scheduled workflow

- GitHub Actions supplies `SUPABASE_SERVICE_ROLE_KEY` to privileged jobs.
- The scraper waits for the 11 p.m. result-verification job and does not run if verification fails.
- A concurrency group prevents overlapping scheduled or manual scraper runs.
- Social posting uses `if: success()` and therefore cannot advertise a stale or failed batch.
- The workflow timeout remains bounded and a failed scraper step is visible as a failed run.

## 7. Market-Integrity Release

### Playdoit extraction

The extractor collects event identity, competitors, start time, market name, period, selection name, line, and decimal price. It clicks one market tab at a time and waits for the content to change before reading it; it does not click several tabs in a single synchronous JavaScript execution.

Dynamic page selectors are isolated in the Playdoit adapter and covered by saved, sanitized HTML/JSON fixtures. Team names are passed to Selenium scripts as arguments rather than interpolated into JavaScript source.

### Odds API fallback

The adapter preserves named outcomes and source event IDs, converts timestamps with `ZoneInfo("America/Mexico_City")`, and deduplicates quotes by bookmaker, market, line, and outcome. If an outcome is absent, no substitute price is invented.

### Candidate generation

Deterministic code first creates candidates only from supported verified markets:

- Moneyline/three-way result.
- Full-game totals.
- Full-game spread or run line.
- Same-day legs may be grouped for validation experiments, but production does
  not publish a parlay without an independently observed combined price and the
  complete source-audit identity for that parlay.

Unsupported partial periods, player props, corners without complete market data, and ambiguous team totals are skipped until an explicit validator exists.

### AI role

AI receives stable candidate identifiers and supporting facts. It may rank candidates and produce a concise rationale. The final validator accepts only identifiers from the candidate catalog and copies all factual market fields from the deterministic candidate, never from AI text.

If every model fails or returns an invalid candidate identifier, the run exits
without publishing. There is no deterministic or free-form fallback that
invents a ranking from `partidos`.

### Confidence and value language

The displayed confidence value is derived from documented signals such as source agreement, price dispersion, data freshness, and market completeness. It is a ranking aid, not a claimed probability of winning. `tiene_valor` is set only when a source-backed comparison exists; missing comparison data cannot become `+EV` by default.

## 8. Data Flow

`Config validation -> Run claim -> Browser/API collection -> Normalization -> Future-event filter -> Verified candidate construction -> Optional AI ranking -> Final deterministic validation -> Atomic Supabase publication -> Public JSON -> Telegram deliveries -> Run summary`

Every transition returns a typed result with accepted records, rejected records, and reason codes. The final summary reports counts without exposing premium pick text in public logs or artifacts.

## 9. Testing Strategy

Development follows test-driven changes. Each behavior is demonstrated by a failing test before production code changes.

- Unit tests for date rollover, Mexico City timestamps, named outcomes, decimal odds, candidate validation, same-day parlays, confidence bands, message splitting, and path resolution.
- Regression tests for the hardcoded `18/08`, undefined `partidos`, duplicate definitions, working-directory-dependent output, and premium pending accumulation.
- Fixture tests for sanitized Playdoit event and deep-market snapshots.
- Contract tests for The Odds API normalization with reordered and missing outcomes.
- Publisher tests using a fake repository to prove atomic batch lifecycle and idempotent retry semantics.
- Telegram tests with a local fake transport to prove channel isolation, timeouts, retries, and public-only payloads.
- Workflow source tests for service-role configuration, job dependency, concurrency, and success-only social posting.
- A full `--dry-run` smoke test that performs no network writes.
- Existing Python, frontend, Deno, typecheck, build, and browser checks remain required before release.

## 10. Rollout

1. Apply and verify the secure membership migration that creates `public_picks`.
2. Configure `SUPABASE_SERVICE_ROLE_KEY`, canonical Telegram identifiers, and remaining secrets locally and in GitHub Actions.
3. Deploy the reliability release with publishing disabled and run `--dry-run` against current sources.
4. Enable one manual production run and verify the run ledger, active batch, one public pick, VIP payload, and free payload.
5. Observe at least two scheduled runs, including the result-verification dependency.
6. Deploy the market-integrity release and repeat dry-run and one controlled publication.
7. Open the platform to public traffic after the controlled checks pass.

## 11. Estimate and Dependencies

- Reliability release: 4–6 focused engineering hours.
- Market-integrity release: 6–10 focused engineering hours.
- Migration, secret configuration, controlled deployment, and verification: 2–4 hours.
- Expected calendar: 2–3 working days when provider credentials and deployment access are available.

Google AdSense review, payment-provider activation, secret creation, and external platform approvals are outside the code schedule. The site can launch without ads while those reviews continue.

## 12. Acceptance Criteria

1. A production-mode run without a service-role credential or secure schema exits non-zero before browser startup.
2. Running from the repository root or `backend` resolves the same environment and public-file paths.
3. Static analysis reports no undefined names or duplicate top-level scraper definitions.
4. Repeating a run key does not insert another batch or resend completed Telegram deliveries.
5. Exactly one active public pending pick exists and it is not a parlay.
6. Subscriber loading shows only the active pending batch, while the grader can still process inactive pending rows.
7. Every published pick maps to an observed source event, market, selection, price, and timestamp.
8. No fabricated fallback odds remain.
9. AI output containing an unknown selection or altered price is rejected.
10. Telegram failures are isolated, bounded by timeouts, recorded, and visible through a non-zero run result.
11. The free JSON and free Telegram payload never contain premium selections or reasoning.
12. GitHub Actions waits for result verification at 11 p.m., prevents overlap, uses the service-role secret, and skips social posting after failure.
13. The dry-run smoke test and the complete existing test/build suite pass before controlled deployment.

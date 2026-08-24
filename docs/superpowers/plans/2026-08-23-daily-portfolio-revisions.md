# Daily Portfolio Revisions Implementation Plan

> **For Codex:** Execute this plan with the executing-plans and test-driven-development skills. Keep the existing one-run batch RPC available as a compatibility path until the daily workflow is verified.

**Goal:** Combine repeated Mexico-day scans into one private, revisioned portfolio, release only new verified picks, and keep Telegram/social publication idempotent.

**Architecture:** Add a daily portfolio ledger beside the existing per-run ledger. Collection jobs stage a complete ranked draft for the Mexico date. Release jobs atomically keep already released entries, replace only unreleased entries, append the eligible delta to one active daily batch, and return both the full current portfolio and the release delta. Telegram sends the delta; the public JSON is rebuilt from the full portfolio; Meta accepts only the first feed revision for each destination.

**Tech Stack:** Python 3.11, Supabase/PostgreSQL RPCs, GitHub Actions, pytest.

---

## Task 1: Pure daily portfolio contract

**Files:**
- Create: `backend/daily_portfolio.py`
- Create: `tests/test_daily_portfolio.py`

1. Write failing tests for a strict Mexico date, stable audit identity, one physical match per portfolio, six-pick cap, immutable released rows, replacement of unreleased rows, and the one/two-free rule over the complete portfolio.
2. Implement immutable models and validation helpers without network or database access.
3. Run `python -m pytest tests/test_daily_portfolio.py -q`.

## Task 2: Daily persistence adapter

**Files:**
- Modify: `backend/pick_publisher.py`
- Modify: `tests/test_pick_publisher.py`

1. Write failing adapter tests for `stage_daily_pick_portfolio`, `release_daily_pick_portfolio`, and `resume_daily_pick_release` exact RPC arguments.
2. Add typed stage/release responses. A release contains `picks` (full portfolio) and `delivery_picks` (only the immutable delta).
3. Validate the full portfolio against the public policy and the delta as a subset with exact source identities.
4. Write the public JSON from the full portfolio and deliver only the delta.

## Task 3: Atomic Supabase daily ledger

**Files:**
- Create: `supabase/migrations/20260823110000_daily_pick_portfolio_revisions.sql`
- Modify: `tests/test_supabase_contract.py`

1. Create private service-role-only tables for daily portfolios, staged scans, entries, and releases.
2. Implement `stage_daily_pick_portfolio` with a per-date advisory lock. Released entries are immutable; unreleased entries are replaceable; physical matches and audit identities are unique; the active draft is capped at six.
3. Implement `release_daily_pick_portfolio`. The first release creates the active daily batch; later releases append only new rows to it and receive their own `scraper_runs` delivery ledger.
4. Implement `resume_daily_pick_release` so recovery returns the exact full portfolio and exact delivery delta for its run key.
5. Make Meta's batch lookup return content only for the first daily feed revision per destination, retaining exact-run retry behavior.
6. Revoke direct access from anon/authenticated and grant only the required RPCs to `service_role`.

## Task 4: Runtime collection and delivery modes

**Files:**
- Modify: `backend/scraper_config.py`
- Modify: `backend/scraper.py`
- Modify: `tests/test_scraper_cli.py`
- Modify: `tests/test_scraper_pipeline.py`

1. Add explicit `DAILY_PORTFOLIO_ENABLED` and an injected Mexico date; reject malformed values.
2. In daily collect-only mode, stage the ranked draft and do not expose public files or deliver.
3. In daily deliver-only mode, release/resume the exact revision, rebuild public JSON from the full portfolio, and send only `delivery_picks`.
4. Preserve the existing batch path for dry runs and controlled compatibility tests.
5. Return healthy success when a release window has no new eligible picks.

## Task 5: Five background scans and bounded release windows

**Files:**
- Modify: `.github/workflows/collector.yml`
- Modify: `tests/test_scraper_workflow.py`

1. Schedule full scans near 08:00, 12:00, 16:00, 20:00, and 23:00 America/Mexico_City.
2. Stage on all five windows and release only at the approved bounded delivery windows; manual dispatch may stage and release for controlled testing.
3. Keep the stale-run gate, primary/recovery routing, hidden/minimized browser mode, and zero power-control commands.
4. Pass the Mexico date and daily mode without logging secrets.

## Task 6: Verification and review

1. Run focused daily portfolio, publisher, CLI, SQL-contract, workflow, Telegram, and social tests.
2. Run `python -m compileall -q backend tests`.
3. Run `python -m pytest -q` and frontend tests/build.
4. Request a code review and address every concrete finding.
5. Run a controlled dry run with external publication disabled before any real workflow dispatch.

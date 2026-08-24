# Confirmed-Lineup Eligibility Implementation Plan

**Goal:** Make soccer player props eligible only when API-Football supplies an exact fixture match and two confirmed starting elevens, while preserving all team-market candidates and keeping lineup usage at or below 40 requests per UTC day.

**Architecture:** Add a fail-closed `lineup_source` boundary with an injectable HTTP transport, persistent cache, and atomic budget abstraction. Match fixtures using both teams, league compatibility, and kickoff tolerance. Resolve a player by one unambiguous official starter name found in the Playdoit market/selection text, then copy the immutable event with only that market's `lineup_confirmed` flag changed. Wire the resolver into collection before candidates are built. Missing keys, data, coverage, quota, or schema must leave team markets operational and player props ineligible.

**Tech stack:** Python dataclasses, `requests`, Supabase RPC, pytest, GitHub Actions.

---

## Task 1: Configuration and strict API-Football response types

**Files:**
- Create: `backend/lineup_source.py`
- Create: `tests/test_lineup_source.py`
- Modify: `backend/scraper_config.py`
- Modify: `tests/test_scraper_config.py`
- Modify: `.env.example`
- Modify: `backend/.env.example`

1. Write failing tests for API key configuration, exact fixture parsing, complete two-team starting elevens, malformed payloads, provider errors, and quota headers.
2. Implement immutable fixture/lineup records and an injected client using `x-apisports-key`.
3. Verify focused tests.

## Task 2: Shared quota ledger and cache

**Files:**
- Create: `supabase/migrations/20260823090000_api_football_lineup_budget.sql`
- Modify: `backend/lineup_source.py`
- Modify: `tests/test_lineup_source.py`
- Modify: `tests/test_supabase_contract.py`

1. Write failing tests for a 40-request UTC-day cap, cached daily fixture discovery, cached confirmed lineups, provider remaining headers, and atomic Supabase claims.
2. Add service-role-only tables/RPCs for request claims and cached exact responses.
3. Implement local/in-memory test doubles and the production Supabase-backed store.
4. Verify no secret or raw response is logged.

## Task 3: Exact fixture/player matching and immutable event enrichment

**Files:**
- Modify: `backend/lineup_source.py`
- Modify: `tests/test_lineup_source.py`

1. Write failing tests for both-team identity, league compatibility, kickoff tolerance, ambiguous fixtures, predicted/incomplete lineups, ambiguous player names, substitutes, and exact starters.
2. Implement the T-60/T-25 eligibility window and strict resolver.
3. Confirm only matching player markets receive `lineup_confirmed=True`; team markets remain unchanged.

## Task 4: Pipeline and Windows workflow integration

**Files:**
- Modify: `backend/scraper.py`
- Modify: `tests/test_scraper_cli.py`
- Modify: `.github/workflows/collector.yml`
- Modify: `.github/workflows/scraper.yml`

1. Write failing tests showing enrichment happens before `build_candidates`, no key leaves team picks working, and dry-run reports lineup usage without external writes.
2. Build the production resolver from scraper settings/Supabase and pass it into Playdoit event projection.
3. Add `API_FOOTBALL_KEY` to both residential collector jobs without exposing it.
4. Verify runner behavior remains minimized and never changes power state.

## Task 5: Verification and review

1. Run lineup/config/pipeline/Supabase contract tests.
2. Run the complete Python suite, compilation, frontend tests/build, and scoped diff checks.
3. Run one safe Playdoit dry-run and verify zero persistence/Telegram/Meta delivery.
4. Request a focused code review and resolve every valid finding.
5. Commit only the lineup phase files; do not include unrelated user changes.

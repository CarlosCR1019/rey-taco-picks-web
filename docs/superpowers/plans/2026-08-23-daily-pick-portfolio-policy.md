# Daily Pick Portfolio Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish at most six strong picks per run, never more than one pick from the same physical match, with one free pick for batches of one to five and two free picks for a six-pick batch.

**Architecture:** Keep the AI ranking limit of twelve as an untrusted-input boundary, then apply a deterministic portfolio selector before evidence scoring and publication. Centralize the public-count rule in the publishing policy, enforce it again in Python response validation, and add a forward-only Supabase migration that replaces the historical one-public database contract without rewriting deployed migrations.

**Tech Stack:** Python 3.11, pytest, PostgreSQL/Supabase PL/pgSQL, GitHub Actions.

---

### Task 1: Deterministic Daily Portfolio

**Files:**
- Modify: `backend/pick_selection.py`
- Modify: `backend/scraper.py`
- Test: `tests/test_pick_selection.py`
- Test: `tests/test_scraper_pipeline.py`

- [ ] **Step 1: Write failing selector tests**

Add tests that build ranked candidates from seven distinct events and assert that `select_daily_portfolio()` preserves ranking order and returns the first six. Add a second test with two different markets for the same physical match and assert that only the highest-ranked one survives.

- [ ] **Step 2: Verify the selector tests fail**

Run: `python -m pytest tests/test_pick_selection.py -k daily_portfolio -q`

Expected: collection fails because `select_daily_portfolio` does not exist.

- [ ] **Step 3: Implement the selector**

Add `MAX_DAILY_PICKS = 6` and `select_daily_portfolio(ranked)` to `backend/pick_selection.py`. Materialize untrusted input fail-closed, accept only `RankedPick`, preserve its order, skip any candidate for which `_same_physical_event()` matches an already selected candidate, and stop at six.

- [ ] **Step 4: Verify the selector tests pass**

Run: `python -m pytest tests/test_pick_selection.py -k daily_portfolio -q`

Expected: all selected tests pass.

- [ ] **Step 5: Write failing pipeline tests**

Add a structured-pipeline test whose ranker returns seven different events and another with two markets from one match. Assert `pick_count <= 6`, exactly one candidate per physical match, and that the publisher receives the same rows exposed by `PipelineResult.picks`.

- [ ] **Step 6: Verify the pipeline tests fail**

Run: `python -m pytest tests/test_scraper_pipeline.py -k daily_portfolio -q`

Expected: the current pipeline sends more than six or more than one selection per match.

- [ ] **Step 7: Apply the selector at both ranking entry points**

Call `select_daily_portfolio(validate_ai_ranking(...))` in `_fase6_candidate_ranking()` and `run_structured_pipeline()`. Update the AI prompt to request a target of four, normally three to five, never more than six, and zero instead of weak picks; retain the twelve-item JSON schema ceiling as an input-safety bound.

- [ ] **Step 8: Run selection and pipeline tests**

Run: `python -m pytest tests/test_pick_selection.py tests/test_scraper_pipeline.py -q`

Expected: all tests pass.

### Task 2: Free/Premium Visibility Contract

**Files:**
- Modify: `backend/publishing_policy.py`
- Modify: `backend/pick_publisher.py`
- Modify: `backend/scraper.py`
- Test: `tests/test_publishing_policy.py`
- Test: `tests/test_pick_publisher.py`
- Test: `tests/test_scraper_pipeline.py`

- [ ] **Step 1: Write failing publishing-policy tests**

Add cases for zero, one through five, and six picks. Assert one public row for one through five, two public rows for six, no public parlay, public rows from distinct source-event identities, input immutability, and all other rows premium.

- [ ] **Step 2: Verify policy tests fail**

Run: `python -m pytest tests/test_publishing_policy.py -q`

Expected: the six-pick case receives only one public row.

- [ ] **Step 3: Implement the centralized count policy**

Add `expected_public_pick_count(total)` and a private physical-event identity helper to `backend/publishing_policy.py`. Update `assign_visibility()` to deep-copy rows and select the required number of non-parlay public rows from different source events; leave an incomplete selection fail-closed for downstream validation.

- [ ] **Step 4: Verify policy tests pass**

Run: `python -m pytest tests/test_publishing_policy.py -q`

Expected: all tests pass.

- [ ] **Step 5: Write failing response-validation tests**

Add persisted-response tests that accept two public non-parlay picks in a six-row batch, reject one or three public rows in a six-row batch, reject more than six rows, and reject duplicate public source-event identities.

- [ ] **Step 6: Verify validation tests fail**

Run: `python -m pytest tests/test_pick_publisher.py -k public_policy -q`

Expected: the valid six-row response is rejected by the historical exact-one rule.

- [ ] **Step 7: Harden Python validators**

Use `expected_public_pick_count()` in `_validated_persisted_picks()` and `_valid_visible_source_rows()`. Require one to six rows, exact public count, every public row to be non-parlay and rationale-free after persistence, and distinct `(source, source_event_id)` identities for public rows.

- [ ] **Step 8: Run publishing tests**

Run: `python -m pytest tests/test_publishing_policy.py tests/test_pick_publisher.py tests/test_scraper_pipeline.py -q`

Expected: all tests pass.

### Task 3: Forward-Only Supabase Migration

**Files:**
- Create: `supabase/migrations/20260823100000_six_pick_portfolio_policy.sql`
- Modify: `tests/test_supabase_contract.py`

- [ ] **Step 1: Write failing SQL contract tests**

Assert that the new migration is transactional, removes `picks_one_public_pending_idx`, validates one-to-six input rows, computes two public rows only for six picks, rejects public parlays and duplicate public source events, replaces `public.publish_pick_batch(text,text,jsonb)`, and grants execution only to `service_role`.

- [ ] **Step 2: Verify SQL contract tests fail**

Run: `python -m pytest tests/test_supabase_contract.py -k six_pick_portfolio -q`

Expected: failure because the migration does not exist.

- [ ] **Step 3: Add the migration**

Create a forward-only migration that drops the obsolete unique index and replaces the latest audited `publish_pick_batch` implementation with the same source-audit, freshness, locking, idempotency, replacement and return contracts, changing only the bounded batch/public-count checks. Add a constraint trigger that prevents more than two active public pending picks per batch, while the RPC enforces the exact count for each new batch.

- [ ] **Step 4: Verify SQL contract tests pass**

Run: `python -m pytest tests/test_supabase_contract.py -q`

Expected: all tests pass, including historical migration assertions.

### Task 4: Integrated Verification and Commit

**Files:**
- Verify all modified files above.

- [ ] **Step 1: Run focused regression tests**

Run: `python -m pytest tests/test_pick_selection.py tests/test_publishing_policy.py tests/test_pick_publisher.py tests/test_scraper_pipeline.py tests/test_supabase_contract.py -q`

Expected: all tests pass.

- [ ] **Step 2: Run syntax verification**

Run: `python -m compileall -q backend tests`

Expected: exit code 0.

- [ ] **Step 3: Run the complete suite**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 4: Review the diff and repository status**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors; `.gitignore` and unrelated existing untracked work remain unstaged.

- [ ] **Step 5: Commit only the portfolio work**

Run: `git add backend/pick_selection.py backend/publishing_policy.py backend/pick_publisher.py backend/scraper.py tests/test_pick_selection.py tests/test_publishing_policy.py tests/test_pick_publisher.py tests/test_scraper_pipeline.py tests/test_supabase_contract.py supabase/migrations/20260823100000_six_pick_portfolio_policy.sql docs/superpowers/plans/2026-08-23-daily-pick-portfolio-policy.md && git commit -m "feat: enforce six-pick daily portfolio"`

Expected: a commit containing only this approved policy block.

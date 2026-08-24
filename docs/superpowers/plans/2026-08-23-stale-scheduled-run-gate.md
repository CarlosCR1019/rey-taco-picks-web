# Stale Scheduled Run Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scheduled residential jobs exit safely without Chrome, scraping, persistence, Telegram, or Meta when a self-hosted PC starts them more than twenty minutes late.

**Architecture:** A small pure-Python gate validates GitHub's authoritative run `created_at` timestamp against the current UTC time and emits a bounded exit code. The collector workflow queries its own run through the GitHub Actions API, invokes the gate, and conditions both dependency installation and collection on the gate output; manual dispatch remains eligible and separate.

**Tech Stack:** Python 3.11, pytest, GitHub Actions, PowerShell.

---

### Task 1: Pure Scheduling Gate

**Files:**
- Create: `backend/adaptive_schedule.py`
- Create: `tests/test_adaptive_schedule.py`

- [ ] **Step 1: Write failing timestamp tests**

Cover an exact twenty-minute delay, a delay greater than twenty minutes, a future timestamp, a timezone offset, a naive timestamp, invalid text, and manual dispatch. Scheduled timestamps are eligible only when aware, not in the future, and no older than twenty minutes; manual dispatch bypasses age because it is an explicit action.

- [ ] **Step 2: Verify tests fail**

Run: `python -m pytest tests/test_adaptive_schedule.py -q`

Expected: import failure because `backend.adaptive_schedule` does not exist.

- [ ] **Step 3: Implement the pure decision**

Create `scheduled_run_is_eligible(created_at, now, event_name, max_age_minutes=20)`. Reject wrong types, unsupported event names, naive datetimes, negative/future age, boolean minute limits, and limits outside 1-60. Return `True` for `workflow_dispatch`; parse GitHub ISO-8601 `Z` timestamps without network or ambient time when `now` is injected.

- [ ] **Step 4: Add a bounded CLI**

`python -m backend.adaptive_schedule --event-name schedule --created-at 2026-08-23T16:00:00Z` exits `0` when eligible, `3` when stale, and `2` for malformed arguments. It prints only `collection_window=eligible`, `collection_window=stale`, or `collection_window=invalid`.

- [ ] **Step 5: Run the unit tests**

Run: `python -m pytest tests/test_adaptive_schedule.py -q`

Expected: all tests pass.

### Task 2: Collector Workflow Integration

**Files:**
- Modify: `.github/workflows/collector.yml`
- Modify: `tests/test_scraper_workflow.py`

- [ ] **Step 1: Write failing workflow contract tests**

Assert `actions: read`, the GitHub run API path, bearer authentication without logging the token, a `collection_window` step on both residential jobs, output-based conditions on dependency installation and collection, manual dispatch support, and no `shutdown`, `sleep`, or power-setting commands.

- [ ] **Step 2: Verify workflow tests fail**

Run: `python -m pytest tests/test_scraper_workflow.py -k stale -q`

Expected: assertions fail because the gate is not wired.

- [ ] **Step 3: Wire the gate fail-closed**

Grant `actions: read`. After checkout and Python setup, query `https://api.github.com/repos/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID` with `GITHUB_TOKEN`. Pass only `created_at` and `GITHUB_EVENT_NAME` to the Python gate. Write `eligible=true` only on exit `0`; write `eligible=false` on exit `3` or API failure; reject unexpected exit codes. Condition dependency installation and scraper execution on `eligible == 'true'` in both primary and recovery jobs.

- [ ] **Step 4: Run workflow and gate tests**

Run: `python -m pytest tests/test_adaptive_schedule.py tests/test_scraper_workflow.py -q`

Expected: all tests pass.

### Task 3: Verification and Commit

**Files:**
- Verify all files above.

- [ ] **Step 1: Run syntax and focused tests**

Run: `python -m compileall -q backend tests && python -m pytest tests/test_adaptive_schedule.py tests/test_scraper_workflow.py -q`

Expected: exit code 0.

- [ ] **Step 2: Run complete test suite**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Review and commit only this block**

Run: `git diff --check`, stage the four files plus this plan, and commit with `git commit -m "feat: skip stale residential collection jobs"`.

Expected: unrelated `.gitignore` and old plan remain unstaged.

# Pre-Scrape Batch Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resume an active completed scraper batch and only its missing deliveries before any browser, source, or AI work starts.

**Architecture:** Add a server-only `resume_pick_batch(text)` RPC that returns either no completed run or the active batch's exact persisted rows and delivery ledger. Reuse the publisher's strict response validator and safe public-file writer, then extract the existing Telegram delivery code so both fresh publication and resume consume the same persisted `PublicationResult`. The workflow receives a stdout marker from the scraper step and skips social auto-posting for resume-only runs.

**Tech Stack:** Python 3.11+, PostgreSQL/Supabase PL/pgSQL, pytest, GitHub Actions YAML, Vitest/TypeScript, Deno.

---

### Task 1: Define and validate the resume boundary

**Files:**
- Modify: `tests/test_pick_publisher.py`
- Modify: `backend/pick_publisher.py`

- [ ] **Step 1: Write failing repository/adapter tests**

Add tests proving `SupabaseBatchRepository.resume("run-1")` calls `resume_pick_batch` with `requested_run_key`, accepts `None`, rejects malformed/created-true responses, freezes valid persisted rows, and that `AuditedBatchPublisher.resume(dry_run=False)` rewrites the public file from persisted public rows. Add a dry-run test proving no repository call.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_pick_publisher.py -k resume -q`
Expected: FAIL because `resume` methods do not exist.

- [ ] **Step 3: Implement the minimal typed boundary**

Extend `BatchRepository` with:

```python
def resume(self, run_key: str) -> PublishResponse | None: ...
```

Implement the Supabase RPC call, reuse `_normalized_publish_response`, require `created is False`, and add `AuditedBatchPublisher.resume(*, dry_run: bool)` that never queries on dry-run and writes `_safe_public_payload(result.picks)` only after strict validation.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_pick_publisher.py -q`
Expected: PASS.

### Task 2: Resume before Chrome and share persisted delivery logic

**Files:**
- Modify: `tests/test_scraper_cli.py`
- Modify: `tests/test_scraper_structure.py`
- Modify: `backend/scraper.py`
- Modify: `.github/workflows/scraper.yml`

- [ ] **Step 1: Write failing production-path tests**

Cover: active partial resume with an exploding driver factory and empty sources; only the missing Telegram destination receives old persisted text; all-success resume sends nothing; absent run continues the normal scrape; inactive/malformed resume fails before driver/file/delivery; dry-run never calls repository resume. Assert `resume_only=true` is emitted and workflow social step requires `steps.scraper.outputs.resumed != 'true'`.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_scraper_cli.py tests/test_scraper_structure.py -k "resume or dry_run" -q`
Expected: FAIL because production always constructs Chrome first.

- [ ] **Step 3: Extract persisted delivery and add pre-scrape branch**

Extract `_deliver_persisted_publication(publication, repository, settings, transport=None)` from phase 7. At the beginning of non-dry `LegacyPipeline.run`, call `AuditedBatchPublisher.resume`; on a result, deliver only missing destinations and return a persisted `PipelineResult` with immutable persisted picks without constructing a driver. Convert resume errors to sanitized `PersistenceFailure`.

- [ ] **Step 4: Expose resume-only workflow output**

Make the scraper print exactly `resume_only=true`. Give the workflow scraper step an `id`, capture its exit status/output with `tee`, set `resumed=true|false` on `$GITHUB_OUTPUT`, and gate social posting with:

```yaml
if: success() && steps.scraper.outputs.resumed != 'true'
```

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/test_scraper_cli.py tests/test_scraper_structure.py -q`
Expected: PASS.

### Task 3: Install and probe the secure resume RPC

**Files:**
- Modify: `tests/test_supabase_contract.py`
- Modify: `supabase/migrations/20260820233000_scraper_run_ledger.sql`
- Modify: `supabase/migrations/20260820234500_pick_source_audit.sql`

- [ ] **Step 1: Write failing SQL contract tests**

Assert both migrations define `resume_pick_batch(text)` as `SECURITY DEFINER` with fixed search path, service-role-only ACL, completed-status check, active-batch requirement, and exact persisted row allow-list. Assert final schema probe validates signature/security/ACL/body. Assert both `publish_pick_batch` replay branches load `active` and reject inactive/superseded batches before returning rows.

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_supabase_contract.py -k "resume or superseded" -q`
Expected: FAIL because the RPC and active replay guard do not exist.

- [ ] **Step 3: Implement SQL fail-closed behavior**

Create `resume_pick_batch(requested_run_key text) returns jsonb`. Return SQL `null` only when no completed run exists. For `published`/`partial`, lock consistently, load the batch, raise `scraper run batch is inactive or superseded` unless it is active, aggregate the exact returned columns, and raise if rows are absent. Apply the same active guard to `publish_pick_batch` replay. Revoke all from public/anon/authenticated and grant only service role. Extend both probes, with the final v2 probe checking the secure definition.

- [ ] **Step 4: Verify GREEN**

Run: `python -m pytest tests/test_supabase_contract.py -q`
Expected: PASS.

### Task 4: Documentation and complete verification

**Files:**
- Modify: `tests/test_source_security.py`
- Modify: `docs/operations/security-and-payments.md`

- [ ] **Step 1: Write and verify a failing documentation contract**

Require the runbook to state that active completed runs resume before source collection and that inactive/superseded batches fail closed without restoring public or Telegram output.

- [ ] **Step 2: Update the runbook and verify GREEN**

Run: `python -m pytest tests/test_source_security.py -q`
Expected: PASS.

- [ ] **Step 3: Run the full gate**

Run Python, frontend tests/typecheck/build, Deno fallback, focused mypy/pyflakes, and `git diff --check`. Do not execute live sources or remote Supabase.

- [ ] **Step 4: Commit**

Commit: `fix: resume active batches before scraping`

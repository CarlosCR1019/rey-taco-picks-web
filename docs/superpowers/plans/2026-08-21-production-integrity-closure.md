# Production Integrity Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining time-of-check, retry, schema-bootstrap, notification, workflow, banner-date, and documentation gaps without any live publication.

**Architecture:** Keep normalized sportsbook candidates as the only factual source and revalidate their clock at both sides of the AI boundary. Make PostgreSQL the authority for idempotent retry contents: the publisher consumes rows returned by the RPC, and downstream file/Telegram publication never reuses newly scraped rows for an existing completed run. Add a pre-membership baseline migration so a blank Supabase database reaches the same schema as an upgrade.

**Tech Stack:** Python 3.14, pytest, PostgreSQL/Supabase migrations, GitHub Actions YAML, Vitest/TypeScript, HTML banner rendering.

---

### Task 1: Revalidate live candidates and preserve event dates

**Files:**
- Modify: `backend/scraper.py`
- Test: `tests/test_odds_source.py`
- Test: `tests/test_scraper_pipeline.py`
- Test: `tests/test_scraper_structure.py`

- [ ] **Step 1: Write failing clock and midnight tests**

```python
def test_phase6_omits_candidate_that_starts_while_ranker_is_running(monkeypatch):
    clock = iter((before_start, after_start))
    monkeypatch.setattr(scraper, "_utc_now", lambda: next(clock))
    assert scraper.fase6_analisis_final(..., reference_at=None) == []

def test_candidate_projection_keeps_mexico_event_date_across_midnight(...):
    assert projected["fecha_evento"] == "2026-08-21"
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/test_odds_source.py tests/test_scraper_pipeline.py -q`
Expected: stale candidate is still projected or `fecha_evento` is recomputed from the later phase-7 clock.

- [ ] **Step 3: Add a clock seam and two-sided validation**

```python
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

catalog_reference = reference_at if reference_at is not None else _utc_now()
prompt_candidates = [c for c in candidates if c.starts_at > catalog_reference]
# after Groq returns
projection_reference = reference_at if reference_at is not None else _utc_now()
ranked = [row for row in ranked if row.candidate.starts_at > projection_reference]
```

Project `fecha_evento` from `candidate.starts_at.astimezone(ZoneInfo("America/Mexico_City")).date()` and make phase 7 preserve a valid supplied date.

- [ ] **Step 4: Run focused tests and commit**

Run: `python -m pytest tests/test_odds_source.py tests/test_scraper_pipeline.py tests/test_scraper_structure.py -q`
Expected: PASS.

Commit: `fix: revalidate live production picks`

### Task 2: Resume the persisted batch rather than a new scrape

**Files:**
- Modify: `backend/pick_publisher.py`
- Modify: `backend/scraper.py`
- Modify: `supabase/migrations/20260820233000_scraper_run_ledger.sql`
- Modify: `supabase/migrations/20260820234500_pick_source_audit.sql`
- Test: `tests/test_pick_publisher.py`
- Test: `tests/test_scraper_structure.py`
- Test: `tests/test_supabase_contract.py`

- [ ] **Step 1: Write failing retry and hostile-response tests**

```python
def test_replay_uses_persisted_rows_for_file_and_missing_delivery(...):
    response = {"created": False, "picks": OLD_PERSISTED_ROWS, ...}
    publication, deliveries = fase7_guardar_y_notificar(NEW_ROWS, ...)
    assert json.loads(public_file.read_text()) == [OLD_PUBLIC_ROW]
    assert sent_rows == OLD_PERSISTED_ROWS
    assert set(deliveries) == {"vip"}

@pytest.mark.parametrize("bad_picks", [None, "rows", [{}], [{"source": ""}]])
def test_rpc_response_rejects_invalid_persisted_picks(bad_picks): ...
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/test_pick_publisher.py tests/test_scraper_structure.py tests/test_supabase_contract.py -q`
Expected: response has no `picks`, file and Telegram use requested rows, and SQL checks hash before replay.

- [ ] **Step 3: Extend the strict publisher result**

```python
class PublishResponse(TypedDict):
    picks: tuple[dict[str, object], ...]

@dataclass(frozen=True)
class PublicationResult:
    picks: tuple[FrozenPersistedPick, ...]
```

Validate list shape, scalar values, exact allow-list, five audit fields, exactly one public non-parlay row, and copy/freeze defensively. Write `public_payload(result.picks)` and make phase 7 deliver `publication.picks` only.

- [ ] **Step 4: Make the RPC replay authoritative**

Before the source-hash mismatch guard, return completed-run rows selected by the claimed batch in stable ID order. Return the newly inserted database rows on creation too. Preserve the hash guard for `running` and `failed` runs.

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/test_pick_publisher.py tests/test_scraper_structure.py tests/test_supabase_contract.py -q`
Expected: PASS.

Commit: `fix: resume persisted scraper deliveries`

### Task 3: Close database, reporting, workflow, banner, and documentation gaps

**Files:**
- Create: `supabase/migrations/20260820210000_base_profiles_and_picks.sql`
- Modify: `supabase/migrations/20260820234500_pick_source_audit.sql`
- Modify: `send_telegram_status_report.py`
- Modify: `backend/social_poster.py`
- Modify: `backend/render_html_banner.py`
- Modify: `backend/social_banner.py`
- Modify: `.github/workflows/scraper.yml`
- Modify: `docs/operations/security-and-payments.md`
- Modify: `docs/superpowers/specs/2026-08-20-scraper-reliability-and-market-integrity-design.md`
- Test: `tests/test_supabase_contract.py`
- Test: `tests/test_telegram_status_report.py`
- Test: `tests/test_render_html_banner.py`
- Test: `tests/test_source_security.py`

- [ ] **Step 1: Write failing contracts**

```python
def test_blank_database_has_profiles_and_picks_before_membership(): ...
def test_audited_source_fields_cannot_change_or_downgrade(): ...
def test_status_report_queries_only_active_pending_and_redacts_free(): ...
def test_backend_modules_run_from_repository_root(): ...
def test_banner_month_is_derived_in_spanish(): ...
def test_docs_do_not_claim_live_parlay_publication(): ...
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/test_supabase_contract.py tests/test_telegram_status_report.py tests/test_render_html_banner.py tests/test_source_security.py -q`
Expected: missing base migration, mutable audit fields, shared Telegram payload, root import failure, fixed August, and incorrect docs.

- [ ] **Step 3: Add the idempotent baseline migration**

Create `profiles` with `id uuid primary key references auth.users(id) on delete cascade` and the profile fields used by membership. Create `picks` with every column consumed by membership, ledger, audit, results, frontend, and Telegram, then use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for upgrade compatibility. Do not delete or rewrite existing rows.

- [ ] **Step 4: Enforce audit immutability and reporting privacy**

Raise from the audit trigger when an audited row changes any of the five source fields or downgrades `source_audit_version`. Query only `active=true AND estado='pendiente'`; build separate admin/VIP and free messages, with free rows restricted to `visibility='public'` and rationale removed.

- [ ] **Step 5: Fix root module execution and dynamic Spanish dates**

Use package imports (`from backend.render_html_banner ...`) and workflow module execution (`python -m backend.social_poster`). Derive Spanish month names from the supplied/current datetime in both banner implementations.

- [ ] **Step 6: Correct operational documentation**

State that parlay legs may be validated/grouped but production does not publish a parlay without its own independently observed price and five-field source audit. Document baseline migration order and replay-from-persisted-row behavior.

- [ ] **Step 7: Verify and commit**

Run: `python -m pytest -q`, `npm test`, `npm run build`, `deno test` when available, `python -m pyflakes ...`, and `git diff --check`.
Expected: all available checks PASS; Deno absence is reported rather than hidden.

Commit: `fix: close production integration gaps`

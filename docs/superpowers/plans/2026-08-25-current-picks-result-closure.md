# Current Picks Result Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settle the two current picks from final evidence and publish exactly one complete result report with the matching original ticket, without duplicates or guessed scores.

**Architecture:** Use the already deployed `scraper.yml` result-verifier workflow as the only writer. First allow automatic audited sources to settle the picks; if a source cannot prove a final, leave it pending and collect a narrowly scoped independent result URL for the existing manual-evidence input rather than editing Supabase directly. Verify idempotency through workflow logs and stored delivery receipts.

**Tech Stack:** GitHub Actions CLI, Python result verifier, Supabase service boundary, API-Football/independent HTTPS result evidence, Telegram and Meta delivery receipts.

---

### Task 1: Capture the exact pre-run state

**Files:**
- Read only: `.github/workflows/scraper.yml`
- Read only: `backend/verificar_resultados.py`
- Read only: `backend/manual_result_evidence.py`

- [ ] **Step 1: Confirm the workflow and branch**

Run:

```powershell
git branch --show-current
gh workflow view scraper.yml
```

Expected: branch is `master`; workflow exposes optional `manual_result_evidence_json` and runs `backend/verificar_resultados.py`.

- [ ] **Step 2: Inspect the latest result run before dispatching**

Run:

```powershell
gh run list --workflow scraper.yml --limit 5 --json databaseId,status,conclusion,createdAt,headSha,event
```

Expected: valid JSON list. Record the newest run ID and conclusion so the new run cannot be confused with an older report.

- [ ] **Step 3: Record the two current pending identities with a read-only query**

Run only in the configured shell where `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are already loaded:

```powershell
python -c "import json,os; from supabase import create_client; c=create_client(os.environ['SUPABASE_URL'],os.environ['SUPABASE_SERVICE_ROLE_KEY']); rows=c.table('picks').select('id,partido,pick,fecha_evento,horario,estado,visibility,source,source_event_id').eq('estado','pendiente').order('id',desc=True).execute().data; print(json.dumps(rows,ensure_ascii=False,indent=2))"
```

Confirm the target set contains the two still-current picks and do not update any row manually.

Expected at the design checkpoint: the set includes the current Defensor Sporting vs Rentistas and Bucaramanga vs Rionegro Águilas selections unless an automatic run has already settled them.

### Task 2: Run automatic fail-closed verification

**Files:**
- No file changes

- [ ] **Step 1: Wait until both events can reasonably be final**

At the planning checkpoint (15:37 CDMX), Defensor Sporting vs Rentistas had only just reached its scheduled start window and Bucaramanga vs Rionegro Águilas was scheduled for 17:00 CDMX. Do not attempt a final report before 19:30 CDMX. A verifier may run earlier, but a still-pending result is expected and must not be converted manually.

- [ ] **Step 2: Dispatch the existing verifier without manual evidence after 19:30 CDMX**

Run:

```powershell
gh workflow run scraper.yml --ref master
Start-Sleep -Seconds 3
$run = gh run list --workflow scraper.yml --event workflow_dispatch --limit 1 --json databaseId | ConvertFrom-Json
$runId = $run[0].databaseId
gh run watch $runId --exit-status
```

Expected: GitHub Actions completes successfully. A successful run may legitimately leave a pick pending if final evidence is unavailable.

- [ ] **Step 3: Inspect verifier and delivery evidence**

Run:

```powershell
gh run view $runId --log | Select-String -Pattern 'actualizados=|result_report|receipt|pending|revision|ganado|perdido|void'
```

Expected: logs identify updates and report disposition without printing secrets.

- [ ] **Step 4: Re-query only the two captured IDs**

Expected outcomes:

- both are in `ganado`, `perdido`, `void`, or `revision_pendiente`; continue to Task 3;
- either remains `pendiente`; leave it unchanged, report the missing evidence, and stop the closure plan. Once an exact independent final HTTPS page exists, write a separate evidence-specific plan containing the literal event names, scores, date, source name, and source URL before invoking `manual_result_evidence_json`. Never use a generic or partially filled payload.

### Task 3: Verify one complete report and original ticket

**Files:**
- No source changes

- [ ] **Step 1: Confirm the result set is complete**

Query the same portfolio/date used by the report. Expected: no `pendiente` rows in the target report and every row has `resultado_verificado_at`, `resultado_fuente`, and a valid final state.

- [ ] **Step 2: Confirm the report delivery receipt**

Inspect the successful run log and the existing result-report receipt relation. Expected: exactly one terminal success receipt per configured destination for the report digest.

- [ ] **Step 3: Confirm original ticket evidence**

Inspect the ticket-evidence decision and vertical-media receipt. Expected: a matched original Telegram JPEG is used when its ticket ID and picks match the completed report; its ID remains visible and no generated replacement is substituted.

- [ ] **Step 4: Prove idempotency with a second verifier run**

Dispatch `scraper.yml` once more without manual evidence and watch it to completion. Expected: zero result transitions for the already settled picks and report/ticket delivery is skipped as already complete; no second Meta or Telegram receipt is created for the same digest.

- [ ] **Step 5: Validate public presentation**

Open the deployed page after the frontend plan is released. Expected: the settled picks appear in their correct six-hour blocks until midnight CDMX, all settled results appear in history, and the matching original image is available in the Muro de victorias.

## Self-review result

- Spec coverage: final evidence, fail-closed behavior, single report, original ticket, receipt verification, and duplicate prevention are all explicit.
- Placeholder scan: no illustrative result payload remains; a missing automatic result stops this plan instead of inviting partially filled manual evidence.
- Type consistency: the manual evidence keys match `_validated_evidence` and every workflow invocation uses the existing `manual_result_evidence_json` input.

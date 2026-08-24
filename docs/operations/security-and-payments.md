# Security and payments runbook

## Required configuration

Keep real values in provider secret stores, never in Git.

- Backend: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ADMIN_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`, `TELEGRAM_FREE_CHANNEL_ID`, `TELEGRAM_VIP_CHANNEL_ID`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `SITE_URL`.
- Frontend build: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_TELEGRAM_BOT_USERNAME`, and optionally `VITE_ADSENSE_CLIENT`, `VITE_ADSENSE_SLOT`.
The Supabase anonymous key is public by design. VIP secrecy depends on deploying the RLS migration before publishing the new frontend.

## Deployment order

1. Rotate any Telegram, Meta, Stripe, or Supabase service credential that has ever appeared in source history.
2. Apply the pending migrations in timestamp order, beginning with
   `supabase/migrations/20260820210000_base_profiles_picks.sql` and then
   `supabase/migrations/20260820220000_secure_membership.sql`.
   Purge any legacy `backend/channel_queue.json` on the running host before restarting `telegram_dispatcher.py`.
3. Verify an anonymous query returns only the one public pending pick and settled history. Verify a signed free account cannot read pending premium rows.
4. Create a recurring Stripe price for `$299 MXN` and store its identifier in `STRIPE_PRICE_ID`.
5. Deploy `create-checkout`, `create-portal`, and `stripe-webhook` with their server secrets.
6. Configure the Stripe webhook endpoint for `checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`, `customer.subscription.updated`, and `customer.subscription.deleted`.
7. Build the frontend with the public Supabase configuration. Add AdSense variables only after Google supplies a real slot.

## SPEI operations

- Receipts go to `backend/private_receipts/`, which is ignored by Git and never copied to `dist`.
- OCR may flag amount/bank text but always creates `pending_review`.
- Confirm the deposit in the bank independently. Then `/vip REVISION_UUID correo@ejemplo.com` atomically approves that review and creates or extends a 30-day `spei` subscription.
- Use `/rechazar REVISION_UUID` for an invalid receipt. Both decisions record `reviewed_by` and `reviewed_at`.
- Do not use `/aprobar` as a substitute for membership; it only handles a Telegram join request.

## Promotional access

- An authenticated admin generates a code with `select public.create_promo_code(7, now() + interval '14 days', 100);`.
- The raw code is returned only to the admin. The database stores its SHA-256 hash, expiry, access days, usage limit, and usage count.
- Customers redeem it from **Mi cuenta**. Redemption is transactional and the same account cannot use the same code twice.

## Controlled scraper rollout

### Verified market scope

The structured pipeline supports only markets for which it can preserve the
source event, market, selection, observation time, bookmaker, and exact decimal
price from collection through publication:

- Full-game moneyline/H2H.
- Full-game totals.
- Full-game spreads, including baseball run lines.

The validator can group individually verified same-day legs for analysis, but
**no publica parlays en producción**. A parlay cannot enter the production
catalog until its combined **cuota independiente** is observed from a source and
the parlay itself carries the **seis campos de auditoría** required of every
published selection: `source`, `source_event_id`, `source_market_key`,
`source_selection_key`, `source_observed_at`, and `source_starts_at`. The last
field is the event's **instante absoluto UTC**, not a display date or human
schedule. Leg prices must never be multiplied to invent that quote.

The pipeline rejects partial periods, halves, quarters, unsupported player
props, incomplete corner markets, ambiguous team totals, and every other market
without a dedicated normalizer, validator, and result grader. Missing or
ambiguous evidence must produce no candidate; it must never be replaced with a
synthetic selection or price.

`confianza` is displayed as **Respaldo de datos**. It is a bounded operational
score derived from source agreement, price dispersion, freshness, and market
completeness; it is not a probability of winning. `tiene_valor` indicates only
that a qualifying comparison between independent source/bookmaker quotes exists.
It does not claim positive expected value or guarantee profit.

The schema-v2/source-audit, Meta ledger and hardened pick-policy migrations were
applied to the confirmed production project on 22 August 2026. The anonymous
surface was rechecked after migration: direct reads expose settled public rows
only and anonymous insert, update and delete privileges are absent.

### Current state and hard stops

The production service-role secret is configured in the private GitHub
repository. The residential collector has **not** been dispatched yet. Do not
publish until at least one Windows runner is registered, both available PCs have
passed `Invoke-ReyTacoDryRun.ps1`, and all verification commands below pass.

Stop the rollout immediately if a secret is printed, the schema probe fails, a
test/build command returns non-zero, more than one batch is active, the active
batch does not have exactly one public non-parlay pick, premium text appears in a
public surface, or any required Telegram delivery is missing or failed.

The backend must use `SUPABASE_SERVICE_ROLE_KEY`. Never substitute
`VITE_SUPABASE_ANON_KEY`, `SUPABASE_ANON_KEY`, or another anonymous key: the
publish and delivery RPCs are intentionally unavailable to anonymous clients.

The legacy `backend/channel_queue.json` is not part of this release. There is no
delivery queue: each Telegram destination is attempted synchronously with a
bounded timeout, recorded independently, and skipped on a same-run retry after a
recorded success. A retry always rebuilds the public file and remaining Telegram
messages from the **filas ya persistidas** for that run; a new scrape payload or
hash never replaces the batch already accepted by the database.

En el workflow hibrido, `--collect-only` consulta `resume_pick_batch` antes de
abrir Chrome o consultar fuentes. Si la misma clave identifica una corrida
completada y activa, termina sin recoleccion ni entrega. Una corrida nueva
persiste sin archivo publico, Telegram o Meta.
`--deliver-only` se ejecuta despues en GitHub Cloud, reanuda exclusivamente esas
filas, intenta solo las entregas faltantes y nunca inicia Chrome, Odds API ni
Groq.

La reanudación exige que el lote siga siendo el único activo. Si el lote está
inactivo o reemplazado, el RPC falla de forma cerrada: termina sin restaurar el
archivo público ni Telegram y no permite que el mismo `run_key` reviva picks
retirados. Un resultado SQL nulo significa únicamente que no existe una corrida
completada para esa clave y, por tanto, la recolección normal puede comenzar.

La publicación inicial, el replay y la reanudación también fallan cerrados si
falta el inicio absoluto o si cualquier `source_starts_at` es menor o igual al
reloj UTC. Python vuelve a comprobar ese instante antes de escribir el archivo
público y otra vez justo antes de Telegram. Si el evento vence entre ambas
operaciones, elimina el archivo recién restaurado y termina sin Telegram,
registro de entrega, navegador ni publicación social. `fecha_evento` y
`horario` son solo presentación y nunca sustituyen este control.

La publicación externa conserva un **supuesto operativo de escritor único**:
el lock de la transacción protege la decisión en base de datos, mientras el
archivo y Telegram se completan después. La concurrencia del workflow impide
dos Actions simultáneas; además, una ejecución local directa no debe solaparse
con ninguna Action programada, manual o reintentada. Si no puede garantizarse
esa exclusión, no ejecute producción hasta implementar una concesión persistente
que abarque también los efectos externos.

### 1. Configure secrets before production work

Store real values in the local process/provider secret store, never in a command
committed to Git. Production publication requires these backend names:

- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `GROQ_API_KEY`, `ODDS_API_KEY`, `API_FOOTBALL_KEY`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`,
  `TELEGRAM_VIP_CHANNEL_ID`, `TELEGRAM_FREE_CHANNEL_ID`
- `SCRAPER_RUN_KEY` for a direct local production run, or the automatic
  `GITHUB_RUN_ID` inside GitHub Actions

The backend accepts `TELEGRAM_CHAT_ID` as the compatibility fallback for
`TELEGRAM_ADMIN_ID` and `TELEGRAM_CHANNEL_ID` as the fallback for
`TELEGRAM_VIP_CHANNEL_ID`. Prefer the canonical names for new configuration.
The current GitHub workflows read these repository-secret names exactly:
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GROQ_API_KEY`, `ODDS_API_KEY`,
`API_FOOTBALL_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_CHANNEL_ID`,
`TELEGRAM_VIP_CHANNEL_ID`, `TELEGRAM_FREE_CHANNEL_ID`,
`META_SYSTEM_USER_ACCESS_TOKEN`, `FB_PAGE_ID`, and `IG_USER_ID`.
`TELEGRAM_CHAT_ID` supplies the admin fallback;
keep it aligned with canonical `TELEGRAM_ADMIN_ID` until the workflow itself is
changed to pass the canonical name. `GITHUB_RUN_ID` is built in and is not a
secret.

Verify only presence; do not print the service-role value:

```powershell
if ([string]::IsNullOrWhiteSpace($env:SUPABASE_SERVICE_ROLE_KEY)) {
  throw "SUPABASE_SERVICE_ROLE_KEY is not configured"
}
"SUPABASE_SERVICE_ROLE_KEY is present (value hidden)"
gh secret list
```

`SCRAPER_RUN_KEY` must be stable for retries of one logical local run and unique
for a new batch. `collector.yml` sets `residential:<GITHUB_RUN_ID>` in the
primary collector, recovery collector and cloud delivery jobs. Use **Re-run
failed jobs** for a partial workflow so the same run ID is retained; a new
manual dispatch is a new run.

### 2. Confirm the target, backup, and migrations

From the repository root, confirm the linked project is the intended production
project and that a current database backup exists. Review pending migrations
before changing the remote database:

```powershell
supabase projects list
supabase migration list
supabase db push --dry-run
```

The pending set must include, in this order:

1. `supabase/migrations/20260820210000_base_profiles_picks.sql`, which creates
   the additive `profiles`/`picks` baseline required by a fresh project and
   safely fills missing base columns on an existing installation.
2. `supabase/migrations/20260820220000_secure_membership.sql`, which creates and
   protects `public_picks` and membership data.
3. `supabase/migrations/20260820233000_scraper_run_ledger.sql`, which creates the
   run ledger, atomic publisher, secure resume RPC, delivery recorder, and the intermediate
   fail-closed schema probe.
4. `supabase/migrations/20260820234500_pick_source_audit.sql`, which adds the
   immutable source-audit fields, replaces the publisher contract, and promotes
   `scraper_schema_status()` to schema version `2` with `source_audit = true`.
5. `supabase/migrations/20260821010000_meta_social_delivery.sql` and
   `supabase/migrations/20260821020000_meta_social_claims.sql`, which add
   server-only Meta delivery receipts and attempt-owned claims.
6. `supabase/migrations/20260822010000_harden_legacy_pick_policies.sql`, which
   removes every legacy `picks` policy, recreates the audited six-policy
   allowlist, revokes anonymous writes, and adds the service-only policy
   allowlist preflight.
7. `supabase/migrations/20260823090000_api_football_lineup_budget.sql`, which
   creates the private shared API-Football request budget and cache.
8. `supabase/migrations/20260823100000_six_pick_portfolio_policy.sql` and
   `supabase/migrations/20260823110000_daily_pick_portfolio_revisions.sql`,
   which enforce the six-pick/two-public policy and one private revisioned
   portfolio per Mexico date.
9. `supabase/migrations/20260823120000_residential_collection_lease.sql` and
   `supabase/migrations/20260823130000_adaptive_residential_checks.sql`, which
   prevent both PCs from collecting the same window and schedule only due
   residential work.
10. `supabase/migrations/20260824100000_api_football_result_budget.sql`, which
    reserves at least 20 of the 100 free daily provider calls while allowing
    the cloud verifier to reuse the same cache and quota after lineups.

`supabase db push` applies every pending migration, not just a named file. Only
after reviewing that complete set, confirming the linked project and backup, and
verifying the production service-role key, apply it:

```powershell
supabase db push
supabase migration list
```

Do not roll back by disabling RLS or granting write access to `anon`. If a
migration check is unexpected, stop before dispatching the scraper and restore
from the confirmed backup only through the normal database incident procedure.

### 3. Run non-mutating and automated checks

The dry run is intentionally allowed without Supabase write credentials. It
executes collection and candidate selection, reports `dry_run=true`, and skips
the schema probe, Supabase publication, `frontend/public/picks.json` write, and
all Telegram requests:

```powershell
python backend/scraper.py --dry-run
```

On a successful source pass the summary has this exact shape (counts vary with
live data):

```text
dry_run=true events=<normalized-events> candidates=<verified-picks> persistence=skipped telegram=skipped
```

Exit `0` means that at least one normalized event and one verified candidate
were found. Exit `3` (`NO_EVENTS`) or `4` (`NO_CANDIDATES`) is an honest
fail-closed live-data result and must not be converted into a fallback pick. Any
other non-zero result is a configuration, dependency, external-service, or
unexpected failure to investigate using sanitized logs. In every case, compare
the tracked hashes/status of `frontend/public/picks.json` and `dist/picks.json`
before and after the smoke: dry-run must leave both unchanged and must report no
persistence or Telegram delivery.

Run the complete local gate from the repository root:

```powershell
python -m pyflakes backend/scraper.py backend/scraper_domain.py backend/playdoit_source.py backend/odds_source.py backend/pick_selection.py backend/pick_publisher.py backend/telegram_publisher.py
python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
deno test --allow-env supabase/functions
git diff --check
```

If Deno is not installed globally, replace only the Deno line with this
cross-platform fallback:

```powershell
npx --yes deno test --allow-env supabase/functions
```

Do not use the old `supabase/functions/*/index.test.ts` glob: PowerShell does not
expand that path consistently. Passing the directory lets Deno discover the
tests.

### 4. Understand the production preflight and exit codes

Before opening Chrome in production mode, the scraper calls the read-only
`scraper_schema_status` and `picks_policy_allowlist_status` RPCs with the
service-role client. A missing/404 RPC, missing `public_picks`, missing atomic
publisher/resume RPC, wrong schema version, extra legacy policy, or anonymous
write privilege fails closed with exit `2`; it does not claim a run or create a
batch. Dry-run skips this production-only preflight.

| Code | Meaning | Operator action |
| ---: | --- | --- |
| `0` | Success | Continue only if the post-run invariants also pass. |
| `2` | Configuration or secure-schema preflight failure | Fix secrets/link/migrations; do not start Chrome manually to bypass it. |
| `3` | No source events | Do not publish stale picks; inspect source availability. |
| `4` | No verified candidates | Do not relax validation or reuse an old batch. |
| `5` | Supabase persistence/public-file failure | Stop downstream publication and inspect the run/batch transaction. |
| `6` | Required Telegram delivery/bookkeeping failure | Keep the schedule disabled; retry the same run after repair. |
| `10` | Unexpected failure | Treat as failed and inspect sanitized logs. |

### 5. One controlled manual publication

After secrets, migrations, one registered runner and both PC dry-runs are ready,
dispatch **Rey Taco Residential Collector** exactly once with
`workflow_dispatch`. Do not start a second dispatch while it is active. Confirm
that exactly one residential runner accepts collection and that `deliver_cloud`
resumes the same `residential:<GITHUB_RUN_ID>` only after collection attempts.

Collection-only and delivery-only do not write `frontend/public/picks.json`.
The live Supabase rows and actual Telegram receipts are the source of truth; a
file in an operator checkout is not evidence of what the controlled run stored
or delivered.

Use the Supabase SQL editor with an administrator session for these read-only
checks. They reveal counts and delivery metadata, not premium pick text:

```sql
select
  count(*) filter (where active) as active_batches
from public.pick_batches;

select
  count(*) filter (
    where active and estado = 'pendiente'
  ) as active_pending,
  count(*) filter (
    where active and estado = 'pendiente'
      and visibility = 'public' and not es_parlay
  ) as active_public_non_parlay,
  count(*) filter (
    where active and estado = 'pendiente'
      and visibility = 'public'
  ) as active_public_total,
  count(*) filter (
    where active and estado = 'pendiente'
      and visibility = 'public'
      and nullif(btrim(coalesce(razonamiento, '')), '') is not null
  ) as active_public_with_reasoning
from public.picks;

select
  run_key,
  status,
  delivery_status -> 'admin' ->> 'success' as admin_success,
  delivery_status -> 'vip' ->> 'success' as vip_success,
  delivery_status -> 'free' ->> 'success' as free_success,
  created_at,
  finished_at
from public.scraper_runs
order by created_at desc
limit 1;
```

The required results are `active_batches = 1`,
`active_public_non_parlay = 1`, `active_public_total = 1`,
`active_public_with_reasoning = 0`, and success `true` for each configured
destination. `active_pending` may be greater than one because it includes the
private active picks in the same batch.

Inspect the actual received messages: free Telegram must contain only the live
public database pick and no rationale/premium selection; administrator and VIP
must receive the full active-batch payload. Do not infer delivery from an HTTP
exit alone—match the messages to the latest run and confirm the recorded
statuses above.

#### Separate direct local production artifact check

The following file check applies only when an operator has separately authorized
a direct production publication from this checkout and a build/deployment of
that resulting artifact. It is not part of, and cannot validate, the GitHub
manual-dispatch procedure above. After the migration, secrets, backup, and full
gate are confirmed, the operator must choose one unique explicit approved key
for this logical run, record it in the change/incident record, and reuse that
exact string for every retry. A new key is only for a deliberately new batch,
never for retrying a failed or partial run. Require exit `0`, then build the root
deployment artifact:

```powershell
$authorizedRunKey = 'authorized-local-CHANGE-ID-RUN-01'
if ([string]::IsNullOrWhiteSpace($authorizedRunKey) -or
    $authorizedRunKey.Contains('CHANGE-ID')) {
  throw 'Replace CHANGE-ID with the approved recorded change identifier'
}
$env:SCRAPER_RUN_KEY = $authorizedRunKey
python backend/scraper.py
if ($LASTEXITCODE -ne 0) { throw "Production scraper failed: $LASTEXITCODE" }
npm run build

foreach ($path in @('frontend/public/picks.json', 'dist/picks.json')) {
  $publicPicks = @(Get-Content -LiteralPath $path -Raw | ConvertFrom-Json)
  if ($publicPicks.Count -ne 1) { throw "$path must contain one public pick" }
  if ($publicPicks[0].visibility -ne 'public' -or $publicPicks[0].es_parlay) {
    throw "$path public pick invariant failed"
  }
  if ($publicPicks[0].PSObject.Properties.Name -contains 'razonamiento') {
    throw "$path contains premium rationale"
  }
}
```

The repository deliberately tracks both source fallbacks as neutral empty arrays:
`frontend/public/picks.json` and `dist/picks.json` contain `[]`. A direct
production publication changes the first file, and `npm run build` copies it to
the second. After the authorized artifact has been deployed, restore both files
to `[]` **before committing or rerunning the source-security/full test gate**.
These PowerShell commands write deterministic UTF-8 without a byte-order mark,
including on Windows PowerShell versions whose `Set-Content -Encoding utf8`
would add a BOM:

```powershell
$utf8NoBom = [Text.UTF8Encoding]::new($false)
[IO.File]::WriteAllText(
  (Resolve-Path -LiteralPath 'frontend/public/picks.json'), '[]', $utf8NoBom
)
[IO.File]::WriteAllText(
  (Resolve-Path -LiteralPath 'dist/picks.json'), '[]', $utf8NoBom
)
python -m pytest tests/test_source_security.py::SourceSecurityTests::test_tracked_public_fallback_is_empty_and_cannot_leak_pick_details -q
if ($LASTEXITCODE -ne 0) { throw "Source-security fallback check failed" }
```

### 6. Observation and rollback

Keep public launch/ads disabled until two subsequent residential schedules have
completed successfully. The observation must include the 11 p.m. Mexico City
collector and at least one independent cloud result-verification pass. Repeat
the invariant and delivery checks after each run.

On any invariant, privacy, persistence, verifier, or delivery failure:

1. Disable `collector.yml` in the GitHub Actions UI (or with
   `gh workflow disable collector.yml`) and do not issue a fresh dispatch.
   Disable `scraper.yml` separately only when result verification itself is
   unsafe.
2. If the failure is partial delivery, repair the cause and re-run the failed
   job from the same GitHub workflow run so `GITHUB_RUN_ID` and the batch remain
   idempotent.
3. Do not deploy the newly generated public artifact. Restore the previous
   known-good static build if an unsafe artifact was already deployed.
4. Preserve the run ledger and inactive picks for diagnosis/grading. Do not
   delete history, disable RLS, create a queue, or switch the backend to an
   anonymous key.
5. Rotate any exposed credential and repeat the full gate before re-enabling the
   workflow.

## Incident and rollback

1. Disable checkout by undeploying `create-checkout` or removing `STRIPE_PRICE_ID`. Existing VIP reads remain governed by RLS.
2. Keep the webhook online long enough to process cancellations and failed invoices; otherwise reconcile Stripe subscriptions before disabling it.
3. If RLS behaves unexpectedly, take the frontend offline or revert to the previous static build. Do not disable RLS and do not add a permissive `using (true)` policy.
4. Rotate the affected provider credential and redeploy from secret storage.
5. Review `subscriptions`, `payment_reviews`, and Stripe event logs before restoring checkout.

## Local verification

```powershell
python -m pyflakes backend/scraper.py backend/scraper_domain.py backend/playdoit_source.py backend/odds_source.py backend/pick_selection.py backend/pick_publisher.py backend/telegram_publisher.py
python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npx --yes deno test --allow-env supabase/functions
git diff --check
```

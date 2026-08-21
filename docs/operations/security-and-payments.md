# Security and payments runbook

## Required configuration

Keep real values in provider secret stores, never in Git.

- Backend: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ADMIN_USER_ID`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`, `TELEGRAM_FREE_CHANNEL_ID`, `TELEGRAM_VIP_CHANNEL_ID`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, `SITE_URL`.
- Frontend build: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_TELEGRAM_BOT_USERNAME`, and optionally `VITE_ADSENSE_CLIENT`, `VITE_ADSENSE_SLOT`.
The Supabase anonymous key is public by design. VIP secrecy depends on deploying the RLS migration before publishing the new frontend.

## Deployment order

1. Rotate any Telegram, Meta, Stripe, or Supabase service credential that has ever appeared in source history.
2. Apply `supabase/migrations/20260820220000_secure_membership.sql` to the target Supabase project.
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

### Current state and hard stops

This documentation task did **not** apply any migration to a remote Supabase
project and did **not** dispatch the production workflow. Do not publish until
the project reference and backup are confirmed, the production service-role key
is configured, and all verification commands below pass.

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
recorded success.

### 1. Configure secrets before production work

Store real values in the local process/provider secret store, never in a command
committed to Git. Production publication requires these backend names:

- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `GROQ_API_KEY`, `ODDS_API_KEY`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`,
  `TELEGRAM_VIP_CHANNEL_ID`, `TELEGRAM_FREE_CHANNEL_ID`
- `SCRAPER_RUN_KEY` for a direct local production run, or the automatic
  `GITHUB_RUN_ID` inside GitHub Actions

The backend accepts `TELEGRAM_CHAT_ID` as the compatibility fallback for
`TELEGRAM_ADMIN_ID` and `TELEGRAM_CHANNEL_ID` as the fallback for
`TELEGRAM_VIP_CHANNEL_ID`. Prefer the canonical names for new configuration.
The current GitHub workflow reads these repository-secret names exactly:
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `GROQ_API_KEY`, `ODDS_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_CHANNEL_ID`,
`TELEGRAM_VIP_CHANNEL_ID`, `TELEGRAM_FREE_CHANNEL_ID`, `FB_PAGE_ACCESS_TOKEN`,
`FB_PAGE_ID`, and `IG_USER_ID`. `TELEGRAM_CHAT_ID` supplies the admin fallback;
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
for a new batch. In GitHub Actions, the loader derives
`github-run:<GITHUB_RUN_ID>` automatically. Use **Re-run failed jobs** for a
partial workflow so the same run ID is retained; a new manual dispatch is a new
run.

### 2. Confirm the target, backup, and migrations

From the repository root, confirm the linked project is the intended production
project and that a current database backup exists. Review pending migrations
before changing the remote database:

```powershell
supabase projects list
supabase migration list
supabase db push --dry-run
```

The pending set must include
`supabase/migrations/20260820233000_scraper_run_ledger.sql`; it creates the run
ledger, atomic publisher, delivery recorder, and read-only schema preflight. The
earlier secure-membership migration that creates/protects `public_picks` must
also be applied in order. `supabase db push` applies every pending migration, not
just the named file. Only after reviewing that set, confirming the linked project
and backup, and verifying the production service-role key, apply it:

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

Exit `0` means that at least one event and one verified candidate were found. A
non-zero result is a stop condition; interpret it using the exit-code table
below. Because sources are live, no events/candidates is an honest failed smoke
test, not permission to publish old picks.

Run the complete local gate from the repository root:

```powershell
python -m pyflakes backend/scraper.py backend/scraper_config.py backend/pick_publisher.py backend/telegram_publisher.py
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
`scraper_schema_status` RPC with the service-role client. A missing/404 RPC,
missing `public_picks`, missing atomic publisher, or wrong schema version fails
closed with exit `2`; it does not claim a run or create a batch. Dry-run skips
this production-only preflight.

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

After secrets and migrations are ready and all checks pass, dispatch the
**Rey Taco Picks Bot (Cloud AI)** workflow exactly once with `workflow_dispatch`.
Do not start a second dispatch while it is active. Confirm the verifier succeeds
first; the scraper depends on it, and social posting must run only after scraper
success.

The generated `frontend/public/picks.json` exists only in the ephemeral GitHub
runner. The current workflow neither uploads it as an artifact nor deploys it,
so a file in the operator's existing local checkout is **not** evidence of what
that GitHub run generated. Validate the controlled workflow run through the live
database invariants and the messages actually received in Telegram.

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

Keep public launch/ads disabled until two subsequent scheduled runs have
completed successfully. The observation must include the 11 p.m. Mexico City
run: its scraper job must wait for result verification, and a verifier failure
must prevent scraper/social publication. Repeat the invariant and delivery
checks after each run.

On any invariant, privacy, persistence, verifier, or delivery failure:

1. Disable the GitHub Actions workflow/schedules in the GitHub UI (or with
   `gh workflow disable scraper.yml`) and do not issue a fresh dispatch.
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
python -m pyflakes backend/scraper.py backend/scraper_config.py backend/pick_publisher.py backend/telegram_publisher.py
python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npx --yes deno test --allow-env supabase/functions
git diff --check
```

# Two-PC Weekend Operations Design

**Date:** 2026-08-21  
**Status:** Approved direction, awaiting written-spec review

## Goal

Run Rey Taco Picks without requiring Carlos to be present. Either of two trusted Windows 11 computers can collect Playdoit data in the background. A Friday-night reserve must cover Saturday and Sunday when both computers may be offline. Cloud jobs that do not need Playdoit must continue independently: scheduled release, Telegram delivery, social publishing, and result verification.

This design extends the Playdoit autonomy design. It preserves the frontend, logo palette, Psalms feature, membership boundaries, and strict supported-market scope.

## Fixed Decisions

- The source repository `CarlosCR1019/rey-taco-picks` becomes private before a self-hosted runner is registered.
- The separate website repository `CarlosCR1019/rey-taco-picks-web` remains public.
- Both collector computers run Windows 11 and are trusted machines.
- Both runners use the same custom label, `playdoit-residential`, and run headless as Windows services.
- Friday at 23:00 `America/Mexico_City`, one available residential runner collects Saturday and Sunday reserves.
- Reserved picks are released at 09:00 `America/Mexico_City` on their event day.
- Result verification runs in GitHub-hosted infrastructure at 07:00 and 13:00 `America/Mexico_City` every day.
- Existing APIs remain optional fallbacks. No new provider account or paid dependency is required.

## Repository Boundary

The private source repository owns backend code, workflows, migrations, tests, and secrets. The public web repository receives only the reviewed static frontend artifact. No self-hosted runner, Supabase service-role credential, Telegram token, Meta token, private pick, or workflow write credential is exposed through the public repository.

Changing the source repository to private must happen only after confirming that its current GitHub Actions remain enabled and that the separate web deployment does not read source files directly from it. The source repository has no GitHub Pages deployment, so website continuity depends on the separate web repository rather than its visibility.

## Runtime Topology

### Residential collectors

Register two repository-level runners with unique names and the shared labels `self-hosted`, `Windows`, `X64`, and `playdoit-residential`. Install each runner as a Windows service so no interactive sign-in is required. Configure both computers not to sleep while connected to power. Chrome runs headless and no user profile, saved password, or personal browser data is used.

GitHub routes a collection job to one matching online, idle runner. The workflow's existing concurrency group prevents overlapping schedule runs. A second collection attempt starts only if the first attempt fails or times out. Both attempts use the same stable run key, so Supabase idempotency prevents duplicate batches and Telegram delivery receipts prevent duplicate messages.

If both machines are offline, the job remains queued. Friday reserves remove the dependency on weekend availability, but an offline weekday collection cannot produce new verified lines and must not synthesize picks.

### GitHub-hosted control jobs

Jobs that do not browse Playdoit remain on `ubuntu-latest`:

- release a previously stored daily batch;
- send Telegram destinations and record delivery receipts;
- generate a banner from the released batch and publish it to connected Meta destinations;
- query ESPN scoreboards and grade pending picks;
- report missing collectors, delayed batches, and failed external deliveries.

These jobs remain available even if both Windows computers are off.

## Collection Schedule

Normal residential collection runs at the existing 10:00, 16:00, and 23:00 Mexico City times. The Friday 23:00 run has a weekend horizon ending after Sunday's final eligible event.

The Friday collector:

1. collects Playdoit first with bounded source diagnostics and retry policy;
2. queries only already-configured fallbacks if verified coverage is insufficient;
3. strictly normalizes source IDs, dates, full-game markets, named outcomes, and prices;
4. partitions candidates by Saturday and Sunday in `America/Mexico_City`;
5. ranks each day independently from its allow-listed candidate catalog;
6. creates one private reserved batch per event date.

Each daily batch has its own stable identity, derived from the weekend and event date. Each contains exactly one future public non-parlay pick and any validated premium picks. A missing eligible day produces no batch for that day and an administrator alert; it never copies a pick from the other day.

## Reserved Batch Storage

Weekend reserves must not be inserted directly into the live public `picks` surface. Add private scheduled-batch storage governed by service-role-only access. Each reserved row stores the complete source audit, event start, observation time, intended event date, release time, visibility, and immutable source-derived price.

At release time, an atomic server-side operation:

1. locks the reserved daily batch;
2. revalidates schema, source audit, event start, public/premium policy, and prior release status;
3. materializes the batch into live picks exactly once;
4. returns the persisted rows and delivery ledger;
5. marks the reservation released.

If the reservation was already released, the operation returns the same persisted batch and resumes only unfinished deliveries. If the event has already started, the batch is rejected as stale.

Because Friday quotes can move before Sunday, every weekend message shows the original observation time and says to verify the current price at the chosen sportsbook. No later process changes the stored factual price without a new verified source observation.

## Optional Weekend Refresh

Saturday and Sunday morning collectors may refresh an unreleased reservation when a residential runner is online. A refresh replaces the private reservation only when it has a newer source observation, the same exact event/market identity, a future start, and a complete valid daily batch. Once release begins, the reservation is immutable.

If no runner is online, the Friday reserve is released unchanged. Refresh failure does not delete a valid reserve.

## Release and Delivery Flow

At 09:00 Mexico City, a GitHub-hosted dispatcher releases that day's batch:

1. atomically materialize or resume the persisted batch;
2. update the website's Supabase-backed public and subscriber views;
3. send all picks to the configured administrator destination;
4. send all authorized picks to the VIP destination;
5. send exactly one public non-parlay pick to the free destination;
6. record each Telegram delivery independently;
7. generate the social banner from the exact released public pick;
8. publish Facebook and Instagram independently and record their outcomes.

Social publication never runs for an empty, stale, unpersisted, or delivery-failed batch. A Meta failure returns a failing job status and an administrator alert instead of being printed and ignored. Facebook and Instagram are separate destinations: one can retry without duplicating the other.

## Result Verification

Result verification does not require Playdoit, Chrome, a residential IP, or either Windows runner. It runs on GitHub-hosted infrastructure at 07:00 and 13:00 Mexico City daily.

For every pending live pick whose event date is due:

1. query the configured public ESPN scoreboards for the exact event date and league;
2. require a unique home/away/date match and a final event state;
3. grade only a market supported by the existing result-domain grader;
4. atomically update the result state and source-audit fields;
5. leave unfinished games pending;
6. mark ambiguous or unsupported cases `revision_pendiente` rather than guessing;
7. send one Telegram recap only when at least one result changed.

The second daily pass catches games that were incomplete during the first. Pending Sunday picks are checked on Monday automatically. Verification failure does not alter the previous state and is retried at the next scheduled pass.

## Failure Behavior

- **One collector offline before assignment:** the other matching runner may accept the job.
- **Collector fails after starting:** the first attempt times out or fails; the second attempt uses the same run key and may run on the other available collector.
- **Both collectors offline:** no new scrape; queued job and administrator status. Existing weekend reserves still release from cloud.
- **Playdoit challenge or broken DOM:** stop bounded attempts, query existing fallbacks, and publish nothing without verified candidates.
- **No valid Saturday or Sunday catalog:** no reservation for that day and no social/public message.
- **Supabase failure:** no Telegram, web exposure, or social post.
- **Telegram failure after persistence:** retain the batch and retry only missing destinations.
- **Meta failure:** keep the already persisted and Telegram-delivered batch, record the failed Meta destination, alert the administrator, and retry without duplicate posts.
- **ESPN unavailable or match ambiguous:** preserve the pending/review state and retry later.

## Security

- Register runners only after the source repository is private.
- Use one dedicated, non-administrator Windows service identity where practical.
- Do not reuse a personal Chrome profile.
- Keep GitHub job permissions read-only except for narrowly scoped operations that explicitly need more.
- Store production secrets only in private GitHub Actions secrets and Supabase secret storage, never in runner files or workflow output.
- Use pinned action commit SHAs and disable credential persistence at checkout.
- Never include secrets, cookies, full page HTML, or exception bodies in artifacts, Telegram alerts, or logs.
- A runner registration token is entered only during installation and is never committed or copied into the second computer's package.

## Testing

Implementation follows test-driven development:

- source-health and bounded-retry unit tests;
- event-horizon and Mexico City date-partition tests;
- reservation privacy and exact-once release SQL contract tests;
- refresh-vs-release race and stale-event tests;
- duplicate-run and collector-failover workflow tests;
- Telegram and Meta per-destination receipt tests;
- cloud verification tests for final, incomplete, ambiguous, void, and unsupported markets;
- workflow tests proving cloud jobs do not target residential runners;
- a no-secret/no-write Playdoit probe on each Windows runner;
- a controlled weekend batch dry run with zero Supabase writes and zero external deliveries;
- the complete Python, frontend, Deno, typecheck, build, lint, and diff verification gates.

## Acceptance Criteria

- Either Windows 11 computer can collect without an interactive login.
- One scheduled scrape never executes concurrently on both computers.
- A failed first collector attempt can be retried by another available collector without duplicate side effects.
- Friday 23:00 can create independent Saturday and Sunday private reserves.
- Saturday and Sunday 09:00 releases do not require either computer to be online.
- Public, VIP, admin, Facebook, and Instagram deliveries derive from the exact persisted daily batch.
- A failed or empty source run cannot trigger Telegram or social pick publication.
- Results are verified in cloud twice daily and never guessed.
- The source repository is private before runner registration; the public web repository remains available.
- Frontend presentation, Psalms, logo colors, and existing supported markets remain unchanged.

## Out of Scope

- guaranteeing that Playdoit permits either residential connection indefinitely;
- adding new sportsbooks, provider accounts, paid services, proxies, CAPTCHA solving, or challenge bypass;
- running arbitrary repository workflows on personal computers;
- collecting unsupported props or periods without dedicated validators and graders;
- exposing reserved weekend picks before their scheduled release.

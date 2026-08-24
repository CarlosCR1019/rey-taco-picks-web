# Interactive Windows Runner Design

**Date:** 2026-08-22  
**Status:** approved direction; pending review of this written specification

## Objective

Run the residential Playdoit collector automatically on either trusted Windows
11 computer without interrupting the person using it. The GitHub runner console
must remain hidden. Chrome may show an icon in the taskbar for the duration of
collection, but its window must start and remain minimized, must not take the
foreground, and must close after collection.

This design replaces the Windows-service and headless-browser decisions in the
earlier two-PC operating designs. The hybrid boundary remains unchanged:
Windows collects and persists; GitHub-hosted jobs deliver Telegram and Meta and
verify results.

## Evidence Behind the Change

The production workflow reached the scraper successfully with Python 3.11.9,
but headless Chrome received a small page titled `Acceso bloqueado`. A diagnostic
run from the same computer and residential IP using headed Chrome received the
complete Playdoit page. A safe full dry run then found 33 eligible events,
selected eight objectives, and completed eight structured market immersions.

The local The Odds API key authenticates, but its account currently reports no
remaining credits. The `/sports` authentication check consumed zero credits.
Therefore the immediate free operating path is Playdoit through an interactive
browser; Odds integration remains an optional later fallback.

## Fixed Decisions

- Use an interactive GitHub Actions runner that starts automatically at Windows
  sign-in instead of a Windows service in session zero.
- The runner process uses the signed-in non-administrator account.
- Its console is hidden; production secrets remain GitHub Actions secrets.
- Chrome uses a temporary automation profile and never uses a personal Chrome
  profile, cookies, saved passwords, or a Playdoit account.
- Chrome starts minimized, is minimized again through WebDriver before source
  navigation, and is closed in a `finally` path.
- An icon in the taskbar is acceptable. A foreground browser window is not.
- The automation never changes power settings and never shuts down, restarts,
  suspends, signs out, or unlocks either computer.
- A locked screen is supported while the Windows session remains signed in. A
  signed-out computer is offline for residential jobs.
- Do not bypass CAPTCHA, access controls, geographic restrictions, or other
  security challenges.

## Architecture

### Interactive runner startup

Each PC retains its repository-level runner registration in
`C:\actions-runner`. A one-time administrative migration stops and uninstalls
the runner service without deleting `.runner`, credentials, the Python tool
cache, or work history required by GitHub Runner.

A Windows Scheduled Task starts the existing `run.cmd` at sign-in for the
current trusted user. The task runs only in that interactive user session and
does not request administrator privileges. A PowerShell launcher hides the
runner console, sets an explicit browser-mode variable, starts `run.cmd`, and
returns a failing status if the runner cannot remain active.

The task is idempotent: reinstalling it updates the same named task rather than
creating duplicates. Installation scripts never accept Supabase, Telegram,
Meta, Groq, or Odds secrets.

### Browser-mode contract

The scraper accepts one explicit browser mode for GitHub residential jobs. In
interactive mode it does not infer headless behavior from `CI` or
`GITHUB_ACTIONS`. It adds Chrome's start-minimized option, starts a fresh
temporary profile, calls WebDriver minimization immediately, verifies that the
window is minimized, and only then navigates to Playdoit.

If the runner has no interactive desktop, Chrome cannot be minimized, or the
window becomes foreground during the startup gate, collection stops with a
sanitized infrastructure failure. It must not silently fall back to headless.

Local dry runs remain safe and headed. GitHub-hosted cloud jobs never create a
browser.

### Two-PC routing and recovery

Both runners keep the shared `playdoit-residential` label and add a unique
machine label:

- `rey-taco-carlos`
- `rey-taco-respaldo`

The first residential job may run on either available computer. An always-run
finalization step records only the runner name and maps it to the opposite
machine label. If collection fails for a recoverable browser or source reason,
the recovery job targets the other machine rather than immediately retrying the
same IP and browser session.

Both attempts retain the same `SCRAPER_RUN_KEY`, so persistence remains
idempotent. If the other PC is signed out or offline, recovery waits for it; it
does not publish fabricated data or convert the failure into a successful empty
run.

### Source-health classification

The scraper distinguishes these outcomes:

- `valid_source`: Playdoit rendered and produced a parseable catalog, even if
  later business filters find no publishable candidate;
- `source_blocked`: the title or body contains the sanitized blocked-access
  signature or Ray-ID challenge structure;
- `source_invalid`: the expected sportsbook application never renders within
  bounded waits;
- `no_events`: a valid rendered source contains no eligible future events;
- `no_candidates`: events exist but none pass the supported market and evidence
  rules.

`source_blocked` and `source_invalid` are recoverable failures and can invoke
the other PC. `no_events` and `no_candidates` are honest business outcomes and
do not invoke duplicate collection. Logs include the classification and counts,
but never the residential IP, full HTML, cookies, credentials, API keys, or
exception bodies.

### Cloud delivery

The cloud boundary is unchanged. A Windows PC runs only `--collect-only` and
persists an audited batch. The Ubuntu job uses the same run key to resume the
exact batch, send unfinished Telegram destinations, and publish the exact
eligible social batch to Facebook and Instagram. With no persisted batch,
delivery reports `deliver_only=no_batch` and performs no external publication.

## Installation and Migration

The Windows package contains:

- a host compatibility check;
- the pinned Python tool-cache initializer;
- a new interactive runner installer/migrator;
- a hidden interactive launcher;
- a safe headed dry-run command;
- a rollback command and operations guide.

Migration on Carlos's PC proceeds first:

1. verify the existing service, runner registration, tool cache, and current
   worktree without exposing credentials;
2. record the service name and Scheduled Task state for rollback;
3. stop and uninstall only the runner service;
4. register the sign-in task and interactive launcher;
5. start the task manually without signing out or restarting;
6. verify GitHub shows the runner online and idle;
7. run the safe Playdoit probe with Chrome minimized;
8. run one separately confirmed production workflow;
9. leave automatic sign-in startup to be observed at the next natural login.

No automated test forces a reboot or sign-out. The girlfriend's PC is migrated
only after Carlos's PC passes the acceptance gates. Its installer searches for
the extracted package and repository so the user does not need to know a path.

## Rollback

Rollback stops the Scheduled Task runner, disables or removes only the Rey Taco
task, and reinstalls/starts the original GitHub Runner service from the existing
registration. It does not delete `C:\actions-runner`, the repository, the tool
cache, secrets, or user files. The service restores the former runner topology,
although headless Playdoit collection is known to be blocked and is not treated
as a functional scraper fallback.

## Testing

Implementation follows test-driven development and must include:

- browser-mode tests proving interactive mode overrides CI headless inference;
- option and call-order tests for start-minimized, immediate minimization, and
  navigation only after the minimization gate;
- source-health tests for blocked, invalid, valid-empty, and valid-populated
  pages;
- workflow tests for unique labels, opposite-PC recovery, a shared run key,
  pinned actions, and no pull-request access to personal runners;
- PowerShell parser and contract tests for hidden console startup, non-admin
  daily execution, idempotent task registration, no production secrets, and
  recoverable rollback;
- a safe integration probe confirming that Chrome remains minimized and that
  Playdoit yields at least one parseable event when its catalog is available;
- a controlled real workflow requiring action-time confirmation before any
  possible Telegram or Meta publication;
- the existing scraper, persistence, delivery, social, and security suites.

## Acceptance Criteria

Carlos's migration is accepted only when:

1. the interactive runner starts through the Scheduled Task with its console
   hidden and GitHub reports it online;
2. Chrome never becomes the foreground window during the observed probe and
   remains minimized until it closes;
3. the safe probe classifies Playdoit as valid and extracts real events when a
   catalog is available;
4. blocked/invalid source pages fail explicitly and cannot produce an empty
   success or external publication;
5. a controlled workflow completes collection and cloud handoff, producing
   either an audited persisted batch or an honest `no_events`/`no_candidates`;
6. Telegram and Meta run only from the exact persisted batch and retain their
   existing per-destination receipts;
7. rollback can restore the original service without deleting runner state;
8. the next natural Windows sign-in demonstrates automatic startup before the
   same migration is declared complete on the backup PC.

No one can guarantee that a third-party website will remain available or permit
a residential connection indefinitely. The guarantee is limited to observable,
tested system behavior: minimized operation, explicit failure classification,
safe failover, no fabricated picks, and no publication without persistence.

## Out of Scope

- buying or creating another provider account;
- consuming additional Odds API credits or changing its quota plan;
- VPNs, proxies, CAPTCHA solving, challenge bypass, or access-control evasion;
- changing pick-ranking policy, supported markets, result grading, frontend,
  Psalms, brand colors, Reels, Stories, or general content generation;
- forcing Windows restart, sign-out, sleep, or power-policy changes.

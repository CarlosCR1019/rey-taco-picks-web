# Adaptive Residential Checks Implementation Plan

**Goal:** Evaluate work every 30 minutes while opening minimized Chrome only for a full scan or verified near-event work.

**Architecture:** GitHub schedules two lightweight half-hour ticks plus the independent 10:00 cloud release. A pure Mexico-time planner identifies the five full-scan windows and release windows. A private Supabase event-watch ledger exposes a fail-closed REST decision for lineup and draft-quote refreshes. Full and adaptive scans update the watch ledger; only a positive decision proceeds to the residential lease and Chrome.

## Tasks

1. Extend the stale-run scheduler with a deterministic Mexico-time scan/release plan.
2. Add a private event-watch ledger and a read-only adaptive-work RPC.
3. Add a standard-library client/CLI for the lightweight RPC so dependency installation is skipped when idle.
4. Record source events after a successful residential surface scan.
5. Replace the five isolated cron entries with two half-hour ticks while preserving 08:00, 12:00, 16:00, 20:00, 23:00 full scans and 10:00 cloud release.
6. Verify no idle tick starts Chrome, claims a lease, installs dependencies, or changes PC power state.

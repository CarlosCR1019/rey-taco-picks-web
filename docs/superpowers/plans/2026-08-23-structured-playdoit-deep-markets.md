# Structured Playdoit Deep-Markets Implementation Plan

**Goal:** Make the current React-snapshot collection path inspect each event detail and retain verified full-game `h2h`, `totals`, and `spreads` markets before candidate generation.

**Architecture:** Keep the approved Playdoit browser collector and its existing strict normalizer. Convert a structured React snapshot into the canonical raw event, enter that event's detail using its source ID and competitors, reuse the bounded supported-market extractor, and merge the snapshot H2H quote with detail markets without inventing or overwriting facts. If detail navigation fails, retain only the already verified snapshot market.

**Safety constraints:** No demo data, synthetic prices, unbounded navigation, new provider, new credential, or automatic publication is introduced. `KeyboardInterrupt` and `SystemExit` remain visible, event failures remain isolated, and every market still passes the existing full-game completeness and conflict validators.

---

## Task 1: Reproduce the missing depth

**Files:**
- Modify: `tests/test_playdoit_source.py`

1. Change the current React-snapshot driver double so it exposes a successful event-detail click, supported market tabs, and a return to the event list.
2. Assert that the collector opens the event by official source ID.
3. Assert that the returned raw record contains verified `h2h`, `totals`, and `spreads` markets.
4. Run the focused test and confirm it fails because the snapshot branch currently returns early.

## Task 2: Repair the snapshot branch

**Files:**
- Modify: `backend/playdoit_source.py`
- Modify: `tests/test_playdoit_source.py`

1. Add one internal detail-enrichment boundary shared by structured and legacy summaries.
2. Navigate with source ID, home, and away as script arguments.
3. Extract supported markets with the existing bounded tab waits.
4. Merge detail markets with snapshot markets by exact raw quote equality; leave conflicts for the strict normalizer to reject.
5. Always attempt to return to the event list after a successful detail entry.
6. Preserve verified snapshot H2H when detail navigation or a supported tab is unavailable.

## Task 3: Prove safe behavior

**Files:**
- Modify: `tests/test_playdoit_source.py`

1. Cover detail-navigation failure and confirm verified snapshot H2H survives.
2. Cover duplicate detail H2H and confirm it does not multiply the canonical quote.
3. Cover conflicting detail H2H and confirm normalization fails closed.
4. Run all Playdoit tests.
5. Run the full Python test suite and repository verification gates.

## Task 4: Controlled live validation

1. Run the collector in a non-publishing/dry-run mode on the interactive Windows runner.
2. Capture sanitized counts for events and each supported market type.
3. Confirm no demo reel or test publisher is reachable from the production workflow.
4. Only after the dry run is clean, run the already-approved real workflow and verify scraper → pick → Telegram → Meta behavior from persisted, verified source data.


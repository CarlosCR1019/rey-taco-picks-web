# Full Sportsbook Sports and Event Scan

## Goal

Capture every sport, event, and displayed market that Playdoit, Codere, and Caliente make reachable through their public sportsbook navigation at scan time. Exhaust each provider's available live and scheduled sections, date navigation, pagination, and incremental loading. Perform browser capture and data processing on the VPS through the existing dedicated Tailscale phone route.

The scanner must report the boundary of what it read. A source can be marked complete only when every discovered category and section has been traversed to its visible end. A blocked page, failed category, unresolved pagination, or reached safety limit produces partial or failed coverage with an explicit reason.

## User-confirmed scope

- Providers: Playdoit, Codere, and Caliente.
- Sports: discover all sports offered by each provider during the run; do not rely on a short hard-coded league allowlist.
- Events: include live events and every scheduled event/date each provider exposes through its own navigation.
- Markets: preserve all displayed markets and selections that can be read. Normalize supported markets for cross-book review. Preserve unsupported or ambiguous market rows in the private source inventory with an unsupported reason instead of dropping them.
- Runtime: browser access, capture, normalization, and reporting remain on the VPS using the existing Tailscale phone route and private network worker. Never use the local browser for sportsbook capture.
- Picks: Playdoit remains the candidate and quote source; Caliente and Codere remain comparison sources. Existing freshness, event identity, market completeness, and pick-review gates remain unchanged. Broader capture must not force a pick.
- Horizon: scan all dates and pages each provider publishes through its navigation. There is no fixed seven-day cutoff. A runtime safety stop is permitted only if it is visible in the coverage report as incomplete.

## Current gaps

- Playdoit's review collector visits a fixed list of named competitions, so sports and leagues outside that list are not enumerated.
- Caliente and Codere currently parse the rendered landing-page DOM. They do not traverse every sport tab, date control, or page.
- Sport-name recognition is a short alias table and omits categories such as table tennis and American football.
- The normalized snapshot does not describe which sports, dates, pages, and sections were exhausted. A zero count cannot distinguish an empty source from an unvisited or blocked category.
- The existing primary-led join can retain comparison events only when they match Playdoit. It must not be used as the raw coverage inventory because unmatched source events disappear from the pick candidate join.

## Design

### Provider-specific navigation, shared capture contract

Keep provider navigation explicit because the three sites use different page structures. Each provider adapter discovers its sport and competition controls from the currently rendered page, records a stable identifier and display label when available, and traverses the controls exposed by that site. For each discovered sport, visit live and scheduled views where available. Continue every date selector, page control, load-more action, or virtualized list until the provider signals exhaustion or a repeated page is detected.

All adapters emit a common capture record containing provider, category identity, section, page or cursor identity, date selected, observation time, rendered HTML or extracted DOM rows, and navigation outcome. Use the existing Playwright browser configured with `socks5://127.0.0.1:1055`. Reuse the current VPS-only transient `PrivateNetwork=yes` worker and bridge. Do not change the system exit route, persistent allowlist, active services, or provider credentials.

### Event and market inventory

Store source events before cross-book matching. Preserve provider event IDs, sport and competition labels, teams or participants, start time, live state, displayed markets, selection labels, prices, and provider market/selection IDs whenever available. Codere featured combined cards remain a separate inventory section and are not converted into straight match markets.

Normalize the market types already accepted by the private pick review. Keep all other captured market rows in the private inventory with a stable unsupported or ambiguous reason. A provider event without a Playdoit counterpart remains visible in coverage and source inventory even though it cannot become a Playdoit-led pick candidate.

Deduplicate pages using provider event IDs. When an event has no stable provider ID, use a composite identity of normalized sport, competition, ordered participants, and start time; ambiguous collisions remain separate and are marked for review rather than merged.

### Coverage manifest

Add a versioned coverage manifest to each snapshot and report. For each provider, include:

- scan start/end and observed timestamps;
- discovered sport and competition controls;
- live/scheduled/featured sections visited;
- selected dates and page/cursor count per section;
- whether the provider's terminal page or date boundary was reached;
- raw event rows, unique events, duplicate rows, accepted normalized events, and rejected rows by sport and section;
- captured market and selection rows, normalized counts, and unsupported/ambiguous counts;
- navigation errors, empty states, blocked states, and safety-limit stops.

Overall status is `complete` only when every discovered sport/section has reached its provider-reported end and no navigation or parse gap remains unexplained. Use `partial` for any discoverable but unfinished section, `blocked` when provider access prevents traversal, and `error` when collection cannot produce a reliable manifest. Do not infer completeness from nonzero event counts.

### Safety, resource bounds, and private outputs

Protect the VPS from infinite pagination, repeated cursors, and runaway runtime with configurable page, retry, and elapsed-time safety bounds. Reaching a bound stops that branch and marks it incomplete with the bound and last cursor recorded. Use stable deduplication and bounded browser retries; never retry a completed page indefinitely.

Write raw capture metadata, normalized snapshot, coverage manifest, and private pick-review report under the existing mode-restricted VPS run directory. Do not write these artifacts to public assets, Supabase, the audit ledger, or Telegram. Keep secrets in the VPS environment and do not include them in manifests or logs.

## Data flow

1. The VPS runner validates the dedicated residential Tailscale route and launches the private worker.
2. Each provider adapter discovers available sports and navigation controls.
3. The adapters exhaust live/scheduled sections, published dates, pages, and incremental loads within explicit safety bounds.
4. Raw source events and markets are stored with per-page provenance before provider joins.
5. Normalizers classify every row as accepted, duplicate, unsupported, ambiguous, or rejected with a reason.
6. The coverage evaluator marks each provider and sport complete, partial, blocked, or error from traversal evidence.
7. The existing Playdoit-led pick-review pipeline uses only matched, fresh, complete, supported markets and keeps all current gates.
8. The VPS writes the private source inventory, coverage manifest, and review report.

## Failure behavior

- A blocked sportsbook is recorded as blocked; the scanner continues with other providers when the VPS route is still healthy.
- A single sport or page failure makes that provider's overall coverage partial and records the affected branch; successfully read data remains available.
- Missing sport metadata is retained under an explicit unknown category and prevents a complete-coverage claim until resolved.
- Unsupported market structures remain captured but cannot satisfy pick-review market requirements.
- An event shown live is retained as live inventory and remains excluded from pre-match candidate eligibility.
- No context, odds, or event count is fabricated when a provider endpoint or rendered page omits it.

## Verification and completion criteria

- Fixture-driven tests prove each provider adapter discovers categories dynamically and traverses live, scheduled, date, pagination, and incremental-load controls until terminal state.
- Tests prove repeated pages/cursors terminate with a partial status rather than hanging or claiming completion.
- Tests prove each raw event and market row is retained, categorized, and counted even when unsupported, ambiguous, duplicate, unmatched, or rejected.
- Tests prove coverage is complete only when every discovered branch reaches a terminal state; blocked or failed branches cannot yield complete status.
- Tests prove all navigation runs through the configured SOCKS proxy and the VPS runner continues to use the dedicated Tailscale bridge and temporary private worker.
- A live VPS scan records a coverage manifest for each of the three providers, with no unexplained discovered category or page omitted. Any provider control that cannot be exhausted is identified explicitly, so the run reports partial coverage rather than claiming all.
- The resulting private pick review does not weaken identity, freshness, market-completeness, or eligibility rules and does not publish or dispatch anything.

## Out of scope

- Modifying production services, system Tailscale routes, or persistent egress allowlists.
- Using the local browser or moving credentials/browser profiles off the VPS.
- Publishing picks, sending Telegram messages, writing Supabase or the audit ledger, changing stake sizing, or claiming positive expected value.
- Claiming access to provider data that is not exposed through the account's reachable pages at scan time.
- Scheduling a recurring daemon or automation without a separate request.

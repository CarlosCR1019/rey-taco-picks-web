# Universal Markets, Confirmed Lineups, and Adaptive Scheduling

**Date:** 2026-08-23
**Status:** Approved design pending written-spec review
**Product:** Rey Taco Picks, Mexico launch

## Objective

Expand the Playdoit collector from three hard-coded market families to a
source-backed catalog of every market that can be tied unambiguously to one
pre-match event. Use confirmed starting lineups before making soccer player
props eligible, run collectors in the background on either Windows 11 PC, and
publish a small, quality-controlled daily portfolio instead of one pick per
scrape.

The system must never invent a market period, team/player scope, selection,
line, price, fixture identity, or result. More observed markets increase the
candidate pool; they do not weaken the evidence boundary.

## Approved Product Rules

- Observe all source markets, including match markets, team totals, halves,
  corners, cards, player props, and composite/boosted offers.
- A market is publishable only when the official event, market, selection, and
  current price are complete and internally consistent.
- Soccer player props require the player to appear in the confirmed starting
  eleven. A predicted lineup or the presence of a Playdoit prop is not enough.
- When lineups are unavailable, discard the player prop and fill the open draft
  slot with the best verified team-market candidate. Already delivered picks
  are never silently replaced.
- Target four picks per Mexico calendar day. Publish zero rather than force a
  weak pick, normally publish three to five, and cap the portfolio at six.
- Publish at most one pick per physical match.
- With one to five published picks, exactly one is public/free. With six picks,
  exactly two are public/free and the other four are premium. VIP receives the
  complete portfolio.
- Free picks follow the same validation rules as premium picks, come from
  different matches, and are never parlays.
- Scanning more frequently must not create duplicate Telegram or social posts.
- No job may shut down, suspend, wake, or interrupt either PC.

## Delivery Phases

The work is split into three bounded phases so the existing team-market flow
can remain usable while broader market support is added safely.

### Phase 1: Provenance-safe universal catalog

Collect every rendered Playdoit market with official source identifiers and
names. Preserve unsupported shapes in the catalog instead of coercing them into
`h2h`, `totals`, or `spreads`. Only structurally complete quotes can become
candidates.

### Phase 2: Confirmed-lineup eligibility

Map soccer fixtures and players to API-Football, cache confirmed lineups, and
gate player props. Team markets continue normally if the lineup service or its
API key is unavailable.

### Phase 3: Autonomous result resolvers

Resolve published market types against exact official event, team, and player
statistics. Markets without a deterministic resolver remain pending and do not
enter performance statistics until resolved. A later resolver may settle them;
the system never guesses a win or loss.

## Source Provenance Boundary

The React extractor receives the expected Playdoit event ID, home team, and
away team as script arguments. It must verify all of the following before
returning detail markets:

1. The current Playdoit URL contains the expected `eventId`.
2. Exactly one active event-details market container is used.
3. The container text or source context contains both expected competitors.
4. Buttons are descendants of that container and are not residual nodes from
   another route.
5. Each quote has an official market ID, odd/selection ID, non-empty official
   names, active status, and a finite decimal price greater than 1.0.
6. If a market exposes `oddIds`, each returned odd belongs to that list.
7. A contradictory source period, team/player identifier, or scope causes the
   affected quote group to fail closed.

The extractor scopes boosted/composite offers separately. A boost becomes a
candidate only when Playdoit exposes the complete component description and a
single official price. Promotional DOM text without complete source identity
is cataloged as detected but is not publishable.

## Canonical Market Data

Each collected market record carries:

- Playdoit event ID;
- market ID and sport-market ID when present;
- exact market name and short name;
- explicit period/category/scope label when supplied, otherwise
  `source_unspecified` rather than an inferred value;
- official market type, variant, and line values;
- selection/odd ID, exact selection name, competitor ID when present, status,
  type, line, and decimal price;
- observed timestamp and bookmaker identity;
- structural provenance flags showing that route, event container, and
  competitors were verified.

Known full-game match markets keep the existing canonical projections for
cross-provider comparison. Other source-backed offers use a generic source
market representation with their display name and source IDs preserved. This
allows the ranking and publishing layers to say exactly what Playdoit offers
without pretending that a corner, card, team total, or player prop is a generic
match total.

Progressive rendering is handled by waiting for complete quote groups. A total
does not become ready with only an over or only an under unless Playdoit defines
the market as an official one-way selection. Scroll/expansion continues through
the event-details container until its observed market/selection ID set becomes
stable within a bounded timeout.

## Candidate Eligibility and Ranking

The complete source catalog is persisted, but the AI receives a bounded,
read-only candidate set. Deterministic code performs these checks first:

- future pre-match event inside the configured horizon;
- exact source IDs and current quote;
- no conflicting revisions for the same selection;
- no duplicate physical event/market/selection;
- confirmed starting eleven for soccer player props;
- complete composite definition for boosted offers;
- at most one final published selection per physical match;
- no more than six published picks on one Mexico date.

The AI may rank candidate IDs and explain its ordering. It may not rewrite any
market, participant, line, price, or schedule. The existing internal ceiling of
twelve ranked candidates remains a prompt/output bound, not a publication
target.

## Lineup Sources and Quota

API-Football is the primary lineup source. TheSportsDB is an optional fallback
when an exact event match and a complete starting eleven are available.

Fixture matching requires both competitors, competition compatibility, and a
kickoff-time tolerance. One-sided or name-only fuzzy matching is rejected.
Player matching requires the official player name within the matched team; an
ambiguous normalized name fails closed.

API-Football use is cached and budgeted:

- one daily fixture discovery per relevant date, reused by all events;
- grouped fixture lookups where the provider supports them;
- lineup checks near T-60 and T-25 rather than continuous polling;
- hard limit of 40 API-Football requests per UTC quota day for lineup work;
- honor the provider's remaining-request and per-minute headers;
- stop lineup polling once both starting elevens are confirmed.

This leaves at least 60 of the free plan's 100 daily calls for result checks,
recovery, or later features. Missing quota, coverage, credentials, or lineup
data removes player props from eligibility but does not stop team picks.
API-Football is a separate integration from the existing Odds API and uses its
own GitHub secret.

## Adaptive Background Scheduling

The collector runs on either registered Windows 11 self-hosted runner. Chrome
uses the already approved minimized interactive mode because headless access is
not reliable enough for Playdoit. PowerShell remains hidden and Chrome must not
take focus. If minimization cannot be verified, the scrape fails closed.

### Full scans

Run full event/category scans at approximately 08:00, 12:00, 16:00, 20:00,
and 23:00 America/Mexico_City. The Friday 23:00 scan retains the approved
weekend horizon behavior.

### Lightweight adaptive checks

Evaluate work every 30 minutes, but do not launch a full scrape unless one of
these conditions is true:

- the current time is inside a full-scan window;
- a persisted event is approaching its lineup window;
- a current draft quote requires bounded revalidation;
- a previous attempt recorded a recoverable, non-stale failure.

At T-60, request lineups. At T-25, confirm the starting eleven and re-open only
the relevant Playdoit event to refresh its quotes. At T-15, a confirmed player
prop may fill an undelivered draft slot. A sent pick remains immutable.

Scheduled workflow concurrency keeps only the newest pending scheduled run, so
turning on a PC does not replay a backlog. Manual workflow dispatch remains
separate. Supabase provides an expiring distributed lock so only one PC owns a
collection window; the second PC is recovery. Stale windows exit successfully
without scraping or publishing.

Both machines require an active Windows user session and must not be asleep.
No automation changes power settings or closes user applications.

## Publication Policy

Multiple scans update a private daily draft. They do not each produce a new
batch. Normal team-pick releases stay bounded to the existing daily delivery
windows, while a confirmed lineup prop may be delivered near kickoff if the
daily cap has room.

Visibility is assigned after the final daily ordering:

| Published count | Free | Premium-only | VIP receives |
| ---: | ---: | ---: | ---: |
| 0 | 0 | 0 | 0 |
| 1-5 | 1 | 0-4 | all |
| 6 | 2 | 4 | all 6 |

Free selections must belong to different physical matches. Social content uses
one principal feed publication per batch; additional timely information is
routed to stories/Telegram rather than repeatedly posting the same feed asset.
Idempotency keys include the Mexico date, source event, source market,
selection, and batch revision.

## Result Verification

Every delivered pick preserves enough source identity to select an exact result
resolver. The verifier checks the physical event first and then applies the
resolver for the official market definition. It records the evidence source and
timestamp used for settlement.

If statistics are missing, contradictory, or insufficient for that market, the
pick remains `pending_verification`. It is not counted as won, lost, void, or in
win-rate calculations. Retries are bounded and idempotent. Voids, postponed
matches, non-starters, and provider-specific push rules are represented
explicitly instead of being folded into wins or losses.

## Failure Handling

- Wrong or missing Playdoit route identity: return no detail markets.
- Residual market nodes from another event: reject the entire affected detail
  observation.
- Partial progressive render: wait within the bound, then omit only incomplete
  quote groups.
- API-Football unavailable or over budget: disable player props for that window.
- Player not in confirmed starting eleven: reject the prop.
- Quote changed after selection: update an undelivered draft or discard it;
  never mutate a delivered pick.
- Both PCs offline: no collection occurs; cloud delivery may process only an
  already persisted exact batch.
- A PC returns late: stale scheduled work exits without replay.
- No qualifying candidates: publish nothing and record a healthy no-pick run.

## Verification Strategy

Implementation follows test-driven development. Required tests include:

1. A foreign event route cannot contribute markets.
2. Buttons outside the one verified detail container are ignored.
3. Explicit first-half/team metadata cannot become a full-game event market.
4. An incomplete progressive total waits for its second side.
5. Scrolling stabilizes on market/selection IDs and remains bounded.
6. Arbitrary official market and selection IDs survive normalization unchanged.
7. One-way official props are distinct from incomplete two-way groups.
8. Player props fail without a confirmed starter and pass with an exact starter.
9. Fixture/player ambiguity fails closed.
10. The lineup budget, cache, and provider headers prevent quota exhaustion.
11. Adaptive scheduling rejects stale runs and gives one PC the distributed
    lock.
12. More scans do not create duplicate deliveries.
13. Daily publication count is 0-6, with one free for 1-5 and two free for six.
14. Free picks use different matches and are not parlays.
15. Unknown result types remain pending and do not affect performance.
16. Existing H2H, totals, spreads, Telegram, social, dry-run, and recovery tests
    continue to pass.

A controlled live dry-run must report event count, total catalog size,
publishable candidates by family, exclusions by reason, lineup API usage,
market coverage, and zero external publication. Only after the complete test
suite and a second code review pass may a real workflow be dispatched.

## Acceptance Criteria

- Playdoit markets cannot cross event boundaries.
- All observed official market shapes are preserved without coercion.
- Only exact, active, current source quotes become candidates.
- Soccer player props require a confirmed starting eleven.
- The adaptive scheduler runs minimized in the background on either PC and does
  not replay stale work.
- API-Football lineup usage stays at or below 40 requests per quota day.
- Publication never exceeds six picks per Mexico date and follows the approved
  free/premium split.
- Multiple scans are idempotent and do not spam Telegram or social networks.
- Result records never guess unsupported outcomes.
- Focused tests, the full Python suite, frontend tests/build, compilation, and a
  safe live dry-run all pass before production execution.

## Non-Goals

- Claiming or guaranteeing profitability or win probability.
- Circumventing Playdoit access controls, CAPTCHA, or geographic restrictions.
- Waking or powering on either Windows PC.
- Treating predicted lineups as confirmed.
- Publishing in-play lines in this release.
- Using an unresolved market in reported performance.

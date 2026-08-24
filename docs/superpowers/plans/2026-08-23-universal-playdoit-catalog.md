# Universal Playdoit Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provenance-safe Playdoit detail collector that preserves every official market and selection while retaining canonical H2H, totals, and spread projections.

**Architecture:** Scope React extraction to the exact routed event and its single details container, accumulate progressively rendered market groups by official IDs, and normalize unknown market shapes into generic source-backed `Market` objects. Extend candidates and public projections with official display/source fields without changing existing canonical behavior.

**Tech Stack:** Python 3.11, Selenium/undetected-chromedriver, React fiber inspection through `execute_script`, immutable dataclasses, pytest, GitHub Actions dry-run workflow.

---

## Scope and File Map

This is phase 1 of the approved design. Confirmed lineups/adaptive scheduling
and autonomous result resolvers receive separate plans after this plan produces
a tested universal catalog.

- Modify `backend/playdoit_source.py`: exact detail-route/container provenance,
  progressive group accumulation, canonical and generic market normalization.
- Modify `backend/scraper_domain.py`: optional official source/display metadata
  on immutable outcomes and markets.
- Modify `backend/pick_selection.py`: generic Playdoit candidate validation and
  propagation of official market/selection metadata.
- Modify `backend/scraper.py`: prompt and persisted projection use official
  display/source fields and report generic coverage.
- Modify `tests/test_playdoit_source.py`: provenance, progressive rendering,
  one-way market, and normalization tests.
- Modify `tests/test_scraper_domain.py`: immutable source metadata tests.
- Modify `tests/test_pick_selection.py`: generic candidate identity and
  fail-closed validation tests.
- Modify `tests/test_scraper_ai.py` and `tests/test_scraper_cli.py`: prompt,
  projection, coverage, and audit-field tests.
- Keep `lab/inspect_playdoit_detail_dom.py` ignored and diagnostic-only.
- Do not stage the pre-existing `.gitignore` modification.

### Task 1: Bind React detail extraction to the current event

**Files:**
- Modify: `backend/playdoit_source.py:380-443`
- Test: `tests/test_playdoit_source.py:542-805`

- [ ] **Step 1: Write failing provenance tests**

Add drivers/tests that verify arguments are passed rather than interpolated,
foreign routes return no groups, and only the exact detail container is queried:

```python
class RoutedReactDetailDriver(ReactDetailMarketDriver):
    def __init__(self, raw=None):
        super().__init__()
        self.raw = raw if raw is not None else super().execute_script(
            "/* playdoit:extract-react-detail-markets */"
        )
        self.args = None

    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        self.script = script
        self.args = args
        return self.raw


def test_react_detail_passes_exact_event_identity_as_script_arguments():
    driver = RoutedReactDetailDriver()
    extract_react_detail_markets(
        driver, "16848649", "Fulham", "Chelsea"
    )
    assert driver.args == ("16848649", "Fulham", "Chelsea")
    assert "16848649" not in driver.script
    assert "EventDetailsMarketsContainer" in driver.script
    assert "detailRoot.querySelectorAll" in driver.script
    assert "host.shadowRoot.querySelectorAll('button" not in driver.script


def test_react_detail_rejects_unverified_route_snapshot():
    driver = RoutedReactDetailDriver(raw={
        "verified": False,
        "source_event_id": "999",
        "groups": ReactDetailMarketDriver().execute_script(
            "/* playdoit:extract-react-detail-markets */"
        ),
    })
    assert extract_react_detail_markets(
        driver, "16848649", "Fulham", "Chelsea"
    ) == []
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_playdoit_source.py -k "exact_event_identity or unverified_route" -q
```

Expected: failures because `extract_react_detail_markets` lacks `event_id` and
the current script scans the full shadow root.

- [ ] **Step 3: Implement exact route and container verification**

Change `_EXTRACT_REACT_DETAIL_MARKETS_SCRIPT` to accept the official identity,
fail closed before reading odds, and return a provenance envelope:

```javascript
var sourceId = String(arguments[0] || '').trim();
var home = String(arguments[1] || '').trim().toLocaleLowerCase();
var away = String(arguments[2] || '').trim().toLocaleLowerCase();
var route = new URLSearchParams(String(window.location.hash || '').replace(/^#/, ''));
if (!sourceId || route.get('eventId') !== sourceId) {
  return {verified: false, source_event_id: route.get('eventId') || '', groups: []};
}
var roots = Array.from(host.shadowRoot.querySelectorAll(
  '[class*="EventDetailsMarketsContainer"]'
));
if (roots.length !== 1) {
  return {verified: false, source_event_id: sourceId, groups: []};
}
var detailRoot = roots[0];
var detailText = (detailRoot.innerText || '').toLocaleLowerCase();
if (!detailText.includes(home) || !detailText.includes(away)) {
  return {verified: false, source_event_id: sourceId, groups: []};
}
var buttons = Array.from(detailRoot.querySelectorAll(
  'button[class*="OddBoxButton"]'
));
```

For each button, mark rather than silently discard promotional offers:

```javascript
var offerRoot = button.closest('[class*="Boosted"], [class*="PlayBoost"]');
var offerKind = offerRoot ? 'boosted' : 'standard';
var offerDescription = offerRoot ? (offerRoot.innerText || '').trim() : '';
```

Copy only explicit primitive source metadata into the market group:

```javascript
period: market.period,
periodName: market.periodName,
scope: market.scope,
scopeName: market.scopeName,
competitorId: market.competitorId,
teamId: market.teamId,
participantId: market.participantId,
shortName: market.shortName,
variant: market.variant,
offerKind: offerKind,
offerDescription: offerDescription
```

An absent field stays absent. Python must not manufacture a period or scope.

Return:

```javascript
return {
  verified: true,
  source_event_id: sourceId,
  groups: Object.keys(groups).map(function(key) { return groups[key]; })
};
```

Change the Python signature and enforce the envelope:

```python
def extract_react_detail_groups(
    driver: Any, event_id: str, home: str, away: str
) -> list[dict[str, Any]]:
    raw = driver.execute_script(
        _EXTRACT_REACT_DETAIL_MARKETS_SCRIPT, event_id, home, away
    )
    if (
        not isinstance(raw, Mapping)
        or raw.get("verified") is not True
        or str(raw.get("source_event_id") or "").strip() != event_id
        or not isinstance(raw.get("groups"), list)
    ):
        return []
    return [dict(row) for row in raw["groups"] if isinstance(row, Mapping)]
```

- [ ] **Step 4: Thread `event_id` through production and tests**

Use:

```python
details = extract_supported_markets(
    driver,
    event_id,
    home,
    away,
    wait_factory=wait_factory,
    timeout=timeout,
)
```

Update all direct test calls to the same positional order.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_playdoit_source.py -k "react_detail or supported_market_extraction or current_react_snapshot" -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the provenance boundary**

```powershell
git add -- backend/playdoit_source.py tests/test_playdoit_source.py
git commit -m "fix: bind Playdoit markets to routed event"
```

### Task 2: Wait for stable, complete progressive market groups

**Files:**
- Modify: `backend/playdoit_source.py:908-1092`
- Test: `tests/test_playdoit_source.py:597-805`

- [ ] **Step 1: Write failing progressive-render tests**

```python
class PartialThenCompleteTotalDriver(RoutedReactDetailDriver):
    def __init__(self):
        super().__init__(raw=[])
        self.polls = 0

    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        self.polls += 1
        odds = [{
            "id": "over-1", "name": "Más de 2.5", "oddStatus": 0,
            "price": 1.8, "sv": "2.5", "typeId": 12,
        }]
        if self.polls >= 3:
            odds.append({
                "id": "under-1", "name": "Menos de 2.5", "oddStatus": 0,
                "price": 2.0, "sv": "2.5", "typeId": 13,
            })
        return {"verified": True, "source_event_id": args[0], "groups": [{
            "market": {"id": "total-1", "name": "Total", "sv": "2.5", "typeId": 18},
            "odds": odds,
        }]}


def test_progressive_total_waits_for_both_official_sides():
    driver = PartialThenCompleteTotalDriver()
    markets = extract_supported_markets(
        driver, "16848649", "Fulham", "Chelsea",
        wait_factory=ImmediateWait, timeout=0.01,
    )
    assert driver.polls >= 3
    assert [row["key"] for row in markets] == ["totals"]
```

Add a second test where market IDs appear across scroll/polls and assert the
final catalog contains the union without duplicate odd IDs.

- [ ] **Step 2: Run the tests and verify RED**

```powershell
python -m pytest tests/test_playdoit_source.py -k "progressive_total or progressive_market_union" -q
```

Expected: early completion or missing groups.

- [ ] **Step 3: Add deterministic group merging**

```python
def _merge_react_detail_groups(
    accumulated: dict[str, dict[str, Any]],
    observed: Iterable[Mapping[str, Any]],
) -> None:
    for row in observed:
        market = row.get("market")
        odds = row.get("odds")
        if not isinstance(market, Mapping) or not isinstance(odds, list):
            continue
        market_id = str(market.get("id") or "").strip()
        if not market_id:
            continue
        target = accumulated.setdefault(
            market_id, {"market": dict(market), "odds": []}
        )
        by_id = {
            str(odd.get("id")): odd
            for odd in target["odds"]
            if isinstance(odd, Mapping) and odd.get("id") is not None
        }
        for odd in odds:
            if isinstance(odd, Mapping) and odd.get("id") is not None:
                by_id[str(odd["id"])] = dict(odd)
        target["odds"] = list(by_id.values())
```

Canonical totals return nothing until exactly one valid over and under share
the line. Canonical H2H requires the sport-format outcome set. Spreads continue
to require exact opposing pairs.

- [ ] **Step 4: Add bounded scroll/stability signaling**

Add `_ADVANCE_REACT_DETAIL_MARKETS_SCRIPT` that scrolls only the verified
details container and returns its `(scrollTop, scrollHeight, clientHeight)`.
The wait callback merges groups and succeeds after two consecutive identical
sorted `(market_id, odd_id)` signatures, or after a complete known deep market
set is stable. It never sleeps or loops without the existing timeout bound.

```python
signature = tuple(sorted(
    (market_id, str(odd.get("id")))
    for market_id, row in accumulated.items()
    for odd in row["odds"]
    if isinstance(odd, Mapping) and odd.get("id") is not None
))
```

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
python -m pytest tests/test_playdoit_source.py -k "react_detail or progressive or spread" -q
```

Expected: all selected tests pass with no early partial total.

- [ ] **Step 6: Commit progressive collection**

```powershell
git add -- backend/playdoit_source.py tests/test_playdoit_source.py
git commit -m "fix: stabilize progressive Playdoit markets"
```

### Task 3: Preserve official source metadata in domain objects

**Files:**
- Modify: `backend/scraper_domain.py:55-120`
- Test: `tests/test_scraper_domain.py`

- [ ] **Step 1: Write failing immutable metadata tests**

```python
def test_market_preserves_official_display_and_source_identity():
    outcome = Outcome(
        "playdoit_odd:4132889965", "Más de 0.5 remates", 1.75,
        source_id="4132889965",
    )
    market = Market(
        "playdoit_market:1614791472",
        "source_unspecified",
        None,
        (outcome,),
        bookmaker_key="playdoit",
        name="Remates a Puerta - Cole Palmer",
        source_id="1614791472",
        sport_market_id="70520",
    )
    assert market.name == "Remates a Puerta - Cole Palmer"
    assert market.source_id == "1614791472"
    assert market.outcomes[0].source_id == "4132889965"
```

Add negative tests for blank source IDs/names when provided and mutation.
Add a source-backed price test at decimal `80.0`; official identified props may
exceed the old canonical safety ceiling of `50.0`.

- [ ] **Step 2: Run the tests and verify RED**

```powershell
python -m pytest tests/test_scraper_domain.py -k "official_display or source_identity" -q
```

Expected: constructors reject the new keyword arguments.

- [ ] **Step 3: Add optional validated metadata**

Append defaulted fields so existing positional constructors remain compatible:

```python
@dataclass(frozen=True, slots=True)
class Outcome:
    key: str
    name: str
    price: float
    source_id: str | None = None


@dataclass(frozen=True, slots=True)
class Market:
    key: str
    period: str
    line: float | None
    outcomes: tuple[Outcome, ...]
    bookmaker_key: str | None = None
    name: str | None = None
    source_id: str | None = None
    sport_market_id: str | None = None
```

Normalize every non-`None` optional string with `_required_text`; keep display
name case and canonicalize only identity keys.

Keep the `50.0` maximum for outcomes without a source ID. For an official
source-backed outcome, allow finite decimal prices through `1000.0`:

```python
maximum_price = 1000.0 if self.source_id is not None else 50.0
if not 1.01 <= price <= maximum_price:
    raise ValueError(
        f"price must be decimal odds between 1.01 and {maximum_price:g}"
    )
```

- [ ] **Step 4: Run domain tests and verify GREEN**

```powershell
python -m pytest tests/test_scraper_domain.py -q
```

Expected: all domain tests pass.

- [ ] **Step 5: Commit domain metadata**

```powershell
git add -- backend/scraper_domain.py tests/test_scraper_domain.py
git commit -m "feat: preserve sportsbook source metadata"
```

### Task 4: Normalize arbitrary official Playdoit markets

**Files:**
- Modify: `backend/playdoit_source.py:630-825,908-1030`
- Test: `tests/test_playdoit_source.py`

- [ ] **Step 1: Write failing generic market tests**

```python
def test_unknown_official_market_becomes_source_backed_market():
    raw = fixture_event()
    raw["markets"].append({
        "key": "source_market",
        "title": "Remates a Puerta - Cole Palmer",
        "period": "source_unspecified",
        "scope": "source_unspecified",
        "source_market_id": "player-shots-1",
        "sport_market_id": "shots",
        "outcomes": [{
            "key": "playdoit_odd:shots-over-05",
            "source_selection_id": "shots-over-05",
            "name": "Más de 0.5",
            "price": 1.75,
        }],
    })
    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )
    market = event.markets[-1]
    assert market.key == "playdoit_market:player-shots-1"
    assert market.name == "Remates a Puerta - Cole Palmer"
    assert market.outcomes[0].source_id == "shots-over-05"
```

Add tests that an explicit first-half `Total` is preserved as a generic source
market but is not projected as canonical `totals/full_game`, and that missing
market/odd IDs fail closed.

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests/test_playdoit_source.py -k "source_backed_market or explicit_first_half" -q
```

Expected: generic markets are omitted by `_normalize_market`.

- [ ] **Step 3: Emit a generic raw record for every complete group**

Add:

```python
def _generic_react_market_from_group(
    raw: Mapping[str, Any],
) -> dict[str, Any] | None:
    market = raw.get("market")
    odds = raw.get("odds")
    if not isinstance(market, Mapping) or not isinstance(odds, list):
        return None
    market_id = str(market.get("id") or "").strip()
    title = str(market.get("name") or "").strip()
    if not market_id or not title:
        return None
    outcomes = []
    for odd in odds:
        if not isinstance(odd, Mapping) or odd.get("oddStatus") not in (None, 0):
            continue
        odd_id = str(odd.get("id") or "").strip()
        name = str(odd.get("name") or "").strip()
        try:
            price = _strict_number(odd.get("price"), "price", price=True)
        except (TypeError, ValueError, OverflowError):
            continue
        if odd_id and name:
            outcomes.append({
                "key": f"playdoit_odd:{odd_id}",
                "source_selection_id": odd_id,
                "name": name,
                "price": price,
            })
    if not outcomes:
        return None
    return {
        "key": "source_market",
        "title": title,
        "period": str(market.get("period") or "source_unspecified"),
        "scope": str(market.get("scope") or "source_unspecified"),
        "source_market_id": market_id,
        "sport_market_id": (
            str(market["sportMarketId"])
            if market.get("sportMarketId") is not None else None
        ),
        "offer_kind": str(market.get("offerKind") or "standard"),
        "offer_description": str(market.get("offerDescription") or "").strip(),
        "outcomes": outcomes,
    }
```

For exact canonical names, emit the validated canonical projection instead of a
duplicate generic record. If explicit metadata contradicts full-game/event,
emit only the generic record.

For `offer_kind == "boosted"`, require a non-empty complete offer description
plus official market and odd IDs. If those fields are missing, record the
exclusion reason `incomplete_boost_definition`; do not convert promotional text
into a selection. Add one positive complete-boost test and one negative
description-only boost test.

- [ ] **Step 4: Normalize `source_market` records**

```python
def _normalize_source_market(raw: Mapping[str, object]) -> Market:
    source_market_id = _required_text(
        raw.get("source_market_id"), "source market id"
    )
    title = _required_text(raw.get("title"), "market title")
    period_value = str(raw.get("period") or "source_unspecified").strip()
    outcomes = tuple(
        Outcome(
            _required_text(row.get("key"), "outcome key"),
            _required_text(row.get("name"), "outcome name"),
            _strict_number(row.get("price"), "price", price=True),
            source_id=_required_text(
                row.get("source_selection_id"), "source selection id"
            ),
        )
        for row in _raw_outcomes(raw)
    )
    return Market(
        f"playdoit_market:{source_market_id}",
        period_value,
        None,
        outcomes,
        bookmaker_key="playdoit",
        name=title,
        source_id=source_market_id,
        sport_market_id=(
            str(raw["sport_market_id"]).strip()
            if raw.get("sport_market_id") is not None else None
        ),
    )
```

Route `key == "source_market"` to this function before the canonical supported
market check. Duplicate source selection IDs or contradictory revisions remain
fail-closed through existing identity/conflict logic.

- [ ] **Step 5: Run normalization tests and verify GREEN**

```powershell
python -m pytest tests/test_playdoit_source.py -q
```

Expected: all Playdoit tests pass.

- [ ] **Step 6: Commit generic normalization**

```powershell
git add -- backend/playdoit_source.py tests/test_playdoit_source.py
git commit -m "feat: normalize all official Playdoit markets"
```

### Task 5: Build and project generic source-backed candidates

**Files:**
- Modify: `backend/pick_selection.py:18-321,372-478`
- Modify: `backend/scraper.py:1273-1470,2015-2058`
- Test: `tests/test_pick_selection.py`
- Test: `tests/test_scraper_ai.py`
- Test: `tests/test_scraper_cli.py`

- [ ] **Step 1: Write failing generic candidate tests**

```python
def test_build_candidates_preserves_generic_market_display_and_ids():
    event = source_market_event()
    candidate = build_candidates([event])[0]
    assert candidate.market_key == "playdoit_market:player-shots-1"
    assert candidate.market_name == "Remates a Puerta - Cole Palmer"
    assert candidate.source_market_id == "player-shots-1"
    assert candidate.source_selection_id == "shots-over-05"
```

Add a negative constructor test requiring all three source/display fields for a
`playdoit_market:` candidate, plus a prompt/projection test asserting that the
official name is displayed while the audit key retains the source ID.

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests/test_pick_selection.py tests/test_scraper_ai.py tests/test_scraper_cli.py -k "generic_market or official_market_display" -q
```

Expected: generic markets are filtered or metadata attributes do not exist.

- [ ] **Step 3: Extend `CandidatePick` compatibly**

Append defaulted fields:

```python
market_name: str | None = None
source_market_id: str | None = None
source_selection_id: str | None = None
```

Validation becomes:

```python
canonical = (self.market_key, self.period) in SUPPORTED_MARKETS
generic = self.market_key.startswith("playdoit_market:")
if not canonical and not generic:
    raise ValueError("candidate market and period are not supported")
if generic:
    for field in ("market_name", "source_market_id", "source_selection_id"):
        object.__setattr__(
            self, field, _required_text(getattr(self, field), field)
        )
    if self.market_key != f"playdoit_market:{self.source_market_id}":
        raise ValueError("generic market key must contain its source id")
else:
    if self.selection_key not in SUPPORTED_SELECTIONS[self.market_key]:
        raise ValueError("candidate selection is not supported for its market")
```

Populate the fields in `_candidate_from_evidence` from `Market` and `Outcome`.
Keep `_candidate_id` version 1 unchanged because generic market/selection keys
already contain the official IDs.

Use the same source-aware price ceiling as `Outcome`: canonical candidates stay
at or below `50.0`; a generic candidate with all official source IDs may be at
or below `1000.0`.

- [ ] **Step 4: Make evidence grouping safe for generic markets**

Use source market identity for exclusivity and never cross-compare a generic
Playdoit prop against canonical Odds API markets:

```python
def _required_market_outcomes(candidate: CandidatePick) -> frozenset[str]:
    if candidate.market_key.startswith("playdoit_market:"):
        return frozenset({candidate.selection_key})
    # existing h2h/totals/spreads branches remain unchanged
```

The final one-pick-per-physical-event cap belongs to the separate
daily-publication implementation plan; this phase only ensures one generic
market does not collide with another.

- [ ] **Step 5: Use official display/source fields in prompt and projection**

Add to `_candidate_prompt_row`:

```python
"market_name": candidate.market_name or candidate.market_key,
"source_market_id": candidate.source_market_id,
"source_selection_id": candidate.source_selection_id,
```

Project:

```python
display_market = candidate.market_name or candidate.market_key
row["mercado"] = display_market
row["source_market_key"] = _source_market_audit_key(candidate)
row["source_selection_key"] = (
    candidate.source_selection_id or candidate.selection_key
)
```

Include `source_market_id` in `_source_market_audit_key` without exposing it as
the public display label.

- [ ] **Step 6: Run focused tests and verify GREEN**

```powershell
python -m pytest tests/test_pick_selection.py tests/test_scraper_ai.py tests/test_scraper_cli.py -q
```

Expected: all selected files pass.

- [ ] **Step 7: Commit candidate/projection support**

```powershell
git add -- backend/pick_selection.py backend/scraper.py tests/test_pick_selection.py tests/test_scraper_ai.py tests/test_scraper_cli.py
git commit -m "feat: rank source-backed Playdoit markets"
```

### Task 6: Verify live catalog coverage without publishing

**Files:**
- Modify: `backend/scraper.py:316-334,915-930`
- Modify: `tests/test_scraper_cli.py`
- Verify: `scripts/windows/Invoke-ReyTacoDryRun.ps1`

- [ ] **Step 1: Write a failing generic coverage test**

```python
def test_market_coverage_counts_generic_source_markets():
    coverage = _verified_market_coverage([record_with_generic_candidates()])
    assert coverage == {
        "h2h": 1,
        "totals": 0,
        "spreads": 0,
        "source_markets": 1,
    }
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m pytest tests/test_scraper_cli.py -k "coverage_counts_generic" -q
```

Expected: missing `source_markets` coverage.

- [ ] **Step 3: Add generic coverage and exclusion diagnostics**

Initialize `source_markets` in `_verified_market_coverage`, increment it for
`candidate.market_key.startswith("playdoit_market:")`, and log:

```python
print(
    "   market_coverage="
    f"h2h:{coverage['h2h']} totals:{coverage['totals']} "
    f"spreads:{coverage['spreads']} "
    f"source_markets:{coverage['source_markets']}"
)
```

Do not print raw tokens, credentials, full React objects, or player personal
data beyond official public sports names.

- [ ] **Step 4: Run all focused tests**

```powershell
python -m pytest tests/test_playdoit_source.py tests/test_scraper_domain.py tests/test_pick_selection.py tests/test_scraper_ai.py tests/test_scraper_cli.py -q
```

Expected: all focused tests pass.

- [ ] **Step 5: Run the full verification suite**

```powershell
python -m pytest -q
python -m compileall -q backend tests
npm --prefix frontend run test
npm --prefix frontend run build
git diff --check -- backend/playdoit_source.py backend/scraper_domain.py backend/pick_selection.py backend/scraper.py tests
```

Expected: zero failing tests, successful compilation/build, and no diff-check
errors.

- [ ] **Step 6: Run a safe live dry-run**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/windows/Invoke-ReyTacoDryRun.ps1
```

Expected: `RESULT=DRY_RUN_SAFE`, no persisted batch, no Telegram/Meta delivery,
route-bound event details, and nonzero source-market coverage when Playdoit
offers eligible events.

- [ ] **Step 7: Request a second code review**

Review specifically for cross-event leakage, invented period/scope, incomplete
progressive groups, generic candidate collisions, and accidental secret/public
payload exposure. Resolve every blocking finding with a reproducing test.

- [ ] **Step 8: Commit diagnostics and phase completion**

```powershell
git add -- backend/scraper.py tests/test_scraper_cli.py
git commit -m "test: verify universal Playdoit catalog"
```

Do not push or dispatch the production workflow until the review is clean and
fresh verification evidence is recorded.

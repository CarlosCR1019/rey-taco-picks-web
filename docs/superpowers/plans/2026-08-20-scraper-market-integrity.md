# Scraper Market Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every published pick is built from a real future event and an exact observed market outcome, while limiting AI to ranking and explaining verified candidates.

**Architecture:** Source adapters normalize Playdoit and The Odds API into immutable event/market objects. Deterministic candidate construction owns event identity, market, line, selection, and price; AI receives candidate IDs and can return only an ordering plus rationale that is validated against the catalog.

**Tech Stack:** Python 3.11+ dataclasses, ZoneInfo, Selenium, Groq SDK, urllib, unittest/pytest, JSON fixtures.

---

## File Structure

- Create `backend/scraper_domain.py` for normalized event, market, outcome, and candidate types.
- Create `backend/odds_source.py` for The Odds API normalization.
- Create `backend/playdoit_source.py` for Playdoit raw-record normalization and Selenium extraction.
- Create `backend/pick_selection.py` for deterministic candidates, evidence scoring, and AI response validation.
- Modify `backend/scraper.py` to orchestrate adapters rather than accept factual market fields from free-form AI output.
- Add sanitized JSON fixtures under `tests/fixtures/` and focused tests under `tests/`.

### Task 1: Define immutable normalized market objects

**Files:**
- Create: `backend/scraper_domain.py`
- Create: `tests/test_scraper_domain.py`

- [ ] **Step 1: Write failing domain tests**

```python
from datetime import datetime, timezone
import pytest

from backend.scraper_domain import Event, Market, Outcome


def test_market_looks_up_named_outcomes_without_using_position():
    market = Market(
        key="h2h",
        period="full_game",
        line=None,
        outcomes=(Outcome("away", "Tigres", 2.40), Outcome("home", "América", 1.70)),
    )
    assert market.outcome("home").price == 1.70


def test_event_rejects_naive_or_past_start_times():
    now = datetime(2026, 8, 20, 18, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="timezone-aware"):
        Event("playdoit", "1", "soccer", "Liga MX", "A", "B", datetime(2026, 8, 21), now, ())
    with pytest.raises(ValueError, match="future"):
        Event("playdoit", "1", "soccer", "Liga MX", "A", "B", now, now, ())
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_scraper_domain.py -q`

Expected: FAIL because `backend.scraper_domain` does not exist.

- [ ] **Step 3: Implement the domain types**

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Outcome:
    key: str
    name: str
    price: float

    def __post_init__(self):
        if not 1.01 <= self.price <= 50:
            raise ValueError("decimal price must be between 1.01 and 50")


@dataclass(frozen=True)
class Market:
    key: str
    period: str
    line: float | None
    outcomes: tuple[Outcome, ...]

    def outcome(self, key: str) -> Outcome:
        return next(outcome for outcome in self.outcomes if outcome.key == key)


@dataclass(frozen=True)
class Event:
    source: str
    source_event_id: str
    sport: str
    league: str
    home_team: str
    away_team: str
    starts_at: datetime
    observed_at: datetime
    markets: tuple[Market, ...]

    def __post_init__(self):
        if self.starts_at.tzinfo is None or self.observed_at.tzinfo is None:
            raise ValueError("event timestamps must be timezone-aware")
        if self.starts_at <= self.observed_at:
            raise ValueError("event must start in the future")
        if not self.source_event_id or not self.home_team or not self.away_team:
            raise ValueError("event identity and competitors are required")
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_scraper_domain.py -q`

Expected: `2 passed`.

```bash
git add backend/scraper_domain.py tests/test_scraper_domain.py
git commit -m "feat: define normalized sportsbook markets"
```

### Task 2: Normalize The Odds API without fabricated prices

**Files:**
- Create: `backend/odds_source.py`
- Create: `tests/test_odds_source.py`
- Create: `tests/fixtures/odds_api_event.json`
- Modify: `backend/scraper.py`

- [ ] **Step 1: Save a sanitized fixture with reordered outcomes**

```json
{
  "id": "event-123",
  "sport_key": "soccer_mexico_ligamx",
  "sport_title": "Liga MX",
  "commence_time": "2026-08-21T02:00:00Z",
  "home_team": "América",
  "away_team": "Tigres",
  "bookmakers": [{
    "key": "book-a",
    "markets": [{
      "key": "h2h",
      "outcomes": [
        {"name": "Tigres", "price": 2.40},
        {"name": "Draw", "price": 3.30},
        {"name": "América", "price": 1.70}
      ]
    }]
  }]
}
```

- [ ] **Step 2: Write failing adapter tests**

```python
from datetime import datetime, timezone
import json
from pathlib import Path

from backend.odds_source import normalize_odds_event


FIXTURE = Path(__file__).parent / "fixtures" / "odds_api_event.json"


def test_outcomes_are_named_even_when_api_order_changes():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    event = normalize_odds_event(raw, datetime(2026, 8, 20, 20, tzinfo=timezone.utc))
    assert event.markets[0].outcome("home").name == "América"
    assert event.markets[0].outcome("home").price == 1.70


def test_missing_market_produces_no_market_instead_of_default_odds():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["bookmakers"] = []
    event = normalize_odds_event(raw, datetime(2026, 8, 20, 20, tzinfo=timezone.utc))
    assert event.markets == ()
```

- [ ] **Step 3: Run tests and verify RED**

Run: `python -m pytest tests/test_odds_source.py -q`

Expected: FAIL because `backend.odds_source` does not exist.

- [ ] **Step 4: Implement named-outcome normalization**

```python
from datetime import datetime

from backend.scraper_domain import Event, Market, Outcome


def _outcome_key(name: str, home: str, away: str) -> str:
    if name.casefold() == home.casefold():
        return "home"
    if name.casefold() == away.casefold():
        return "away"
    if name.casefold() in {"draw", "empate"}:
        return "draw"
    return name.casefold()


def normalize_odds_event(raw: dict, observed_at: datetime) -> Event:
    home, away = raw["home_team"], raw["away_team"]
    markets, seen = [], set()
    for bookmaker in raw.get("bookmakers", []):
        for item in bookmaker.get("markets", []):
            outcomes = tuple(
                Outcome(_outcome_key(row["name"], home, away), row["name"], float(row["price"]))
                for row in item.get("outcomes", []) if row.get("price") is not None
            )
            signature = (item.get("key"), tuple((row.key, row.price) for row in outcomes))
            if outcomes and signature not in seen:
                seen.add(signature)
                markets.append(Market(str(item["key"]), "full_game", None, outcomes))
    return Event(
        "the_odds_api", str(raw["id"]), str(raw.get("sport_key") or "unknown"),
        str(raw.get("sport_title") or "Deportes"), home, away,
        datetime.fromisoformat(raw["commence_time"].replace("Z", "+00:00")),
        observed_at, tuple(markets),
    )
```

The request URL must explicitly include `oddsFormat=decimal`. Delete every synthetic odds fallback.

- [ ] **Step 5: Run tests, regression search, and commit**

Run: `python -m pytest tests/test_odds_source.py -q && rg -n '1\.85.*3\.20.*2\.10' backend`

Expected: tests pass and the search returns no synthetic fallback.

```bash
git add backend/odds_source.py tests/test_odds_source.py tests/fixtures/odds_api_event.json backend/scraper.py
git commit -m "feat: normalize named market outcomes"
```

### Task 3: Parse Playdoit dates and markets with explicit identity

**Files:**
- Create: `backend/playdoit_source.py`
- Create: `tests/test_playdoit_source.py`
- Create: `tests/fixtures/playdoit_event.json`
- Modify: `backend/scraper.py`

- [ ] **Step 1: Save a sanitized Playdoit fixture**

```json
{
  "event_id": "playdoit-456",
  "sport": "soccer",
  "league": "Liga MX",
  "home": "América",
  "away": "Tigres",
  "date_label": "21/08",
  "time_label": "20:00",
  "markets": [{
    "key": "h2h",
    "period": "full_game",
    "outcomes": [
      {"key": "home", "name": "América", "price": "1.72"},
      {"key": "draw", "name": "Empate", "price": "3.25"},
      {"key": "away", "name": "Tigres", "price": "2.35"}
    ]
  }]
}
```

- [ ] **Step 2: Write failing date and market tests**

```python
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.playdoit_source import normalize_playdoit_event, resolve_mexico_start


FIXTURE = Path(__file__).parent / "fixtures" / "playdoit_event.json"
MEXICO = ZoneInfo("America/Mexico_City")


def test_year_rollover_uses_next_year_not_a_hardcoded_date():
    observed = datetime(2026, 12, 31, 10, tzinfo=MEXICO)
    assert resolve_mexico_start("01/01", "12:00", observed).year == 2027


def test_fixture_preserves_exact_market_and_price():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    event = normalize_playdoit_event(raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO))
    assert event.source_event_id == "playdoit-456"
    assert event.markets[0].outcome("home").price == 1.72
```

- [ ] **Step 3: Run tests and verify RED**

Run: `python -m pytest tests/test_playdoit_source.py -q`

Expected: FAIL because `backend.playdoit_source` does not exist.

- [ ] **Step 4: Implement pure Playdoit normalization**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.scraper_domain import Event, Market, Outcome


MEXICO = ZoneInfo("America/Mexico_City")


def resolve_mexico_start(date_label: str, time_label: str, observed_at: datetime) -> datetime:
    day, month = (int(value) for value in date_label.replace("-", "/").split("/")[:2])
    hour, minute = (int(value) for value in time_label.split(":")[:2])
    candidate = datetime(observed_at.year, month, day, hour, minute, tzinfo=MEXICO)
    if candidate < observed_at and (observed_at.date() - candidate.date()).days > 180:
        candidate = candidate.replace(year=observed_at.year + 1)
    return candidate


def normalize_playdoit_event(raw: dict, observed_at: datetime) -> Event:
    markets = tuple(
        Market(
            item["key"], item.get("period", "full_game"),
            float(item["line"]) if item.get("line") is not None else None,
            tuple(Outcome(row["key"], row["name"], float(row["price"])) for row in item.get("outcomes", [])),
        )
        for item in raw.get("markets", []) if item.get("outcomes")
    )
    return Event(
        "playdoit", raw["event_id"], raw["sport"], raw["league"], raw["home"], raw["away"],
        resolve_mexico_start(raw["date_label"], raw["time_label"], observed_at), observed_at, markets,
    )
```

- [ ] **Step 5: Make Selenium extraction wait for each market tab**

Pass source text as `execute_script` arguments instead of interpolating it into JavaScript. Click one supported tab in Python and wait for changed content:

```python
previous = market_signature(driver)
tab.click()
WebDriverWait(driver, 8).until(lambda active: market_signature(active) not in {"", previous})
raw_markets.extend(extract_visible_markets(driver))
```

Delete the hardcoded `"18/08"` fallback. Reject records without both date and time as `missing_start_time`.

- [ ] **Step 6: Run tests, search hardcoded dates, and commit**

Run: `python -m pytest tests/test_playdoit_source.py -q && rg -n '18/08|19/08' backend/scraper.py backend/playdoit_source.py`

Expected: tests pass and no hardcoded operational date remains.

```bash
git add backend/playdoit_source.py backend/scraper.py tests/test_playdoit_source.py tests/fixtures/playdoit_event.json
git commit -m "feat: extract structured Playdoit markets"
```

### Task 4: Construct picks only from supported verified outcomes

**Files:**
- Create: `backend/pick_selection.py`
- Create: `tests/test_pick_selection.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add complete normalized fixtures**

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest

from backend.scraper_domain import Event, Market, Outcome


MEXICO = ZoneInfo("America/Mexico_City")
OBSERVED = datetime(2026, 8, 20, 10, tzinfo=MEXICO)


@pytest.fixture
def event_fixture():
    return Event(
        "playdoit", "event-1", "soccer", "Liga MX", "América", "Tigres",
        OBSERVED + timedelta(hours=8), OBSERVED,
        (Market("h2h", "full_game", None, (Outcome("home", "América", 1.72), Outcome("away", "Tigres", 2.35))),),
    )


@pytest.fixture
def partial_market_event():
    return Event(
        "playdoit", "event-2", "baseball", "MLB", "Dodgers", "Padres",
        OBSERVED + timedelta(hours=10), OBSERVED,
        (Market("totals", "first_inning", 0.5, (Outcome("over", "Más de 0.5", 1.80),)),),
    )


@pytest.fixture
def candidate_today(event_fixture):
    from backend.pick_selection import build_candidates
    return build_candidates([event_fixture])[0]


@pytest.fixture
def candidate_tomorrow(candidate_today):
    from dataclasses import replace
    return replace(candidate_today, candidate_id="tomorrow", source_event_id="event-3", starts_at=candidate_today.starts_at + timedelta(days=1))


@pytest.fixture
def candidate_fixture(candidate_today):
    return candidate_today
```

- [ ] **Step 2: Write failing candidate tests**

```python
from backend.pick_selection import build_candidates, build_same_day_parlay


def test_candidate_copies_exact_source_market_and_price(event_fixture):
    candidates = build_candidates([event_fixture])
    home = next(row for row in candidates if row.selection_key == "home")
    assert home.source_event_id == event_fixture.source_event_id
    assert home.market_key == "h2h"
    assert home.price == event_fixture.markets[0].outcome("home").price


def test_unsupported_period_is_not_a_candidate(partial_market_event):
    assert build_candidates([partial_market_event]) == []


def test_parlay_requires_individually_valid_same_day_legs(candidate_today, candidate_tomorrow):
    assert build_same_day_parlay([candidate_today, candidate_tomorrow]) is None
```

- [ ] **Step 3: Run tests and verify RED**

Run: `python -m pytest tests/test_pick_selection.py -q`

Expected: FAIL because `backend.pick_selection` does not exist.

- [ ] **Step 4: Implement verified candidate construction**

```python
from dataclasses import dataclass
from datetime import datetime

from backend.scraper_domain import Event


SUPPORTED = {("h2h", "full_game"), ("totals", "full_game"), ("spreads", "full_game")}


@dataclass(frozen=True)
class CandidatePick:
    candidate_id: str
    source: str
    source_event_id: str
    starts_at: datetime
    home_team: str
    away_team: str
    market_key: str
    period: str
    line: float | None
    selection_key: str
    selection_name: str
    price: float
    observed_at: datetime


def build_candidates(events: list[Event]) -> list[CandidatePick]:
    result = []
    for event in events:
        for market in event.markets:
            if (market.key, market.period) not in SUPPORTED:
                continue
            for outcome in market.outcomes:
                identifier = ":".join((event.source, event.source_event_id, market.key, str(market.line), outcome.key))
                result.append(CandidatePick(
                    identifier, event.source, event.source_event_id, event.starts_at,
                    event.home_team, event.away_team, market.key, market.period,
                    market.line, outcome.key, outcome.name, outcome.price, event.observed_at,
                ))
    return result


def build_same_day_parlay(candidates: list[CandidatePick]):
    eligible = sorted(candidates, key=lambda row: (row.starts_at, row.candidate_id))
    for index, first in enumerate(eligible):
        for second in eligible[index + 1:]:
            if first.source_event_id != second.source_event_id and first.starts_at.date() == second.starts_at.date():
                return first, second
    return None
```

- [ ] **Step 5: Run tests and commit**

Run: `python -m pytest tests/test_pick_selection.py -q`

Expected: `3 passed`.

```bash
git add backend/pick_selection.py tests/test_pick_selection.py tests/conftest.py
git commit -m "feat: build picks from verified outcomes"
```

### Task 5: Restrict AI to candidate IDs

**Files:**
- Modify: `backend/pick_selection.py`
- Modify: `tests/test_pick_selection.py`
- Modify: `backend/scraper.py`

- [ ] **Step 1: Add failing hostile-response tests**

```python
from backend.pick_selection import validate_ai_ranking


def test_ai_cannot_invent_a_selection_or_change_its_price(candidate_fixture):
    response = [{"candidate_id": "unknown", "price": 9.99, "rationale": "Selección supuestamente segura"}]
    assert validate_ai_ranking(response, [candidate_fixture]) == []


def test_ai_result_copies_factual_fields_from_catalog(candidate_fixture):
    response = [{"candidate_id": candidate_fixture.candidate_id, "price": 9.99, "rationale": "Dos fuentes coinciden."}]
    ranked = validate_ai_ranking(response, [candidate_fixture])
    assert ranked[0].candidate.price == candidate_fixture.price
    assert ranked[0].rationale == "Dos fuentes coinciden."
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_pick_selection.py -q`

Expected: FAIL because `validate_ai_ranking` does not exist.

- [ ] **Step 3: Implement allow-list validation**

```python
@dataclass(frozen=True)
class RankedPick:
    candidate: CandidatePick
    rationale: str


def validate_ai_ranking(response: list[dict], candidates: list[CandidatePick]) -> list[RankedPick]:
    catalog = {candidate.candidate_id: candidate for candidate in candidates}
    ranked, seen = [], set()
    for item in response:
        candidate_id = str(item.get("candidate_id") or "")
        rationale = str(item.get("rationale") or "").strip()
        if candidate_id not in catalog or candidate_id in seen or len(rationale) < 10:
            continue
        seen.add(candidate_id)
        ranked.append(RankedPick(catalog[candidate_id], rationale[:500]))
    return ranked
```

The Groq schema contains only `candidate_id` and `rationale`. Delete the parser that accepts arbitrary `partido`, `pick`, and `cuota` from AI output.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_pick_selection.py -q`

Expected: all pick-selection tests pass.

```bash
git add backend/pick_selection.py tests/test_pick_selection.py backend/scraper.py
git commit -m "feat: constrain AI to verified candidates"
```

### Task 6: Derive bounded confidence and value labels from evidence

**Files:**
- Modify: `backend/pick_selection.py`
- Modify: `tests/test_pick_selection.py`
- Modify: `backend/scraper.py`

- [ ] **Step 1: Write failing scoring tests**

```python
from backend.pick_selection import Evidence, score_evidence


def test_missing_comparison_never_claims_value():
    score = score_evidence(Evidence(1, 5, None, True))
    assert score.has_value is False
    assert score.label == "Datos limitados"


def test_fresh_agreeing_sources_produce_a_bounded_label():
    score = score_evidence(Evidence(2, 3, 0.03, True))
    assert score.has_value is True
    assert score.percent <= 85
    assert score.label == "Respaldo alto"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_pick_selection.py -q`

Expected: FAIL because `Evidence` and `score_evidence` do not exist.

- [ ] **Step 3: Implement evidence scoring**

```python
@dataclass(frozen=True)
class Evidence:
    source_count: int
    age_minutes: int
    price_spread: float | None
    market_complete: bool


@dataclass(frozen=True)
class EvidenceScore:
    percent: int
    label: str
    has_value: bool


def score_evidence(evidence: Evidence) -> EvidenceScore:
    points = 45
    points += 15 if evidence.source_count >= 2 else 0
    points += 10 if evidence.age_minutes <= 10 else 0
    points += 10 if evidence.market_complete else 0
    agrees = evidence.price_spread is not None and evidence.price_spread <= 0.05
    points += 5 if agrees else 0
    bounded = min(points, 85)
    return EvidenceScore(bounded, "Respaldo alto" if bounded >= 75 and agrees else "Datos limitados", agrees and evidence.source_count >= 2)
```

Map `percent` to `confianza` and `has_value` to `tiene_valor`. Remove hardcoded `90%`, `91%`, `93%`, and infallibility language.

- [ ] **Step 4: Run tests, regression search, and commit**

Run: `python -m pytest tests/test_pick_selection.py -q && rg -n 'confianza.*9[0-9]%|alta probabilidad matemática|infalible' backend/scraper.py backend/pick_selection.py`

Expected: tests pass and the search returns no hardcoded claim.

```bash
git add backend/pick_selection.py tests/test_pick_selection.py backend/scraper.py
git commit -m "feat: derive bounded pick evidence scores"
```

### Task 7: Persist source audit fields through the structured pipeline

**Files:**
- Modify: `backend/scraper.py`
- Modify: `backend/pick_publisher.py`
- Create: `supabase/migrations/20260820234500_pick_source_audit.sql`
- Modify: `supabase/migrations/20260820233000_scraper_run_ledger.sql`
- Modify: `tests/test_supabase_contract.py`
- Create: `tests/test_scraper_pipeline.py`

- [ ] **Step 1: Write failing pipeline and SQL tests**

```python
from backend.scraper import run_structured_pipeline


class FakePublisher:
    def __init__(self):
        self.calls = []

    def publish(self, rows, *, dry_run):
        self.calls.append(rows)
        return type("Publication", (), {"created": False, "dry_run": dry_run})()


def _rank_first(candidates):
    return [{"candidate_id": candidates[0].candidate_id, "rationale": "Mercado completo y precio reciente."}] if candidates else []


def test_pipeline_publishes_only_catalog_backed_rows(event_fixture):
    publisher = FakePublisher()
    result = run_structured_pipeline([event_fixture], _rank_first, publisher, dry_run=True)
    assert result.pick_count > 0
    assert all(row["source_event_id"] for row in result.picks)
    assert all(row["source_market_key"] for row in result.picks)
    assert all(row["source_observed_at"] for row in result.picks)


def test_pipeline_refuses_empty_verified_catalog():
    publisher = FakePublisher()
    result = run_structured_pipeline([], _rank_first, publisher, dry_run=True)
    assert result.pick_count == 0
    assert publisher.calls == []
```

Add to `test_supabase_contract.py`:

```python
def test_picks_store_source_market_audit_fields(self):
    text = (SQL.parent / "20260820234500_pick_source_audit.sql").read_text(encoding="utf-8").lower()
    for field in ("source", "source_event_id", "source_market_key", "source_selection_key", "source_observed_at"):
        self.assertIn(field, text)
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_scraper_pipeline.py tests/test_supabase_contract.py -q`

Expected: FAIL because the structured orchestrator and audit migration do not exist.

- [ ] **Step 3: Add source audit columns**

```sql
begin;

alter table public.picks
    add column if not exists source text,
    add column if not exists source_event_id text,
    add column if not exists source_market_key text,
    add column if not exists source_selection_key text,
    add column if not exists source_observed_at timestamptz;

create index if not exists picks_source_event_idx on public.picks (source, source_event_id);

commit;
```

Update `publish_pick_batch` to insert all five source fields from each requested pick.

- [ ] **Step 4: Integrate the structured ownership sequence**

```python
events = collect_normalized_events(playdoit_source, odds_source)
candidates = build_candidates(events)
ai_response = rank_verified_candidates(candidates, groq_client)
validated = validate_ai_ranking(ai_response, candidates)
rows = [persistable_pick(item, evidence_for(item.candidate, events)) for item in validated]
if not rows:
    return PipelineResult(event_count=len(events), pick_count=0, picks=[], persisted=False)
publication = publisher.publish(rows, dry_run=dry_run)
return PipelineResult(len(events), len(rows), rows, publication.created or publication.dry_run)
```

Apply `assign_visibility` only after rows are source-backed. If AI fails, use a deterministic ordering only when candidates meet the same evidence threshold; otherwise publish nothing.

- [ ] **Step 5: Run focused tests and commit**

Run: `python -m pytest tests/test_scraper_pipeline.py tests/test_pick_selection.py tests/test_publishing_policy.py tests/test_supabase_contract.py -q`

Expected: all focused tests pass.

```bash
git add backend/scraper.py backend/pick_publisher.py supabase/migrations/20260820233000_scraper_run_ledger.sql supabase/migrations/20260820234500_pick_source_audit.sql tests/test_scraper_pipeline.py tests/test_supabase_contract.py
git commit -m "feat: publish source-backed pick candidates"
```

### Task 8: Complete market-integrity verification and dry run

**Files:**
- Modify: `docs/operations/security-and-payments.md`

- [ ] **Step 1: Document supported and rejected markets**

Document full-game moneyline, totals, and spreads/run lines as production-supported. Document same-day parlay leg grouping as validator-only: production must reject it until the combined quote and complete source audit are independently observed. Document partial periods, unsupported player props, incomplete corners, and ambiguous team totals as rejected until a specific validator and grader exist.

- [ ] **Step 2: Run all automated checks**

Run:

```powershell
python -m pyflakes backend/scraper.py backend/scraper_domain.py backend/playdoit_source.py backend/odds_source.py backend/pick_selection.py backend/pick_publisher.py backend/telegram_publisher.py
python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
deno test --allow-env supabase/functions/*/index.test.ts
git diff --check
```

Expected: every command exits `0` with no failed tests, undefined names, duplicate definitions, or whitespace errors.

- [ ] **Step 3: Run the no-write integration smoke test**

Run: `python backend/scraper.py --dry-run`

Expected output includes:

```text
dry_run=true
events_normalized=<positive number>
candidates_verified=<positive number>
picks_selected=<positive number>
supabase_writes=0
telegram_deliveries=0
```

If current source data contains no eligible future market, the command exits with `ExitCode.NO_CANDIDATES` and does not invent a fallback pick.

- [ ] **Step 4: Inspect a sanitized dry-run artifact**

Verify each selected row contains `source`, `source_event_id`, `source_market_key`, `source_selection_key`, `source_observed_at`, and a price equal to its referenced candidate. Confirm the artifact is outside `frontend/public` and ignored by Git.

- [ ] **Step 5: Commit operations documentation**

```bash
git add docs/operations/security-and-payments.md
git commit -m "docs: describe verified scraper markets"
```

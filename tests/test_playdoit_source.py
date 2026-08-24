from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend.playdoit_source import (
    extract_playdoit_raw_events,
    extract_react_detail_markets,
    extract_supported_markets,
    normalize_playdoit_event,
    normalize_playdoit_events,
    resolve_mexico_start,
)


FIXTURE = Path(__file__).parent / "fixtures" / "playdoit_event.json"
SCRAPER = Path(__file__).resolve().parents[1] / "backend" / "scraper.py"
MEXICO = ZoneInfo("America/Mexico_City")


def fixture_event() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_year_rollover_uses_next_year_not_a_hardcoded_date():
    observed = datetime(2026, 12, 31, 10, tzinfo=MEXICO)

    assert resolve_mexico_start("01/01", "12:00", observed).year == 2027


def test_leap_day_rollover_finds_the_next_valid_leap_year():
    observed = datetime(2026, 12, 31, 10, tzinfo=MEXICO)

    assert resolve_mexico_start("29/02", "12:00", observed) == datetime(
        2028, 2, 29, 12, tzinfo=MEXICO
    )


def test_fixture_preserves_exact_named_market_and_price_independent_of_order():
    raw = fixture_event()

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert event.source == "playdoit"
    assert event.source_event_id == "playdoit-456"
    assert event.observed_at.tzinfo == MEXICO
    assert event.markets[0].bookmaker_key == "playdoit"
    assert event.markets[0].outcome("home").price == 1.72


def test_observed_at_is_converted_to_mexico_city_before_resolving_relative_date():
    observed_utc = datetime(2026, 8, 21, 4, 30, tzinfo=timezone.utc)

    starts_at = resolve_mexico_start("Hoy", "23:00", observed_utc)

    assert starts_at == datetime(2026, 8, 20, 23, 0, tzinfo=MEXICO)


def test_manana_is_resolved_relative_to_the_mexico_calendar():
    observed = datetime(2026, 8, 20, 23, 30, tzinfo=MEXICO)

    assert resolve_mexico_start("Mañana", "00:15", observed) == datetime(
        2026, 8, 21, 0, 15, tzinfo=MEXICO
    )


@pytest.mark.parametrize(
    ("date_label", "time_label"),
    [
        ("", "20:00"),
        ("21/08/2026", "20:00"),
        ("21.08", "20:00"),
        ("31/02", "20:00"),
        ("21/08", "8:00"),
        ("21/08", "24:00"),
        ("Hoy", "20:00 hrs"),
    ],
)
def test_start_requires_a_strict_supported_date_and_time(date_label, time_label):
    observed = datetime(2026, 8, 20, 10, tzinfo=MEXICO)

    with pytest.raises(ValueError):
        resolve_mexico_start(date_label, time_label, observed)


def test_start_rejects_naive_observation_and_past_events():
    with pytest.raises(ValueError, match="timezone-aware"):
        resolve_mexico_start(
            "21/08", "20:00", datetime(2026, 8, 20, 10)
        )

    with pytest.raises(ValueError, match="future"):
        resolve_mexico_start(
            "20/08", "09:59", datetime(2026, 8, 20, 10, tzinfo=MEXICO)
        )


def test_date_accepts_dash_only_as_the_documented_alternative_separator():
    observed = datetime(2026, 8, 20, 10, tzinfo=MEXICO)

    assert resolve_mexico_start("21-08", "20:00", observed) == datetime(
        2026, 8, 21, 20, tzinfo=MEXICO
    )


@pytest.mark.parametrize("event_id", [None, "", "   "])
def test_event_requires_a_real_stable_source_identifier(event_id):
    raw = fixture_event()
    raw["event_id"] = event_id

    with pytest.raises((TypeError, ValueError), match="event_id"):
        normalize_playdoit_event(
            raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
        )


@pytest.mark.parametrize(
    "price", [None, True, "+110", "-110", "1e1", "1.00", "50.01", math.nan]
)
def test_non_decimal_or_out_of_range_price_omits_the_whole_market(price):
    raw = fixture_event()
    raw["markets"][0]["outcomes"][0]["price"] = price

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert event.markets == ()


def test_soccer_h2h_requires_exact_home_draw_away_and_rejects_unknown_names():
    raw = fixture_event()
    raw["markets"][0]["outcomes"] = [
        {"key": "home", "name": "América", "price": "1.72"},
        {"key": "away", "name": "Otro equipo", "price": "2.35"},
    ]

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert event.markets == ()


def test_two_way_h2h_requires_exact_home_and_away_without_draw():
    raw = fixture_event()
    raw["sport"] = "baseball"
    raw["league"] = "MLB"
    raw["markets"][0]["outcomes"] = [
        {"key": "away", "name": "Tigres", "price": "2.35"},
        {"key": "home", "name": "América", "price": "1.72"},
    ]

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )
    assert tuple(outcome.key for outcome in event.markets[0].outcomes) == (
        "home",
        "away",
    )

    raw["markets"][0]["outcomes"].append(
        {"key": "draw", "name": "Empate", "price": "3.25"}
    )
    assert normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    ).markets == ()


def test_totals_and_spreads_require_named_complete_opposing_selections():
    raw = fixture_event()
    raw["markets"] = [
        {
            "key": "totals",
            "title": "Total de goles",
            "period": "full_game",
            "scope": "event",
            "line": "2.5",
            "outcomes": [
                {"key": "under", "name": "Menos de 2.5", "line": "2.5", "price": "1.91"},
                {"key": "over", "name": "Más de 2.5", "line": "2.5", "price": "1.89"},
            ],
        },
        {
            "key": "spreads",
            "title": "Hándicap del partido",
            "period": "full_game",
            "scope": "event",
            "line": "-1.5",
            "outcomes": [
                {"key": "away", "name": "Tigres +1.5", "line": "1.5", "price": "1.95"},
                {"key": "home", "name": "América -1.5", "line": "-1.5", "price": "1.85"},
            ],
        },
    ]

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert [(market.key, market.line) for market in event.markets] == [
        ("totals", 2.5),
        ("spreads", -1.5),
    ]
    assert tuple(outcome.key for outcome in event.markets[0].outcomes) == (
        "over",
        "under",
    )
    assert tuple(outcome.key for outcome in event.markets[1].outcomes) == (
        "home",
        "away",
    )

    raw["markets"][1]["outcomes"][0]["line"] = "2.0"
    malformed = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )
    assert [market.key for market in malformed.markets] == ["totals"]


def test_totals_reject_keys_that_contradict_the_named_selection():
    raw = fixture_event()
    raw["markets"] = [{
        "key": "totals",
        "title": "Total de goles",
        "period": "full_game",
        "scope": "event",
        "line": "2.5",
        "outcomes": [
            {"key": "over", "name": "Menos de 2.5", "line": "2.5", "price": "1.89"},
            {"key": "under", "name": "Más de 2.5", "line": "2.5", "price": "1.91"},
        ],
    }]

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert event.markets == ()


def test_only_supported_full_game_markets_are_kept():
    raw = fixture_event()
    first_period = deepcopy(raw["markets"][0])
    first_period["period"] = "first_half"
    raw["markets"].extend(
        [
            first_period,
            {
                "key": "corners",
                "title": "Tiros de esquina",
                "period": "full_game",
                "scope": "event",
                "outcomes": [
                    {"key": "over", "name": "Más", "price": "1.80"}
                ],
            },
        ]
    )

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert [market.key for market in event.markets] == ["h2h"]


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
            "competitor_id": "cole-palmer",
            "name": "Más de 0.5",
            "price": 1.75,
        }],
    })

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )
    market = event.markets[-1]

    assert market.key == "playdoit_market:player-shots-1"
    assert market.period == "source_unspecified"
    assert market.name == "Remates a Puerta - Cole Palmer"
    assert market.source_id == "player-shots-1"
    assert market.sport_market_id == "shots"
    assert market.outcomes[0].source_id == "shots-over-05"
    assert market.outcomes[0].competitor_id == "cole-palmer"


@pytest.mark.parametrize(
    ("missing_market_id", "missing_odd_id"),
    [(True, False), (False, True)],
)
def test_source_backed_market_fails_closed_without_official_ids(
    missing_market_id: bool, missing_odd_id: bool
):
    raw = fixture_event()
    source_market = {
        "key": "source_market",
        "title": "Tiros de esquina",
        "period": "source_unspecified",
        "scope": "source_unspecified",
        "source_market_id": "corners-1",
        "outcomes": [{
            "key": "playdoit_odd:corners-over",
            "source_selection_id": "corners-over",
            "name": "Más de 8.5",
            "price": 1.85,
        }],
    }
    if missing_market_id:
        source_market.pop("source_market_id")
    if missing_odd_id:
        source_market["outcomes"][0].pop("source_selection_id")
    raw["markets"] = [source_market]

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert event.markets == ()


def test_conflicting_scope_for_same_official_market_fails_closed():
    raw = fixture_event()
    source_market = {
        "key": "source_market",
        "title": "Total",
        "period": "source_unspecified",
        "scope": "event",
        "source_market_id": "total-1",
        "offer_kind": "standard",
        "source_selection_ids": ["over-1"],
        "outcomes": [{
            "key": "playdoit_odd:over-1",
            "source_selection_id": "over-1",
            "name": "Más de 2.5",
            "price": 1.85,
        }],
    }
    conflicting = deepcopy(source_market)
    conflicting["scope"] = "team_total"
    raw["markets"] = [source_market, conflicting]

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert event.markets == ()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", None),
        ("period", None),
        ("scope", None),
        ("title", "Total de goles"),
        ("title", "Total de goles de América"),
        ("period", "first_half"),
        ("scope", "team_total"),
    ],
)
def test_raw_market_requires_explicit_matching_full_game_event_scope(field, value):
    raw = fixture_event()
    if value is None:
        raw["markets"][0].pop(field)
    else:
        raw["markets"][0][field] = value

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert event.markets == ()


def test_duplicate_market_quote_is_deduped_but_conflicting_quote_fails_closed():
    raw = fixture_event()
    duplicate = deepcopy(raw["markets"][0])
    duplicate["outcomes"].reverse()
    raw["markets"].append(duplicate)

    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )
    assert len(event.markets) == 1

    raw["markets"][1]["outcomes"][0]["price"] = "9.99"
    conflicted = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )
    assert conflicted.markets == ()


def test_event_batch_dedupes_source_id_and_omits_conflicting_revisions():
    raw = fixture_event()
    same = deepcopy(raw)

    observed = datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    events = normalize_playdoit_events([raw, same], observed)
    assert [event.source_event_id for event in events] == ["playdoit-456"]

    conflict = deepcopy(raw)
    conflict["markets"][0]["outcomes"][0]["price"] = "9.99"
    assert normalize_playdoit_events([raw, conflict], observed) == ()


def test_event_batch_skips_invalid_records_without_losing_valid_siblings():
    invalid = fixture_event()
    invalid["event_id"] = ""
    valid = fixture_event()

    events = normalize_playdoit_events(
        [invalid, valid], datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert [event.source_event_id for event in events] == ["playdoit-456"]


def test_missing_start_time_has_an_explicit_rejection_reason_in_event_and_batch():
    raw = fixture_event()
    raw["time_label"] = ""
    observed = datetime(2026, 8, 20, 10, tzinfo=MEXICO)

    with pytest.raises(ValueError) as exc_info:
        normalize_playdoit_event(raw, observed)
    assert getattr(exc_info.value, "reason", None) == "missing_start_time"

    rejections = []
    assert normalize_playdoit_events(
        [raw], observed, rejections=rejections
    ) == ()
    assert rejections == ["missing_start_time"]


class ImmediateWait:
    def __init__(self, driver, timeout):
        self.driver = driver
        self.timeout = timeout

    def until(self, predicate):
        for _ in range(5):
            value = predicate(self.driver)
            if value:
                return value
        from selenium.common.exceptions import TimeoutException

        raise TimeoutException("unchanged")


class ProgressiveWait(ImmediateWait):
    def until(self, predicate):
        for _ in range(8):
            value = predicate(self.driver)
            if value:
                return value
        from selenium.common.exceptions import TimeoutException

        raise TimeoutException("progressive market did not stabilize")


class MarketDriver:
    def __init__(self, *, stuck_key=None, active=None, late_details=False):
        self.active = active
        self.stuck_key = stuck_key
        self.late_details = late_details
        self.discovery_calls = 0
        self.calls = []

    def execute_script(self, script, *args):
        self.calls.append((script, args))
        if "playdoit:extract-react-detail-markets" in script:
            return {
                "verified": True,
                "source_event_id": args[0],
                "groups": [],
            }
        if "playdoit:advance-react-detail-markets" in script:
            return {"scrollTop": 0, "scrollHeight": 100, "clientHeight": 100}
        if "playdoit:discover-market-tabs" in script:
            self.discovery_calls += 1
            if self.late_details and self.discovery_calls == 1:
                return []
            return [
                {"key": "h2h", "token": "tab-h2h"},
                {"key": "totals", "token": "tab-totals"},
                {"key": "spreads", "token": "tab-spreads"},
            ]
        if "playdoit:is-market-tab-active" in script:
            return self.active == args[0].removeprefix("tab-")
        if "playdoit:market-signature" in script:
            if self.active == self.stuck_key:
                return "overview"
            return "overview" if self.active is None else f"market:{self.active}"
        if "playdoit:click-market-tab" in script:
            self.active = args[0].removeprefix("tab-")
            return True
        if "playdoit:extract-visible-market" in script:
            key, home, away = args[:3]
            if key == "h2h":
                return [{
                    "key": "h2h",
                    "title": "resultado final",
                    "period": "full_game",
                    "scope": "event",
                    "outcomes": [
                        {"key": "home", "name": home, "price": "1.72"},
                        {"key": "draw", "name": "Empate", "price": "3.25"},
                        {"key": "away", "name": away, "price": "2.35"},
                    ],
                }]
            return []
        raise AssertionError("unexpected script")


def test_default_active_h2h_is_extracted_without_requiring_content_change():
    driver = MarketDriver(active="h2h", stuck_key="h2h")

    markets = extract_supported_markets(
        driver,
        "América",
        "Tigres",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert [market["key"] for market in markets] == ["h2h"]
    assert driver.discovery_calls >= 3
    clicked_tokens = [
        args[0]
        for script, args in driver.calls
        if "playdoit:click-market-tab" in script
    ]
    assert clicked_tokens == ["tab-totals", "tab-spreads"]


def test_event_detail_wait_handles_tabs_appearing_after_initial_discovery():
    driver = MarketDriver(late_details=True)

    markets = extract_supported_markets(
        driver,
        "América",
        "Tigres",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert [market["key"] for market in markets] == ["h2h"]
    assert driver.discovery_calls >= 4


class BrokenMarketDriver(MarketDriver):
    def execute_script(self, script, *args):
        if "playdoit:discover-market-tabs" in script and self.discovery_calls == 1:
            self.discovery_calls += 1
            raise RuntimeError("stale DOM")
        return super().execute_script(script, *args)


def test_one_market_dom_exception_is_isolated_from_sibling_markets():
    driver = BrokenMarketDriver()

    markets = extract_supported_markets(
        driver,
        "América",
        "Tigres",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert markets == []
    assert driver.discovery_calls >= 3


class ActiveBeforeBoxesDriver(MarketDriver):
    def __init__(self):
        super().__init__(active="totals")
        self.rendered = "totals"
        self.pending_polls = 0

    def execute_script(self, script, *args):
        if "playdoit:discover-market-tabs" in script:
            self.discovery_calls += 1
            return [{"key": "h2h", "token": "tab-h2h"}]
        if "playdoit:click-market-tab" in script:
            self.active = "h2h"
            self.pending_polls = 1
            return True
        if "playdoit:market-signature" in script:
            if self.pending_polls == 1:
                self.pending_polls = 2
                return "market:totals"
            if self.pending_polls == 2:
                self.rendered = "h2h"
                self.pending_polls = 0
            return f"market:{self.rendered}"
        if "playdoit:extract-visible-market" in script and self.rendered != args[0]:
            return []
        return super().execute_script(script, *args)


def test_inactive_tab_waits_for_boxes_to_change_after_active_state_changes():
    driver = ActiveBeforeBoxesDriver()

    markets = extract_supported_markets(
        driver,
        "América",
        "Tigres",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert [market["key"] for market in markets] == ["h2h"]
    assert driver.rendered == "h2h"


def test_market_extraction_passes_source_text_as_script_arguments():
    driver = MarketDriver()

    markets = extract_supported_markets(
        driver,
        "América",
        "Tigres",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert markets[0]["outcomes"][0]["name"] == "América"
    source_calls = [
        (script, args)
        for script, args in driver.calls
        if "playdoit:extract-visible-market" in script
    ]
    assert source_calls
    assert all("América" not in script and "Tigres" not in script for script, _ in source_calls)
    assert source_calls[0][1][:3] == ("h2h", "América", "Tigres")


class ReactDetailMarketDriver:
    def __init__(self):
        self.script = ""

    def execute_script(self, script, *args):
        self.script = script
        if "playdoit:advance-react-detail-markets" in script:
            return {
                "scrollTop": 0,
                "scrollHeight": 100,
                "clientHeight": 100,
            }
        if "playdoit:extract-react-detail-markets" not in script:
            raise AssertionError("unexpected script")
        groups = [
            {
                "market": {
                    "id": 1614791472,
                    "name": "Total",
                    "oddIds": [],
                    "sportMarketId": 70520,
                    "sv": "2.5",
                    "typeId": 18,
                    "period": "full_game",
                    "scope": "event",
                },
                "odds": [
                    {
                        "id": 4132889965,
                        "name": "Más de 2.5",
                        "oddStatus": 0,
                        "price": 1.6667,
                        "sv": "2.5",
                        "typeId": 12,
                    },
                    {
                        "id": 4132889966,
                        "name": "Menos de 2.5",
                        "oddStatus": 0,
                        "price": 2.2223,
                        "sv": "2.5",
                        "typeId": 13,
                    },
                ],
            },
            {
                "market": {
                    "id": 999,
                    "name": "Fulham total de goles",
                    "sv": "1.5",
                    "typeId": 18,
                },
                "odds": [],
            },
        ]
        return {
            "verified": True,
            "source_event_id": args[0],
            "groups": groups,
        }


class RoutedReactDetailMarketDriver(ReactDetailMarketDriver):
    def __init__(self, *, verified=True, routed_event_id="16848649"):
        super().__init__()
        self.verified = verified
        self.routed_event_id = routed_event_id
        self.args = None

    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        raw = super().execute_script(script, *args)
        self.args = args
        raw["verified"] = self.verified
        raw["source_event_id"] = self.routed_event_id
        return raw


def test_react_detail_passes_exact_event_identity_as_script_arguments():
    driver = RoutedReactDetailMarketDriver()

    markets = extract_react_detail_markets(
        driver,
        "16848649",
        "Fulham",
        "Chelsea",
    )

    assert driver.args == ("16848649", "Fulham", "Chelsea")
    assert "16848649" not in driver.script
    assert "EventDetailsMarketsContainer" in driver.script
    assert "detailRoot.querySelectorAll" in driver.script
    assert "host.shadowRoot.querySelectorAll('button" not in driver.script
    assert "offerKind" in driver.script
    assert "route.get('eventId')" in driver.script
    assert "market.oddIds.some" in driver.script
    assert [market["key"] for market in markets] == ["totals"]


def test_react_detail_rejects_unverified_route_snapshot():
    driver = RoutedReactDetailMarketDriver(
        verified=False,
        routed_event_id="999",
    )

    markets = extract_react_detail_markets(
        driver,
        "16848649",
        "Fulham",
        "Chelsea",
    )

    assert markets == []


def test_react_detail_extracts_exact_full_game_total_and_ignores_team_total():
    driver = ReactDetailMarketDriver()

    markets = extract_react_detail_markets(
        driver, "16848649", "Fulham", "Chelsea"
    )

    assert "__reactFiber$" in driver.script
    assert markets == [{
        "key": "totals",
        "title": "Total",
        "period": "full_game",
        "scope": "event",
        "line": "2.5",
        "outcomes": [
            {
                "key": "over",
                "name": "Más de 2.5",
                "price": 1.6667,
                "line": "2.5",
            },
            {
                "key": "under",
                "name": "Menos de 2.5",
                "price": 2.2223,
                "line": "2.5",
            },
        ],
    }]

    raw = fixture_event()
    raw["markets"].extend(markets)
    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )
    assert [market.key for market in event.markets] == ["h2h", "totals"]
    assert event.markets[1].line == 2.5


class ExplicitFirstHalfTotalDriver(ReactDetailMarketDriver):
    def execute_script(self, script, *args):
        raw = super().execute_script(script, *args)
        total = raw["groups"][0]["market"]
        total["period"] = "first_half"
        total["scope"] = "event"
        return raw


def test_explicit_first_half_total_is_generic_not_canonical_full_game():
    driver = ExplicitFirstHalfTotalDriver()

    markets = extract_react_detail_markets(
        driver, "16848649", "Fulham", "Chelsea"
    )

    assert len(markets) == 1
    assert markets[0]["key"] == "source_market"
    assert markets[0]["period"] == "first_half"
    assert markets[0]["scope"] == "event"
    assert markets[0]["source_market_id"] == "1614791472"


class DelayedReactDetailMarketDriver(ReactDetailMarketDriver):
    def __init__(self):
        super().__init__()
        self.detail_polls = 0

    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" in script:
            self.detail_polls += 1
            if self.detail_polls < 3:
                self.script = script
                return {
                    "verified": True,
                    "source_event_id": args[0],
                    "groups": [],
                }
        return super().execute_script(script, *args)


def test_supported_market_extraction_waits_for_react_detail_to_render():
    driver = DelayedReactDetailMarketDriver()

    markets = extract_supported_markets(
        driver,
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert driver.detail_polls >= 3
    assert [market["key"] for market in markets] == ["totals"]


class WrongEventReactWithLegacyTabsDriver(MarketDriver):
    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" in script:
            return {
                "verified": False,
                "source_event_id": "other-event",
                "groups": [],
            }
        if "playdoit:advance-react-detail-markets" in script:
            return {"scrollTop": 0, "scrollHeight": 100, "clientHeight": 100}
        return super().execute_script(script, *args)


def test_wrong_event_react_provenance_never_falls_back_to_legacy_tabs():
    markets = extract_supported_markets(
        WrongEventReactWithLegacyTabsDriver(active="h2h"),
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert markets == []


class PartialThenCompleteTotalDriver(RoutedReactDetailMarketDriver):
    def __init__(self):
        super().__init__()
        self.polls = 0

    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        self.script = script
        self.args = args
        self.polls += 1
        odds = [{
            "id": "over-1",
            "name": "Más de 2.5",
            "oddStatus": 0,
            "price": 1.8,
            "sv": "2.5",
            "typeId": 12,
        }]
        if self.polls >= 3:
            odds.append({
                "id": "under-1",
                "name": "Menos de 2.5",
                "oddStatus": 0,
                "price": 2.0,
                "sv": "2.5",
                "typeId": 13,
            })
        return {
            "verified": True,
            "source_event_id": args[0],
            "groups": [{
                "market": {
                    "id": "total-1",
                    "name": "Total",
                    "sv": "2.5",
                    "typeId": 18,
                    "period": "full_game",
                    "scope": "event",
                },
                "odds": odds,
            }],
        }


def test_progressive_total_waits_for_both_official_sides():
    driver = PartialThenCompleteTotalDriver()

    markets = extract_supported_markets(
        driver,
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ProgressiveWait,
        timeout=0.01,
    )

    assert driver.polls >= 3
    assert [row["key"] for row in markets] == ["totals"]
    assert [row["key"] for row in markets[0]["outcomes"]] == [
        "over",
        "under",
    ]


class ProgressiveMarketUnionDriver(RoutedReactDetailMarketDriver):
    def __init__(self):
        super().__init__()
        self.polls = 0

    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        self.script = script
        self.args = args
        self.polls += 1
        h2h = {
            "market": {
                "id": "h2h-1",
                "name": "Resultado Final",
                "period": "full_game",
                "scope": "event",
            },
            "odds": [
                {"id": "home-1", "name": "Fulham", "price": 4.0},
                {"id": "draw-1", "name": "Empate", "price": 4.0},
                {"id": "away-1", "name": "Chelsea", "price": 1.8},
            ],
        }
        total = {
            "market": {
                "id": "total-1",
                "name": "Total",
                "sv": "2.5",
                "period": "full_game",
                "scope": "event",
            },
            "odds": [
                {
                    "id": "over-1",
                    "name": "Más de 2.5",
                    "price": 1.8,
                    "sv": "2.5",
                },
                {
                    "id": "under-1",
                    "name": "Menos de 2.5",
                    "price": 2.0,
                    "sv": "2.5",
                },
            ],
        }
        return {
            "verified": True,
            "source_event_id": args[0],
            "groups": [h2h] if self.polls == 1 else [total],
        }


def test_progressive_market_union_keeps_groups_and_deduplicates_odd_ids():
    driver = ProgressiveMarketUnionDriver()

    markets = extract_supported_markets(
        driver,
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ProgressiveWait,
        timeout=0.01,
    )

    assert driver.polls >= 3
    assert [row["key"] for row in markets] == ["h2h", "totals"]
    assert len(markets[0]["outcomes"]) == 3
    assert len(markets[1]["outcomes"]) == 2


class StableUnknownMarketDriver(RoutedReactDetailMarketDriver):
    def __init__(self):
        super().__init__()
        self.polls = 0

    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        self.script = script
        self.args = args
        self.polls += 1
        return {
            "verified": True,
            "source_event_id": args[0],
            "groups": [{
                "market": {
                    "id": "corners-1",
                    "name": "Total de tiros de esquina",
                    "sportMarketId": "corners",
                },
                "odds": [
                    {
                        "id": "corners-over",
                        "name": "Más de 8.5",
                        "price": 1.85,
                    },
                    {
                        "id": "corners-under",
                        "name": "Menos de 8.5",
                        "price": 1.95,
                    },
                ],
            }],
        }


def test_stable_unknown_market_finishes_without_waiting_for_timeout():
    driver = StableUnknownMarketDriver()

    markets = extract_supported_markets(
        driver,
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ProgressiveWait,
        timeout=0.01,
    )

    assert driver.polls == 2
    assert [row["key"] for row in markets] == ["source_market"]


class ScrollingUnknownMarketDriver(StableUnknownMarketDriver):
    def __init__(self):
        super().__init__()
        self.scroll_polls = 0

    def execute_script(self, script, *args):
        if "playdoit:advance-react-detail-markets" in script:
            self.scroll_polls += 1
            return {
                "scrollTop": min(self.scroll_polls * 100, 300),
                "scrollHeight": 400,
                "clientHeight": 100,
            }
        return super().execute_script(script, *args)


def test_progressive_catalog_reaches_bottom_before_stable_completion():
    driver = ScrollingUnknownMarketDriver()

    markets = extract_supported_markets(
        driver,
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ProgressiveWait,
        timeout=0.01,
    )

    assert driver.polls == 3
    assert driver.scroll_polls == 3
    assert [row["key"] for row in markets] == ["source_market"]


class BoostedUnknownMarketDriver(RoutedReactDetailMarketDriver):
    def __init__(self, description: str):
        super().__init__()
        self.description = description

    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        self.script = script
        self.args = args
        return {
            "verified": True,
            "source_event_id": args[0],
            "groups": [{
                "market": {
                    "id": "boost-1",
                    "name": "Cole Palmer anota",
                    "offerKind": "boosted",
                    "offerDescription": self.description,
                },
                "odds": [{
                    "id": "boost-yes",
                    "name": "Sí",
                    "price": 3.5,
                }],
            }],
        }


def test_boosted_market_requires_complete_official_description():
    incomplete = extract_react_detail_markets(
        BoostedUnknownMarketDriver(""),
        "16848649",
        "Fulham",
        "Chelsea",
    )
    complete = extract_react_detail_markets(
        BoostedUnknownMarketDriver("Cuota aumentada: Cole Palmer anota"),
        "16848649",
        "Fulham",
        "Chelsea",
    )

    assert incomplete == []
    assert len(complete) == 1
    assert complete[0]["offer_kind"] == "boosted"
    assert complete[0]["source_market_id"] == "boost-1"


class HighPriceUnknownMarketDriver(BoostedUnknownMarketDriver):
    def __init__(self):
        super().__init__("standard")

    def execute_script(self, script, *args):
        raw = super().execute_script(script, *args)
        if "playdoit:extract-react-detail-markets" in script:
            raw["groups"][0]["market"]["offerKind"] = "standard"
            raw["groups"][0]["market"]["offerDescription"] = ""
            raw["groups"][0]["odds"][0]["price"] = 80.0
        return raw


def test_unknown_official_market_preserves_source_backed_longshot_price():
    markets = extract_react_detail_markets(
        HighPriceUnknownMarketDriver(),
        "16848649",
        "Fulham",
        "Chelsea",
    )

    assert markets[0]["outcomes"][0]["price"] == 80.0


class IncompleteDeclaredOddsDriver(BoostedUnknownMarketDriver):
    def __init__(self):
        super().__init__("standard")

    def execute_script(self, script, *args):
        raw = super().execute_script(script, *args)
        if "playdoit:extract-react-detail-markets" in script:
            market = raw["groups"][0]["market"]
            market["offerKind"] = "standard"
            market["offerDescription"] = ""
            market["oddIds"] = ["boost-yes", "boost-no"]
        return raw


def test_generic_market_waits_for_every_declared_official_odd_id():
    markets = extract_react_detail_markets(
        IncompleteDeclaredOddsDriver(),
        "16848649",
        "Fulham",
        "Chelsea",
    )

    assert markets == []


class FailedScrollUnknownMarketDriver(StableUnknownMarketDriver):
    def execute_script(self, script, *args):
        if "playdoit:advance-react-detail-markets" in script:
            return None
        return super().execute_script(script, *args)


def test_unknown_market_fails_closed_when_detail_scroll_cannot_be_verified():
    driver = FailedScrollUnknownMarketDriver()

    markets = extract_supported_markets(
        driver,
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ProgressiveWait,
        timeout=0.01,
    )

    assert markets == []


class StandardAndBoostedSameIdDriver(RoutedReactDetailMarketDriver):
    def __init__(self):
        super().__init__()
        self.polls = 0

    def execute_script(self, script, *args):
        if "playdoit:advance-react-detail-markets" in script:
            return {"scrollTop": 0, "scrollHeight": 100, "clientHeight": 100}
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        self.polls += 1
        return {
            "verified": True,
            "source_event_id": args[0],
            "groups": [
                {
                    "market": {
                        "id": "scorer-1",
                        "name": "Primer goleador",
                        "oddIds": ["standard-1"],
                        "offerKind": "standard",
                        "offerDescription": "",
                    },
                    "odds": [{
                        "id": "standard-1",
                        "name": "Cole Palmer",
                        "price": 5.0,
                    }],
                },
                {
                    "market": {
                        "id": "scorer-1",
                        "name": "Primer goleador",
                        "oddIds": ["boosted-1"],
                        "offerKind": "boosted",
                        "offerDescription": "Boost Cole Palmer",
                    },
                    "odds": [{
                        "id": "boosted-1",
                        "name": "Cole Palmer",
                        "price": 6.0,
                    }],
                },
            ],
        }


def test_standard_and_boosted_offers_with_same_market_id_stay_separate():
    markets = extract_supported_markets(
        StandardAndBoostedSameIdDriver(),
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ProgressiveWait,
        timeout=0.01,
    )

    assert len(markets) == 2
    assert [row["offer_kind"] for row in markets] == [
        "standard",
        "boosted",
    ]
    assert [len(row["outcomes"]) for row in markets] == [1, 1]


class ContradictoryProgressiveMetadataDriver(
    StandardAndBoostedSameIdDriver
):
    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        self.polls += 1
        market_name = "Total" if self.polls == 1 else "Total alterno"
        return {
            "verified": True,
            "source_event_id": args[0],
            "groups": [{
                "market": {
                    "id": "total-1",
                    "name": market_name,
                    "oddIds": ["over-1"],
                    "scope": "event",
                    "offerKind": "standard",
                    "offerDescription": "",
                },
                "odds": [{
                    "id": "over-1",
                    "name": "Más de 2.5",
                    "price": 1.85,
                }],
            }],
        }


def test_progressive_metadata_contradiction_fails_closed():
    markets = extract_supported_markets(
        ContradictoryProgressiveMetadataDriver(),
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ProgressiveWait,
        timeout=0.01,
    )

    assert markets == []


class EarlyH2HReactDetailDriver(ReactDetailMarketDriver):
    def __init__(self):
        super().__init__()
        self.detail_polls = 0

    def execute_script(self, script, *args):
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        self.script = script
        self.detail_polls += 1
        h2h = {
            "market": {
                "id": 1,
                "name": "Resultado Final (Tiempo Regular)",
                "period": "full_game",
                "scope": "event",
            },
            "odds": [
                {"id": 1, "name": "Fulham", "oddStatus": 0, "price": 4.0},
                {"id": 2, "name": "Empate", "oddStatus": 0, "price": 4.0},
                {"id": 3, "name": "Chelsea", "oddStatus": 0, "price": 1.8182},
            ],
        }
        if self.detail_polls < 3:
            return {
                "verified": True,
                "source_event_id": args[0],
                "groups": [h2h],
            }
        raw = super().execute_script(script, *args)
        raw["groups"] = [h2h, *raw["groups"]]
        return raw


def test_react_detail_does_not_stop_when_only_early_h2h_has_rendered():
    driver = EarlyH2HReactDetailDriver()

    markets = extract_supported_markets(
        driver,
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert driver.detail_polls >= 3
    assert [market["key"] for market in markets] == ["h2h", "totals"]


class ExpandableSpreadDriver(ReactDetailMarketDriver):
    def __init__(self):
        super().__init__()
        self.expanded = False

    def execute_script(self, script, *args):
        if "playdoit:expand-react-spread-market" in script:
            self.expanded = True
            return True
        if "playdoit:extract-react-detail-markets" not in script:
            return super().execute_script(script, *args)
        raw = super().execute_script(script, *args)
        groups = raw["groups"]
        if self.expanded:
            groups.append({
                "market": {
                    "id": 77,
                    "name": "Hándicap Asiatico",
                    "sv": "+2.5",
                    "typeId": 2,
                    "period": "full_game",
                    "scope": "event",
                },
                "odds": [
                    {
                        "id": 771,
                        "name": "Fulham (+2.5)",
                        "oddStatus": 0,
                        "price": 1.125,
                        "sv": "+2.5",
                    },
                    {
                        "id": 772,
                        "name": "Chelsea (-2.5)",
                        "oddStatus": 0,
                        "price": 6.0,
                        "sv": "+2.5",
                    },
                    {
                        "id": 773,
                        "name": "Fulham (+1.5)",
                        "oddStatus": 0,
                        "price": 1.3637,
                        "sv": "+2.5",
                    },
                    {
                        "id": 774,
                        "name": "Chelsea (-1.5)",
                        "oddStatus": 0,
                        "price": 3.1,
                        "sv": "+2.5",
                    },
                ],
            })
        return raw


def test_supported_market_extraction_expands_and_validates_opposing_spreads():
    driver = ExpandableSpreadDriver()

    markets = extract_supported_markets(
        driver,
        "Fulham",
        "Chelsea",
        event_id="16848649",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert driver.expanded is True
    assert [market["key"] for market in markets] == [
        "totals",
        "spreads",
        "spreads",
    ]
    spread = markets[1]
    assert spread["line"] == "+2.5"
    assert [row["line"] for row in spread["outcomes"]] == ["+2.5", "-2.5"]
    assert markets[2]["line"] == "+1.5"
    assert [row["line"] for row in markets[2]["outcomes"]] == [
        "+1.5",
        "-1.5",
    ]

    raw = fixture_event()
    raw["home"] = "Fulham"
    raw["away"] = "Chelsea"
    for outcome in raw["markets"][0]["outcomes"]:
        if outcome["key"] == "home":
            outcome["name"] = "Fulham"
        elif outcome["key"] == "away":
            outcome["name"] = "Chelsea"
    raw["markets"].extend(markets)
    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )
    assert [market.key for market in event.markets] == [
        "h2h",
        "totals",
        "spreads",
        "spreads",
    ]


class EventDriver(MarketDriver):
    def execute_script(self, script, *args):
        if "playdoit:event-summaries" in script:
            self.calls.append((script, args))
            return [
                {
                    "event_id": "playdoit-456",
                    "sport": "soccer",
                    "league": "Liga MX",
                    "home": "América",
                    "away": "Tigres",
                    "date_label": "21/08",
                    "time_label": "20:00",
                },
                {
                    "event_id": "missing-clock",
                    "sport": "soccer",
                    "league": "Liga MX",
                    "home": "Pumas",
                    "away": "Atlas",
                    "date_label": "21/08",
                    "time_label": "",
                },
            ]
        if "playdoit:click-event" in script:
            self.calls.append((script, args))
            assert args == ("playdoit-456", "América", "Tigres")
            return True
        if "playdoit:return-to-events" in script:
            self.calls.append((script, args))
            return True
        if "playdoit:event-list-ready" in script:
            self.calls.append((script, args))
            return True
        return super().execute_script(script, *args)


class CurrentReactSnapshotDriver(MarketDriver):
    def __init__(self):
        super().__init__()
        self.summary_script = ""
        self.clicked_event = None
        self.returned_to_events = False

    def execute_script(self, script, *args):
        if "playdoit:event-summaries" in script:
            self.summary_script = script
            return [{
                "event": {
                    "id": 17289368,
                    "name": "Cruz Azul vs. Atlas",
                    "startDate": "2026-08-23T03:00:00Z",
                    "status": 0,
                },
                "sport": {"id": 66, "name": "Fútbol", "iconName": "soccer"},
                "championship": {"id": 10009, "name": "Liga MX"},
                "competitors": [
                    {"id": 50908, "name": "Cruz Azul"},
                    {"id": 46433, "name": "Atlas"},
                ],
                "markets": [{
                    "market": {
                        "id": 1684427600,
                        "name": "Resultado Final (Tiempo Regular)",
                        "oddIds": [4350669530, 4350669531, 4350669532],
                        "typeId": 1,
                    },
                    "odds": [
                        {
                            "id": 4350669530,
                            "competitorId": 50908,
                            "name": "Cruz Azul",
                            "oddStatus": 0,
                            "price": 1.6154,
                            "typeId": 1,
                        },
                        {
                            "id": 4350669531,
                            "name": "Empate",
                            "oddStatus": 0,
                            "price": 4.0,
                            "typeId": 2,
                        },
                        {
                            "id": 4350669532,
                            "competitorId": 46433,
                            "name": "Atlas",
                            "oddStatus": 0,
                            "price": 5.5,
                            "typeId": 3,
                        },
                    ],
                }],
            }]
        if "playdoit:click-event" in script:
            self.calls.append((script, args))
            self.clicked_event = args
            self.active = "h2h"
            return True
        if "playdoit:return-to-events" in script:
            self.calls.append((script, args))
            self.returned_to_events = True
            return True
        if "playdoit:event-list-ready" in script:
            self.calls.append((script, args))
            return True
        if "playdoit:extract-visible-market" in script:
            self.calls.append((script, args))
            key, home, away = args[:3]
            if key == "h2h":
                return [{
                    "key": "h2h",
                    "title": "resultado final (tiempo regular)",
                    "period": "full_game",
                    "scope": "event",
                    "outcomes": [
                        {"key": "home", "name": home, "price": "1.6154"},
                        {"key": "draw", "name": "Empate", "price": "4.0"},
                        {"key": "away", "name": away, "price": "5.5"},
                    ],
                }]
            if key == "totals":
                return [{
                    "key": "totals",
                    "title": "total de goles",
                    "period": "full_game",
                    "scope": "event",
                    "line": "2.5",
                    "outcomes": [
                        {"key": "over", "name": "Más 2.5", "price": "1.90", "line": "2.5"},
                        {"key": "under", "name": "Menos 2.5", "price": "1.90", "line": "2.5"},
                    ],
                }]
            return [{
                "key": "spreads",
                "title": "hándicap del partido",
                "period": "full_game",
                "scope": "event",
                "line": "-1.0",
                "outcomes": [
                    {"key": "home", "name": f"{home} -1.0", "price": "2.10", "line": "-1.0"},
                    {"key": "away", "name": f"{away} +1.0", "price": "1.70", "line": "+1.0"},
                ],
            }]
        return super().execute_script(script, *args)


def test_current_react_snapshot_opens_detail_and_keeps_all_supported_markets():
    driver = CurrentReactSnapshotDriver()
    records = extract_playdoit_raw_events(
        driver,
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert len(records) == 1
    assert "__reactFiber$" in driver.summary_script
    assert "memoizedProps" in driver.summary_script
    assert "oddIds" in driver.summary_script
    assert records[0]["event_id"] == "17289368"
    assert records[0]["date_label"] == "22/08"
    assert records[0]["time_label"] == "21:00"
    assert driver.clicked_event == ("17289368", "Cruz Azul", "Atlas")
    assert driver.returned_to_events is True
    click_source = next(
        script
        for script, _args in driver.calls
        if "playdoit:click-event" in script
    )
    assert "__reactFiber$" in click_source
    assert "17289368" not in click_source

    event = normalize_playdoit_event(
        records[0], datetime(2026, 8, 22, 12, tzinfo=MEXICO)
    )
    assert [market.key for market in event.markets] == [
        "h2h",
        "totals",
        "spreads",
    ]
    h2h = event.markets[0]
    assert h2h.outcome("home").price == 1.6154
    assert h2h.outcome("draw").price == 4.0
    assert h2h.outcome("away").price == 5.5


class SnapshotDetailUnavailableDriver(CurrentReactSnapshotDriver):
    def execute_script(self, script, *args):
        if "playdoit:click-event" in script:
            self.calls.append((script, args))
            self.clicked_event = args
            return False
        return super().execute_script(script, *args)


def test_current_react_snapshot_keeps_verified_h2h_when_detail_is_unavailable():
    driver = SnapshotDetailUnavailableDriver()

    records = extract_playdoit_raw_events(
        driver,
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert driver.clicked_event == ("17289368", "Cruz Azul", "Atlas")
    event = normalize_playdoit_event(
        records[0], datetime(2026, 8, 22, 12, tzinfo=MEXICO)
    )
    assert [market.key for market in event.markets] == ["h2h"]
    assert event.markets[0].outcome("home").price == 1.6154


class ConflictingSnapshotDetailDriver(CurrentReactSnapshotDriver):
    def execute_script(self, script, *args):
        result = super().execute_script(script, *args)
        if "playdoit:extract-visible-market" in script and args[0] == "h2h":
            result[0]["outcomes"][0]["price"] = "9.99"
        return result


def test_current_react_snapshot_rejects_conflicting_detail_quote_fail_closed():
    records = extract_playdoit_raw_events(
        ConflictingSnapshotDetailDriver(),
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    event = normalize_playdoit_event(
        records[0], datetime(2026, 8, 22, 12, tzinfo=MEXICO)
    )
    assert [market.key for market in event.markets] == ["totals", "spreads"]


def test_repeated_snapshot_reuses_detail_markets_within_one_collection_run():
    driver = CurrentReactSnapshotDriver()
    detail_cache = {}

    first = extract_playdoit_raw_events(
        driver,
        wait_factory=ImmediateWait,
        timeout=0.01,
        detail_cache=detail_cache,
    )
    second = extract_playdoit_raw_events(
        driver,
        wait_factory=ImmediateWait,
        timeout=0.01,
        detail_cache=detail_cache,
    )

    detail_clicks = [
        args
        for script, args in driver.calls
        if "playdoit:click-event" in script
    ]
    assert detail_clicks == [("17289368", "Cruz Azul", "Atlas")]
    assert first == second


class DistantReactSnapshotDriver(CurrentReactSnapshotDriver):
    def execute_script(self, script, *args):
        result = super().execute_script(script, *args)
        if "playdoit:event-summaries" in script:
            result[0]["event"]["startDate"] = "2026-08-30T03:00:00Z"
        return result


def test_distant_snapshot_keeps_surface_h2h_without_opening_event_detail():
    driver = DistantReactSnapshotDriver()

    records = extract_playdoit_raw_events(
        driver,
        wait_factory=ImmediateWait,
        timeout=0.01,
        detail_observed_at=datetime(2026, 8, 22, 12, tzinfo=MEXICO),
    )

    assert len(records) == 1
    assert driver.clicked_event is None
    event = normalize_playdoit_event(
        records[0], datetime(2026, 8, 22, 12, tzinfo=MEXICO)
    )
    assert [market.key for market in event.markets] == ["h2h"]


def test_full_extraction_requires_id_date_time_and_never_synthesizes_defaults():
    driver = EventDriver()
    rejections = []

    records = extract_playdoit_raw_events(
        driver,
        wait_factory=ImmediateWait,
        timeout=0.01,
        rejections=rejections,
    )

    assert len(records) == 1
    assert records[0]["event_id"] == "playdoit-456"
    assert records[0]["date_label"] == "21/08"
    assert records[0]["time_label"] == "20:00"
    assert records[0]["markets"][0]["key"] == "h2h"
    assert records[0]["markets"][0]["title"] == "resultado final"
    assert records[0]["markets"][0]["period"] == "full_game"
    assert records[0]["markets"][0]["scope"] == "event"
    click_script, click_args = next(
        (script, args)
        for script, args in driver.calls
        if "playdoit:click-event" in script
    )
    assert "playdoit-456" not in click_script
    assert click_args == ("playdoit-456", "América", "Tigres")
    assert rejections == ["missing_start_time"]


class IsolatedEventFailureDriver(MarketDriver):
    def execute_script(self, script, *args):
        if "playdoit:event-summaries" in script:
            return [
                {
                    "event_id": event_id,
                    "sport": "soccer",
                    "league": "Liga MX",
                    "home": home,
                    "away": away,
                    "date_label": "21/08",
                    "time_label": "20:00",
                }
                for event_id, home, away in (
                    ("broken-click", "Pumas", "Atlas"),
                    ("event-2", "América", "Tigres"),
                    ("event-3", "Cruz Azul", "Toluca"),
                )
            ]
        if "playdoit:click-event" in script:
            if args[0] == "broken-click":
                raise RuntimeError("detached event")
            self.active = "h2h"
            return True
        if "playdoit:return-to-events" in script:
            raise RuntimeError("back button replaced")
        if "playdoit:event-list-ready" in script:
            raise RuntimeError("list not observable")
        return super().execute_script(script, *args)


def test_event_click_return_and_list_wait_failures_are_isolated_from_siblings():
    records = extract_playdoit_raw_events(
        IsolatedEventFailureDriver(),
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert [record["event_id"] for record in records] == ["event-2", "event-3"]


class AmbiguousIdentityDriver:
    def execute_script(self, script, *_args):
        if "playdoit:event-summaries" in script:
            return [{
                "event_id": "",
                "home": "América",
                "away": "Tigres",
                "date_label": "21/08",
                "time_label": "20:00",
                "rejection_reason": "ambiguous_event_identity",
            }]
        raise AssertionError("ambiguous identity must never be clicked")


def test_ambiguous_event_id_is_rejected_with_an_observable_reason():
    rejections = []

    assert extract_playdoit_raw_events(
        AmbiguousIdentityDriver(), rejections=rejections
    ) == []
    assert rejections == ["ambiguous_event_identity"]


def test_scraper_normalizes_playdoit_records_before_legacy_projection(monkeypatch):
    from backend import scraper

    raw = fixture_event()
    monkeypatch.setattr(
        scraper, "extract_playdoit_raw_events", lambda _driver: [raw]
    )

    records = scraper.extract_events_from_page(
        object(), observed_at=datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert len(records) == 1
    assert records[0]["source"] == "playdoit"
    assert records[0]["source_event_id"] == "playdoit-456"
    assert records[0]["bookmaker_key"] == "playdoit"
    assert records[0]["cuotas_por_resultado"] == {
        "home": "1.72",
        "draw": "3.25",
        "away": "2.35",
    }
    assert records[0]["observed_at"].startswith("2026-08-20T10:00:00")
    assert records[0]["starts_at"].startswith("2026-08-21T20:00:00")


def test_scraper_playdoit_integration_rejects_conflicting_source_revisions(
    monkeypatch,
):
    from backend import scraper

    raw = fixture_event()
    conflict = deepcopy(raw)
    conflict["markets"][0]["outcomes"][0]["price"] = "9.99"
    monkeypatch.setattr(
        scraper,
        "extract_playdoit_raw_events",
        lambda _driver: [raw, conflict],
    )

    records = scraper.extract_events_from_page(
        object(), observed_at=datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert records == []


def test_marketless_playdoit_event_is_not_fed_to_picks(monkeypatch):
    from backend import scraper

    raw = fixture_event()
    raw["markets"] = []
    monkeypatch.setattr(
        scraper, "extract_playdoit_raw_events", lambda _driver, **_kw: [raw]
    )

    assert scraper.extract_events_from_page(
        object(), observed_at=datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    ) == []


def test_projection_preserves_bookmaker_even_when_h2h_is_absent():
    from backend import scraper

    raw = fixture_event()
    raw["markets"] = [{
        "key": "totals",
        "title": "Total de goles",
        "period": "full_game",
        "scope": "event",
        "line": "2.5",
        "outcomes": [
            {"key": "over", "name": "Más de 2.5", "line": "2.5", "price": "1.89"},
            {"key": "under", "name": "Menos de 2.5", "line": "2.5", "price": "1.91"},
        ],
    }]
    event = normalize_playdoit_event(
        raw, datetime(2026, 8, 20, 10, tzinfo=MEXICO)
    )

    assert scraper._legacy_odds_projection(event)["bookmaker_key"] == "playdoit"


class NoScriptDriver:
    def execute_script(self, *_args):
        raise AssertionError("an unmatched objective must not click another event")


def test_deep_phase_does_not_fall_back_to_an_arbitrary_event():
    from backend import scraper

    catalog = [{
        "source": "playdoit",
        "source_event_id": "event-1",
        "bookmaker_key": "playdoit",
        "categoria": "Liga MX",
        "partido": "América vs Tigres",
        "local": "América",
        "visitante": "Tigres",
        "horario": "Mañana • 20:00",
        "cuotas_por_resultado": {"home": "1.72"},
    }]

    assert scraper.fase4_inmersion(
        NoScriptDriver(), ["Pumas vs Atlas"], catalog
    ) == []


def test_deep_phase_rejects_text_only_doubleheader_ambiguity():
    from backend import scraper

    catalog = [
        {
            "source": "playdoit",
            "source_event_id": f"event-{index}",
            "bookmaker_key": "playdoit",
            "categoria": "MLB",
            "partido": "Dodgers vs Padres",
            "local": "Dodgers",
            "visitante": "Padres",
            "horario": f"Mañana • {18 + index}:00",
            "cuotas_por_resultado": {"home": "1.72"},
            "mercados_reales": ["[H2H]: Dodgers @ 1.72"],
        }
        for index in range(2)
    ]

    assert scraper.fase4_inmersion(
        NoScriptDriver(), ["Dodgers vs Padres"], catalog
    ) == []


def test_deep_phase_can_resolve_explicit_source_id_without_unstructured_tabs():
    from backend import scraper

    event = {
        "source": "playdoit",
        "source_event_id": "event-2",
        "bookmaker_key": "playdoit",
        "categoria": "MLB",
        "partido": "Dodgers vs Padres",
        "local": "Dodgers",
        "visitante": "Padres",
        "horario": "Mañana • 20:00",
        "cuotas_por_resultado": {"home": "1.72"},
        "mercados_reales": ["[H2H]: Dodgers @ 1.72"],
    }

    assert scraper.fase4_inmersion(
        NoScriptDriver(),
        [{"partido": "Dodgers vs Padres", "source_event_id": "event-2"}],
        [event],
    ) == [{**event, "mercados_profundos": "[H2H]: Dodgers @ 1.72"}]


def test_legacy_dedupe_identity_includes_source_and_source_event_id():
    from backend import scraper

    playdoit = {
        "source": "playdoit",
        "source_event_id": "shared-id",
        "local": "América",
        "visitante": "Tigres",
        "horario": "Mañana • 20:00",
        "cuotas_por_resultado": {"home": "1.72"},
    }
    odds_api = {
        **playdoit,
        "source": "the_odds_api",
        "cuotas_por_resultado": {"home": "1.75"},
    }

    assert scraper._deduplicate_event_records([playdoit, odds_api]) == [
        playdoit,
        odds_api,
    ]


class CategoryDriver:
    def __init__(self):
        self.calls = []

    def execute_script(self, script, *args):
        self.calls.append((script, args))
        return True


def test_click_category_passes_category_as_a_script_argument():
    from backend import scraper

    driver = CategoryDriver()

    assert scraper.click_category(driver, "O'Higgins") is True
    script, args = driver.calls[-1]
    assert args == ("o'higgins",)
    assert "var catLower = arguments[0]" in script
    assert "o'higgins" not in script.casefold()


def test_scraper_has_no_hardcoded_operational_date_or_hoy_schedule_default():
    text = SCRAPER.read_text(encoding="utf-8")

    assert "18/08" not in text
    assert "19/08" not in text
    assert "get('horario', 'Hoy')" not in text
    assert 'get("horario", "Hoy")' not in text
    assert "_surface_event_record(e, cat_real, horario_limpio)" not in text
    assert "tabsToExplore" not in text


def test_dom_extractor_uses_only_vetted_event_ids_prices_and_full_game_titles():
    source = (
        Path(__file__).resolve().parents[1] / "backend" / "playdoit_source.py"
    ).read_text(encoding="utf-8")

    assert "[data-id]" not in source
    assert "getAttribute('data-id')" not in source
    assert "playdoit:is-market-tab-active" in source
    assert "playdoit:event-list-ready" in source
    assert "data-odds" in source or "data-price" in source
    assert "priceNode" in source
    assert "prices = Array.from(text.matchAll" not in source
    assert "SUPPORTED_BOX_TITLES" in source
    assert "first_half" in source
    assert "team_total" in source
    assert "getAttribute('data-period') || 'full_game'" not in source
    assert "getAttribute('data-scope') || 'event'" not in source
    assert "title: title" in source
    assert "period: period" in source
    assert "scope: scope" in source
    assert "period: 'full_game'" not in source

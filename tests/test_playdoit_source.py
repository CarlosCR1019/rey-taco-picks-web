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
        for _ in range(3):
            value = predicate(self.driver)
            if value:
                return value
        from selenium.common.exceptions import TimeoutException

        raise TimeoutException("unchanged")


class MarketDriver:
    def __init__(self, *, stuck_key=None, active=None, late_details=False):
        self.active = active
        self.stuck_key = stuck_key
        self.late_details = late_details
        self.discovery_calls = 0
        self.calls = []

    def execute_script(self, script, *args):
        self.calls.append((script, args))
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

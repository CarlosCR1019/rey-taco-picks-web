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
            "period": "full_game",
            "line": "2.5",
            "outcomes": [
                {"key": "under", "name": "Menos de 2.5", "line": "2.5", "price": "1.91"},
                {"key": "over", "name": "Más de 2.5", "line": "2.5", "price": "1.89"},
            ],
        },
        {
            "key": "spreads",
            "period": "full_game",
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
        "period": "full_game",
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
                "period": "full_game",
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


class ImmediateWait:
    def __init__(self, driver, timeout):
        self.driver = driver
        self.timeout = timeout

    def until(self, predicate):
        value = predicate(self.driver)
        if not value:
            from selenium.common.exceptions import TimeoutException

            raise TimeoutException("unchanged")
        return value


class MarketDriver:
    def __init__(self, *, stuck_key=None):
        self.active = None
        self.stuck_key = stuck_key
        self.discovery_calls = 0
        self.calls = []

    def execute_script(self, script, *args):
        self.calls.append((script, args))
        if "playdoit:discover-market-tabs" in script:
            self.discovery_calls += 1
            return [
                {"key": "h2h", "token": "tab-h2h"},
                {"key": "totals", "token": "tab-totals"},
                {"key": "spreads", "token": "tab-spreads"},
            ]
        if "playdoit:market-signature" in script:
            if self.active == self.stuck_key:
                return "overview"
            return "overview" if self.active is None else f"market:{self.active}"
        if "playdoit:click-market-tab" in script:
            self.active = args[0].removeprefix("tab-")
            return True
        if "playdoit:extract-visible-market" in script:
            key, home, away = args
            if key == "h2h":
                return [{
                    "key": "h2h",
                    "period": "full_game",
                    "outcomes": [
                        {"key": "home", "name": home, "price": "1.72"},
                        {"key": "draw", "name": "Empate", "price": "3.25"},
                        {"key": "away", "name": away, "price": "2.35"},
                    ],
                }]
            return []
        raise AssertionError("unexpected script")


def test_market_tabs_are_recaptured_and_one_timeout_does_not_abort_siblings():
    driver = MarketDriver(stuck_key="h2h")

    markets = extract_supported_markets(
        driver,
        "América",
        "Tigres",
        wait_factory=ImmediateWait,
        timeout=0.01,
    )

    assert markets == []
    assert driver.discovery_calls == 3
    clicked_tokens = [
        args[0]
        for script, args in driver.calls
        if "playdoit:click-market-tab" in script
    ]
    assert clicked_tokens == ["tab-h2h", "tab-totals", "tab-spreads"]


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
    assert source_calls[0][1] == ("h2h", "América", "Tigres")


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
        return super().execute_script(script, *args)


def test_full_extraction_requires_id_date_time_and_never_synthesizes_defaults():
    driver = EventDriver()

    records = extract_playdoit_raw_events(
        driver, wait_factory=ImmediateWait, timeout=0.01
    )

    assert len(records) == 1
    assert records[0]["event_id"] == "playdoit-456"
    assert records[0]["date_label"] == "21/08"
    assert records[0]["time_label"] == "20:00"
    assert records[0]["markets"][0]["key"] == "h2h"
    click_script, click_args = next(
        (script, args)
        for script, args in driver.calls
        if "playdoit:click-event" in script
    )
    assert "playdoit-456" not in click_script
    assert click_args == ("playdoit-456", "América", "Tigres")


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


def test_projection_preserves_bookmaker_even_when_h2h_is_absent():
    from backend import scraper

    raw = fixture_event()
    raw["markets"] = [{
        "key": "totals",
        "period": "full_game",
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


def test_scraper_has_no_hardcoded_operational_date_or_hoy_schedule_default():
    text = SCRAPER.read_text(encoding="utf-8")

    assert "18/08" not in text
    assert "19/08" not in text
    assert "get('horario', 'Hoy')" not in text
    assert 'get("horario", "Hoy")' not in text
    assert "_surface_event_record(e, cat_real, horario_limpio)" not in text

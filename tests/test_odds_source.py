from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from backend.odds_source import (
    OddsSourceError,
    build_odds_url,
    fetch_odds_events,
    normalize_odds_event,
)


FIXTURE = Path(__file__).parent / "fixtures" / "odds_api_event.json"
SCRAPER = Path(__file__).resolve().parents[1] / "backend" / "scraper.py"
ODDS_SOURCE = Path(__file__).resolve().parents[1] / "backend" / "odds_source.py"
OBSERVED_AT = datetime(2026, 8, 20, 20, tzinfo=timezone.utc)


def fixture_event() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_outcomes_are_named_even_when_api_order_and_case_change():
    event = normalize_odds_event(fixture_event(), OBSERVED_AT)

    h2h = next(market for market in event.markets if market.key == "h2h")
    assert tuple(outcome.key for outcome in h2h.outcomes) == (
        "home",
        "draw",
        "away",
    )
    assert h2h.outcome("home").name == "américa"
    assert h2h.outcome("home").price == 1.70
    assert h2h.outcome("away").price == 2.40


def test_missing_bookmakers_produces_no_markets_instead_of_default_odds():
    raw = fixture_event()
    raw["bookmakers"] = []

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert event.markets == ()


@pytest.mark.parametrize("price", [None, "not-a-price", float("nan"), 1.0, 99.0])
def test_malformed_price_skips_the_whole_market(price):
    raw = fixture_event()
    raw["bookmakers"][0]["markets"][0]["outcomes"][0]["price"] = price

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert all(market.key != "h2h" for market in event.markets)


def test_incomplete_h2h_skips_the_whole_market():
    raw = fixture_event()
    raw["bookmakers"][0]["markets"][0]["outcomes"] = [
        {"name": "América", "price": 1.70}
    ]

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert all(market.key != "h2h" for market in event.markets)


def test_totals_require_the_same_finite_point_and_use_it_as_market_line():
    event = normalize_odds_event(fixture_event(), OBSERVED_AT)
    total = next(market for market in event.markets if market.key == "totals")
    assert total.line == 2.5
    assert tuple(outcome.key for outcome in total.outcomes) == ("over", "under")

    raw = fixture_event()
    raw["bookmakers"][0]["markets"][1]["outcomes"][0]["point"] = 3.5
    malformed = normalize_odds_event(raw, OBSERVED_AT)
    assert all(market.key != "totals" for market in malformed.markets)


@pytest.mark.parametrize("bad_point", [None, "2.5", float("inf")])
def test_totals_with_malformed_points_are_skipped(bad_point):
    raw = fixture_event()
    raw["bookmakers"][0]["markets"][1]["outcomes"][0]["point"] = bad_point

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert all(market.key != "totals" for market in event.markets)


def test_spreads_require_opposing_points_and_use_home_handicap_as_line():
    event = normalize_odds_event(fixture_event(), OBSERVED_AT)
    spread = next(market for market in event.markets if market.key == "spreads")
    assert spread.line == -1.5
    assert tuple(outcome.key for outcome in spread.outcomes) == ("home", "away")

    raw = fixture_event()
    raw["bookmakers"][0]["markets"][2]["outcomes"][0]["point"] = 1.0
    malformed = normalize_odds_event(raw, OBSERVED_AT)
    assert all(market.key != "spreads" for market in malformed.markets)


def test_exact_duplicate_market_signatures_are_deduplicated_deterministically():
    raw = fixture_event()
    duplicate = deepcopy(raw["bookmakers"][0])
    duplicate["key"] = "book-b"
    for market in duplicate["markets"]:
        market["outcomes"].reverse()
    raw["bookmakers"].append(duplicate)

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert tuple(market.key for market in event.markets) == (
        "h2h",
        "totals",
        "spreads",
    )


def test_distinct_bookmaker_quotes_are_preserved():
    raw = fixture_event()
    second = deepcopy(raw["bookmakers"][0])
    second["key"] = "book-b"
    second["markets"][0]["outcomes"][0]["price"] = 2.45
    raw["bookmakers"].append(second)

    event = normalize_odds_event(raw, OBSERVED_AT)

    h2h = [market for market in event.markets if market.key == "h2h"]
    assert [market.outcome("away").price for market in h2h] == [2.40, 2.45]


def test_invalid_or_past_event_identity_is_not_silently_swallowed():
    raw = fixture_event()
    raw["id"] = ""
    with pytest.raises(ValueError, match="source_event_id"):
        normalize_odds_event(raw, OBSERVED_AT)

    raw = fixture_event()
    raw["commence_time"] = "2026-08-20T19:59:00Z"
    with pytest.raises(ValueError, match="future"):
        normalize_odds_event(raw, OBSERVED_AT)


def test_url_uses_urlencode_decimal_odds_and_only_concrete_configured_sports():
    url = build_odds_url(
        "soccer_mexico_ligamx",
        "secret with + and &",
        regions=("us", "eu"),
        markets=("h2h", "totals", "spreads"),
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path.endswith("/sports/soccer_mexico_ligamx/odds/")
    assert query == {
        "apiKey": ["secret with + and &"],
        "regions": ["us,eu"],
        "markets": ["h2h,totals,spreads"],
        "oddsFormat": ["decimal"],
    }

    with pytest.raises(ValueError, match="concrete configured sport"):
        build_odds_url("soccer", "secret")


class FakeResponse:
    def __init__(self, payload: object):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_fetch_boundary_is_bounded_validates_list_and_does_not_leak_secret():
    calls = []

    def opener(request, *, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse([fixture_event()])

    rows = fetch_odds_events(
        "provider-secret",
        "soccer_mexico_ligamx",
        timeout=7.5,
        opener=opener,
    )
    assert rows == [fixture_event()]
    assert calls[0][1] == 7.5
    assert parse_qs(urlparse(calls[0][0]).query)["oddsFormat"] == ["decimal"]

    with pytest.raises(OddsSourceError, match="JSON list"):
        fetch_odds_events(
            "provider-secret",
            "soccer_mexico_ligamx",
            opener=lambda *_args, **_kwargs: FakeResponse({"message": "bad"}),
        )

    def failed_opener(*_args, **_kwargs):
        raise RuntimeError("provider-secret was rejected")

    with pytest.raises(OddsSourceError) as captured:
        fetch_odds_events(
            "provider-secret",
            "soccer_mexico_ligamx",
            opener=failed_opener,
        )
    assert "provider-secret" not in str(captured.value)
    assert "rejected" not in str(captured.value)


def test_scraper_legacy_projection_uses_named_h2h_and_no_missing_market_price(
    monkeypatch,
):
    from backend import scraper

    raw = fixture_event()
    calls = []

    def fake_fetch(api_key, sport_key, **kwargs):
        calls.append((api_key, sport_key, kwargs))
        return [deepcopy(raw)]

    monkeypatch.setattr(scraper, "fetch_odds_events", fake_fetch)
    projected = scraper.obtener_eventos_odds_api(
        "secret", observed_at=OBSERVED_AT
    )

    assert projected[0]["cuotas_por_resultado"] == {
        "home": "1.70",
        "draw": "3.30",
        "away": "2.40",
    }
    assert projected[0]["cuotas_superficie"] == ["1.70", "3.30", "2.40"]
    assert all(call[1] != "soccer" for call in calls)
    assert all(call[2]["markets"] == ("h2h", "totals", "spreads") for call in calls)

    raw["bookmakers"] = []
    projected_without_markets = scraper.obtener_eventos_odds_api(
        "secret", observed_at=OBSERVED_AT
    )
    assert projected_without_markets[0]["cuotas_por_resultado"] == {}
    assert projected_without_markets[0]["cuotas_superficie"] == []


def test_market_comparison_uses_normalized_named_outcomes_and_concrete_sports(
    monkeypatch,
):
    from backend import scraper

    calls = []

    def fake_fetch(api_key, sport_key, **kwargs):
        calls.append((api_key, sport_key, kwargs))
        return [fixture_event()]

    monkeypatch.setattr(scraper, "fetch_odds_events", fake_fetch)
    prices = scraper.fase2_comparacion_mercado(
        [], odds_api_key="secret", observed_at=OBSERVED_AT
    )

    assert prices["américa"] == 1.70
    assert prices["tigres"] == 2.40
    assert all(call[1] != "soccer" for call in calls)
    assert all(call[2]["markets"] == ("h2h",) for call in calls)


def test_scraper_source_requests_decimal_and_contains_no_synthetic_fallback_trio():
    source_text = ODDS_SOURCE.read_text(encoding="utf-8")
    scraper_text = SCRAPER.read_text(encoding="utf-8")
    assert '"oddsFormat": "decimal"' in source_text
    assert '["1.85", "3.20", "2.10"]' not in scraper_text

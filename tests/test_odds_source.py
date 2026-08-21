from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
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


def test_exact_duplicate_market_signatures_from_one_bookmaker_are_deduplicated():
    raw = fixture_event()
    duplicate = deepcopy(raw["bookmakers"][0])
    for market in duplicate["markets"]:
        market["outcomes"].reverse()
    raw["bookmakers"].append(duplicate)

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert tuple(market.key for market in event.markets) == (
        "h2h",
        "totals",
        "spreads",
    )


def test_conflicting_prices_for_one_bookmaker_market_identity_are_omitted():
    raw = fixture_event()
    conflicting = deepcopy(raw["bookmakers"][0])
    conflicting["markets"][0]["outcomes"][0]["price"] = 2.45
    raw["bookmakers"].append(conflicting)

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert all(market.key != "h2h" for market in event.markets)
    assert tuple(market.key for market in event.markets) == ("totals", "spreads")


def test_same_bookmaker_can_preserve_distinct_market_lines():
    raw = fixture_event()
    second_total = deepcopy(raw["bookmakers"][0]["markets"][1])
    for outcome in second_total["outcomes"]:
        outcome["point"] = 3.5
    raw["bookmakers"][0]["markets"].append(second_total)

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert [market.line for market in event.markets if market.key == "totals"] == [
        2.5,
        3.5,
    ]


def test_distinct_bookmaker_quotes_are_preserved():
    raw = fixture_event()
    second = deepcopy(raw["bookmakers"][0])
    second["key"] = "book-b"
    second["markets"][0]["outcomes"][0]["price"] = 2.45
    raw["bookmakers"].append(second)

    event = normalize_odds_event(raw, OBSERVED_AT)

    h2h = [market for market in event.markets if market.key == "h2h"]
    assert [market.outcome("away").price for market in h2h] == [2.40, 2.45]
    assert [market.bookmaker_key for market in h2h] == ["book-a", "book-b"]


def test_identical_quotes_from_distinct_bookmakers_preserve_multiplicity():
    raw = fixture_event()
    second = deepcopy(raw["bookmakers"][0])
    second["key"] = "book-b"
    raw["bookmakers"].append(second)

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert len([market for market in event.markets if market.key == "h2h"]) == 2
    assert {market.bookmaker_key for market in event.markets} == {"book-a", "book-b"}


def test_bookmaker_without_stable_identity_contributes_no_markets():
    raw = fixture_event()
    raw["bookmakers"][0]["key"] = "  "

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert event.markets == ()


def test_soccer_h2h_requires_exact_home_draw_away_set():
    raw = fixture_event()
    raw["bookmakers"][0]["markets"][0]["outcomes"] = [
        {"name": "América", "price": 1.70},
        {"name": "Tigres", "price": 2.40},
    ]

    event = normalize_odds_event(raw, OBSERVED_AT)

    assert all(market.key != "h2h" for market in event.markets)


def test_two_way_sport_h2h_requires_exact_home_away_set():
    raw = fixture_event()
    raw["sport_key"] = "baseball_mlb"

    with_draw = normalize_odds_event(raw, OBSERVED_AT)
    assert all(market.key != "h2h" for market in with_draw.markets)

    raw["bookmakers"][0]["markets"][0]["outcomes"] = [
        {"name": "Tigres", "price": 2.40},
        {"name": "América", "price": 1.70},
    ]
    two_way = normalize_odds_event(raw, OBSERVED_AT)
    h2h = next(market for market in two_way.markets if market.key == "h2h")
    assert tuple(outcome.key for outcome in h2h.outcomes) == ("home", "away")


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
    def __init__(
        self, payload: object, *, status: int = 200, raw: bytes | None = None
    ):
        self.payload = payload
        self.status = status
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, amount: int = -1) -> bytes:
        encoded = (
            self.raw
            if self.raw is not None
            else json.dumps(self.payload).encode("utf-8")
        )
        return encoded if amount < 0 else encoded[:amount]


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


@pytest.mark.parametrize("status", [199, 300, 401, 503])
def test_fetch_rejects_every_non_2xx_http_status(status):
    with pytest.raises(OddsSourceError, match="HTTP status"):
        fetch_odds_events(
            "provider-secret",
            "soccer_mexico_ligamx",
            opener=lambda *_args, **_kwargs: FakeResponse([], status=status),
        )


def test_fetch_rejects_response_body_larger_than_configured_limit():
    with pytest.raises(OddsSourceError, match="body exceeds"):
        fetch_odds_events(
            "provider-secret",
            "soccer_mexico_ligamx",
            max_response_bytes=16,
            opener=lambda *_args, **_kwargs: FakeResponse(None, raw=b"[" + b" " * 16),
        )


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
    assert projected[0]["source_event_id"] == "event-123"
    assert projected[0]["bookmaker_key"] == "book-a"
    assert projected[0]["cuotas_superficie"] == ["1.70", "3.30", "2.40"]
    assert all(call[1] != "soccer" for call in calls)
    assert all(call[2]["markets"] == ("h2h", "totals", "spreads") for call in calls)

    raw["bookmakers"] = []
    projected_without_markets = scraper.obtener_eventos_odds_api(
        "secret", observed_at=OBSERVED_AT
    )
    assert projected_without_markets[0]["cuotas_por_resultado"] == {}
    assert projected_without_markets[0]["cuotas_superficie"] == []
    assert projected_without_markets[0]["bookmaker_key"] is None


def test_odds_projection_retains_same_team_events_with_distinct_source_ids(
    monkeypatch,
):
    from backend import scraper

    first = fixture_event()
    second = deepcopy(first)
    second["id"] = "event-456"
    second["commence_time"] = "2026-08-21T03:00:00Z"
    monkeypatch.setattr(
        scraper,
        "fetch_odds_events",
        lambda *_args, **_kwargs: [deepcopy(first), deepcopy(second)],
    )

    projected = scraper.obtener_eventos_odds_api("secret", observed_at=OBSERVED_AT)

    assert [event["source_event_id"] for event in projected] == [
        "event-123",
        "event-456",
    ]


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


@pytest.mark.parametrize(
    "raw",
    [None, "", "bad", 0, "0", 99, "99", True, math.nan, math.inf, "1.70x"],
)
def test_legacy_decimal_normalizer_rejects_invalid_values_without_a_default(raw):
    from backend.scraper import normalizar_cuota_decimal

    assert normalizar_cuota_decimal(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(1.70, "1.70"), ("1.70", "1.70"), ("+110", "2.10"), ("-110", "1.91")],
)
def test_legacy_decimal_normalizer_preserves_decimal_or_explicit_american_odds(
    raw, expected
):
    from backend.scraper import normalizar_cuota_decimal

    assert normalizar_cuota_decimal(raw) == expected


def _run_legacy_ai(monkeypatch, raw_picks, *, named_prices=None):
    from backend import scraper

    monkeypatch.setattr(scraper, "Groq", lambda **_kwargs: object())
    responses = iter(("quant", "audit", json.dumps(raw_picks)))
    monkeypatch.setattr(
        scraper,
        "ejecutar_groq_con_fallback",
        lambda *_args, **_kwargs: next(responses),
    )
    event = {
        "categoria": "Liga MX",
        "partido": "América vs Tigres",
        "local": "América",
        "visitante": "Tigres",
        "horario": "Mañana 23:59",
        "cuotas_por_resultado": named_prices or {},
        "cuotas_superficie": [],
        "info_texto": "",
        "source_event_id": "event-123",
        "bookmaker_key": "book-a",
    }
    return scraper.fase6_analisis_final(
        [event], "", {}, [event], groq_api_key="fake-key"
    )


@pytest.mark.parametrize("invalid", [None, "bad", 0, 99, "1.70", "+110"])
def test_ai_validated_path_discards_every_price_without_named_evidence(
    monkeypatch, invalid
):
    raw_picks = [
        {
            "partido": "América vs Tigres",
            "pick": "América Gana Directo",
            "cuota": invalid,
            "horario": "Mañana 23:59",
            "razonamiento": "Datos suficientes para explicar la selección.",
            "es_parlay": False,
            "odds_mercado": "1.55",
        },
    ]

    picks = _run_legacy_ai(monkeypatch, raw_picks)

    assert picks == []


def test_ai_price_is_ignored_and_exact_named_observation_is_copied(monkeypatch):
    raw_picks = [
        {
            "partido": "América vs Tigres",
            "pick": "América Gana Directo",
            "cuota": ai_price,
            "horario": "Mañana 23:59",
            "razonamiento": "Datos suficientes para explicar la selección.",
            "es_parlay": False,
            "odds_mercado": "1.55",
        }
        for ai_price in ("1.72", "9.99", "+110")
    ]

    picks = _run_legacy_ai(
        monkeypatch,
        raw_picks,
        named_prices={"home": "1.72", "draw": "3.30", "away": "2.40"},
    )

    assert [pick["cuota"] for pick in picks] == ["1.72", "1.72", "1.72"]
    assert all("odds_mercado" not in pick for pick in picks)
    assert all(pick["source_event_id"] == "event-123" for pick in picks)
    assert all(pick["bookmaker_key"] == "book-a" for pick in picks)
    assert all("confianza" not in pick and "tiene_valor" not in pick for pick in picks)


def test_legacy_event_matching_requires_exact_two_team_identity_and_rejects_ambiguity():
    from backend import scraper

    events = [
        {
            "source_event_id": "america-tigres",
            "bookmaker_key": "book-a",
            "partido": "América vs Tigres",
            "local": "América",
            "visitante": "Tigres",
        },
        {
            "source_event_id": "america-pumas",
            "bookmaker_key": "book-a",
            "partido": "América vs Pumas",
            "local": "América",
            "visitante": "Pumas",
        },
    ]

    assert (
        scraper._match_observed_event("América vs Pumas", None, events)
        is events[1]
    )
    assert scraper._match_observed_event("América", None, events) is None
    assert scraper._match_observed_event("América vs Pumas", "america-tigres", events) is None
    assert scraper._match_observed_event("América vs Tigres", "america-tigres", events) is events[0]

    duplicate = dict(events[0])
    duplicate["source_event_id"] = "duplicate-id"
    assert scraper._match_observed_event("América vs Tigres", None, events + [duplicate]) is None

    conflicting_revision = dict(events[0])
    events[0]["cuotas_por_resultado"] = {"home": "1.70"}
    conflicting_revision["cuotas_por_resultado"] = {"home": "9.99"}
    assert (
        scraper._match_observed_event(
            "América vs Tigres",
            "america-tigres",
            [events[0], conflicting_revision],
        )
        is None
    )


def test_ai_cannot_bind_price_by_matching_only_one_team(monkeypatch):
    from backend import scraper

    monkeypatch.setattr(scraper, "Groq", lambda **_kwargs: object())
    raw_picks = [
        {
            "partido": "América vs Pumas",
            "pick": "América Gana Directo",
            "cuota": "9.99",
            "horario": "Mañana 23:59",
            "es_parlay": False,
        }
        for _ in range(3)
    ]
    responses = iter(("quant", "audit", json.dumps(raw_picks)))
    monkeypatch.setattr(
        scraper,
        "ejecutar_groq_con_fallback",
        lambda *_args, **_kwargs: next(responses),
    )
    catalog = [
        {
            "source_event_id": "america-tigres",
            "bookmaker_key": "book-a",
            "categoria": "Liga MX",
            "partido": "América vs Tigres",
            "local": "América",
            "visitante": "Tigres",
            "horario": "Mañana 23:59",
            "cuotas_por_resultado": {"home": "1.70"},
            "info_texto": "",
        },
        {
            "source_event_id": "america-pumas",
            "bookmaker_key": "book-a",
            "categoria": "Liga MX",
            "partido": "América vs Pumas",
            "local": "América",
            "visitante": "Pumas",
            "horario": "Mañana 23:59",
            "cuotas_por_resultado": {"home": "2.25"},
            "info_texto": "",
        },
    ]

    picks = scraper.fase6_analisis_final(
        catalog, "", {}, catalog, groq_api_key="fake-key"
    )

    assert [pick["cuota"] for pick in picks] == ["2.25", "2.25", "2.25"]
    assert {pick["source_event_id"] for pick in picks} == {"america-pumas"}


@pytest.mark.parametrize(
    ("pick_text", "is_parlay"),
    [
        ("Más de 2.5 goles", False),
        ("América -1.5", False),
        ("Tigres tiros de esquina", False),
        ("América gana y Tigres gana", True),
        ("América gana o empata (1X)", False),
    ],
)
def test_ai_unrecognized_or_composite_markets_are_discarded(
    monkeypatch, pick_text, is_parlay
):
    raw = [{
        "partido": "América vs Tigres",
        "pick": pick_text,
        "cuota": "1.72",
        "horario": "Mañana 23:59",
        "razonamiento": "Datos suficientes para explicar la selección.",
        "es_parlay": is_parlay,
    }]

    picks = _run_legacy_ai(
        monkeypatch,
        raw,
        named_prices={"home": "1.72", "draw": "3.30", "away": "2.40"},
    )

    # The hallucinated selection is discarded. The legacy function may still
    # return its deterministic, source-backed home-moneyline fallback.
    assert all(pick["pick"] != pick_text for pick in picks)
    assert {pick["pick"] for pick in picks} <= {"América Gana Directo"}
    assert {pick["cuota"] for pick in picks} <= {"1.72"}


@pytest.mark.parametrize("invalid", [None, "bad", 0, 99])
def test_legacy_surface_fallback_does_not_turn_invalid_price_into_a_pick(
    monkeypatch, invalid
):
    from backend import scraper

    monkeypatch.setattr(scraper, "Groq", lambda **_kwargs: object())
    monkeypatch.setattr(
        scraper,
        "ejecutar_groq_con_fallback",
        lambda *_args, **_kwargs: "not-json",
    )
    event = {
        "categoria": "Liga MX",
        "partido": "América vs Tigres",
        "local": "América",
        "visitante": "Tigres",
        "horario": "Mañana 23:59",
        "cuotas_superficie": [invalid],
        "info_texto": "",
    }

    picks = scraper.fase6_analisis_final(
        [event], "", {}, [event], groq_api_key="fake-key"
    )

    assert picks == []


def test_legacy_fallback_uses_named_home_price_not_positional_surface_price(
    monkeypatch,
):
    from backend import scraper

    monkeypatch.setattr(scraper, "Groq", lambda **_kwargs: object())
    monkeypatch.setattr(
        scraper,
        "ejecutar_groq_con_fallback",
        lambda *_args, **_kwargs: "not-json",
    )
    event = {
        "categoria": "Liga MX",
        "partido": "América vs Tigres",
        "local": "América",
        "visitante": "Tigres",
        "horario": "Mañana 23:59",
        "cuotas_por_resultado": {"home": "1.20"},
        "cuotas_superficie": ["9.99"],
        "info_texto": "",
        "source_event_id": "event-123",
        "bookmaker_key": "book-a",
    }

    picks = scraper.fase6_analisis_final(
        [event], "", {}, [event], groq_api_key="fake-key"
    )

    assert picks[0]["cuota"] == "1.20"
    assert picks[0]["pick"] == "América Gana Directo"
    assert picks[0]["bookmaker_key"] == "book-a"
    assert "odds_mercado" not in picks[0]


def test_legacy_fallback_without_named_h2h_map_creates_no_moneyline_pick(
    monkeypatch,
):
    from backend import scraper

    monkeypatch.setattr(scraper, "Groq", lambda **_kwargs: object())
    monkeypatch.setattr(
        scraper,
        "ejecutar_groq_con_fallback",
        lambda *_args, **_kwargs: "not-json",
    )
    event = {
        "categoria": "Liga MX",
        "partido": "América vs Tigres",
        "local": "América",
        "visitante": "Tigres",
        "horario": "Mañana 23:59",
        "cuotas_superficie": ["1.20"],
        "info_texto": "",
    }

    picks = scraper.fase6_analisis_final(
        [event], "", {}, [event], groq_api_key="fake-key"
    )

    assert picks == []


def test_legacy_event_without_stable_source_id_is_never_publicable(monkeypatch):
    from backend import scraper

    monkeypatch.setattr(scraper, "Groq", lambda **_kwargs: object())
    monkeypatch.setattr(
        scraper,
        "ejecutar_groq_con_fallback",
        lambda *_args, **_kwargs: "not-json",
    )
    event = {
        "categoria": "Liga MX",
        "partido": "América vs Tigres",
        "local": "América",
        "visitante": "Tigres",
        "horario": "Mañana 23:59",
        "cuotas_por_resultado": {"home": "1.70"},
        "bookmaker_key": "playdoit",
        "info_texto": "",
    }

    picks = scraper.fase6_analisis_final(
        [event], "", {}, [event], groq_api_key="fake-key"
    )

    assert picks == []


def test_event_dedupe_uses_schedule_without_id_and_rejects_conflicting_quotes():
    from backend import scraper

    first = {
        "partido": "América vs Tigres",
        "local": " América ",
        "visitante": "Tigres",
        "horario": "Hoy • 20:00",
        "cuotas_superficie": ["1.70"],
    }
    later = {
        **first,
        "local": "américa",
        "horario": "Mañana • 20:00",
        "cuotas_superficie": ["1.80"],
    }

    assert scraper._deduplicate_event_records([first, later]) == [first, later]

    conflict = {**first, "cuotas_superficie": ["9.99"]}
    assert scraper._deduplicate_event_records([first, conflict, later]) == [later]


def test_surface_event_projection_preserves_available_source_and_bookmaker_ids():
    from backend import scraper

    raw = {
        "source_event_id": "playdoit-456",
        "bookmaker_key": "playdoit",
        "local": "América",
        "visitante": "Tigres",
        "cuotas": ["1.72", "3.25", "2.35"],
    }

    projected = scraper._surface_event_record(raw, "Liga MX", "Hoy • 20:00")

    assert projected["source_event_id"] == "playdoit-456"
    assert projected["bookmaker_key"] == "playdoit"


def test_legacy_fallback_does_not_publish_totals_parlays_or_unsupported_claims(
    monkeypatch,
):
    from backend import scraper

    monkeypatch.setattr(scraper, "Groq", lambda **_kwargs: object())
    monkeypatch.setattr(
        scraper,
        "ejecutar_groq_con_fallback",
        lambda *_args, **_kwargs: "not-json",
    )
    events = [
        {
            "source_event_id": f"event-{index}",
            "bookmaker_key": "book-a",
            "categoria": "Liga MX",
            "partido": f"Local {index} vs Visitante {index}",
            "local": f"Local {index}",
            "visitante": f"Visitante {index}",
            "horario": "Mañana 23:59",
            "cuotas_por_resultado": {"home": "1.70"},
            "mercados_profundos": "Más de 2.5 Goles @ 1.80",
            "info_texto": "Más de 9.5 Córners @ 1.75",
        }
        for index in range(2)
    ]

    picks = scraper.fase6_analisis_final(
        events, "", {}, events, groq_api_key="fake-key"
    )

    assert len(picks) == 2
    assert all(pick["pick"].endswith("Gana Directo") for pick in picks)
    assert all(not pick["es_parlay"] for pick in picks)
    assert all("confianza" not in pick and "tiene_valor" not in pick for pick in picks)
    assert {pick["source_event_id"] for pick in picks} == {"event-0", "event-1"}


def test_legacy_source_has_no_executable_price_defaults_or_derived_market_odds():
    text = SCRAPER.read_text(encoding="utf-8")
    forbidden = (
        'def normalizar_cuota_decimal(val, default=',
        "p.get('cuota', '1.85')",
        'raw_c if raw_c else "1.75"',
        "max(1.35, c_val)",
        "c_val - 0.05",
        "cuota_parlay - 0.10",
        '"odds_mercado": f',
        "cuotas_superficie[0]",
    )
    assert not [pattern for pattern in forbidden if pattern in text]
    assert '"cuotas_por_resultado": {}' in text
    # Playdoit now reaches legacy phases only through the normalized Event
    # projection; the positional surface adapter remains non-executable.
    assert "_surface_event_record(e, cat_real, horario_limpio)" not in text
    assert "normalize_playdoit_events(enriched, observed)" in text

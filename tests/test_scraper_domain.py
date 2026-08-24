from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import math

import pytest

from backend.scraper_domain import Event, Market, Outcome


NOW = datetime(2026, 8, 20, 18, tzinfo=timezone.utc)
LATER = datetime(2026, 8, 21, 2, tzinfo=timezone.utc)


def _outcome(key: str = "home", name: str = "América", price: float = 1.70) -> Outcome:
    return Outcome(key, name, price)


def _market(outcomes: tuple[Outcome, ...] | None = None) -> Market:
    return Market("h2h", "full_game", None, outcomes or (_outcome(),))


def _event(**overrides: object) -> Event:
    values: dict[str, object] = {
        "source": "playdoit",
        "source_event_id": "event-1",
        "sport": "soccer",
        "league": "Liga MX",
        "home_team": "América",
        "away_team": "Tigres",
        "starts_at": LATER,
        "observed_at": NOW,
        "markets": (_market(),),
    }
    values.update(overrides)
    return Event(**values)  # type: ignore[arg-type]


def test_market_looks_up_named_outcomes_without_using_position():
    market = Market(
        key=" H2H ",
        period=" FULL_GAME ",
        line=None,
        outcomes=(Outcome(" AWAY ", "Tigres", 2.40), Outcome(" HOME ", "América", 1.70)),
    )

    assert market.key == "h2h"
    assert market.period == "full_game"
    assert market.outcome(" HoMe ").price == 1.70


def test_market_preserves_optional_nonempty_bookmaker_identity():
    without_bookmaker = _market()
    with_bookmaker = Market(
        "h2h",
        "full_game",
        None,
        (_outcome(),),
        bookmaker_key=" Book-A ",
    )

    assert without_bookmaker.bookmaker_key is None
    assert with_bookmaker.bookmaker_key == "book-a"
    with pytest.raises(ValueError, match="bookmaker_key"):
        Market("h2h", "full_game", None, (_outcome(),), bookmaker_key="  ")


def test_market_preserves_official_display_and_source_identity():
    outcome = Outcome(
        "playdoit_odd:4132889965",
        "Más de 0.5 remates",
        1.75,
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
    assert market.sport_market_id == "70520"
    assert market.outcomes[0].source_id == "4132889965"


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("outcome", "source_id"),
        ("market", "name"),
        ("market", "source_id"),
        ("market", "sport_market_id"),
    ],
)
def test_official_metadata_rejects_blank_values_when_provided(
    target: str, field: str
):
    if target == "outcome":
        with pytest.raises(ValueError, match=field):
            Outcome("home", "América", 1.7, **{field: "  "})
        return

    values = {field: "  "}
    with pytest.raises(ValueError, match=field):
        Market("h2h", "full_game", None, (_outcome(),), **values)


def test_source_backed_outcome_accepts_official_high_decimal_price():
    outcome = Outcome(
        "playdoit_odd:longshot-1",
        "Marcador exacto 7-0",
        80.0,
        source_id="longshot-1",
    )

    assert outcome.price == 80.0
    with pytest.raises(ValueError, match="between 1.01 and 50"):
        Outcome("longshot", "Marcador exacto 7-0", 80.0)


def test_market_outcome_reports_the_missing_key_clearly():
    market = _market()

    with pytest.raises(KeyError, match="draw"):
        market.outcome("draw")


@pytest.mark.parametrize("price", [True, "1.70", math.nan, math.inf, -math.inf, 1.0, 50.01])
def test_outcome_rejects_invalid_decimal_prices(price: object):
    with pytest.raises((TypeError, ValueError), match="price"):
        Outcome("home", "América", price)  # type: ignore[arg-type]


def test_outcome_normalizes_numeric_price_to_float():
    outcome = Outcome("home", "América", 2)

    assert outcome.price == 2.0
    assert type(outcome.price) is float


@pytest.mark.parametrize("field", ["key", "name"])
def test_outcome_requires_nonempty_text_fields(field: str):
    values = {"key": "home", "name": "América", "price": 1.70}
    values[field] = "   "

    with pytest.raises(ValueError, match=field):
        Outcome(**values)  # type: ignore[arg-type]


def test_outcome_trims_canonical_text_fields():
    outcome = Outcome(" HOME ", " América ", 1.70)

    assert outcome.key == "home"
    assert outcome.name == "América"


@pytest.mark.parametrize("line", [True, "-1.5", math.nan, math.inf, -math.inf])
def test_market_rejects_invalid_lines(line: object):
    with pytest.raises((TypeError, ValueError), match="line"):
        Market("spread", "full_game", line, (_outcome(),))  # type: ignore[arg-type]


def test_market_accepts_negative_lines_without_artificial_bounds():
    market = Market(
        "spreads",
        "full_game",
        -12,
        (_outcome(), _outcome("away", "Tigres", 1.70)),
    )

    assert market.line == -12.0
    assert type(market.line) is float


@pytest.mark.parametrize(
    ("key", "outcomes"),
    [
        ("totals", (Outcome("over", "Más de 2.5", 1.90), Outcome("under", "Menos de 2.5", 1.90))),
        ("spreads", (Outcome("home", "América -0", 1.90), Outcome("away", "Tigres +0", 1.90))),
    ],
)
def test_canonical_line_markets_require_a_finite_line_but_allow_zero(
    key: str, outcomes: tuple[Outcome, ...]
):
    with pytest.raises(ValueError, match="line"):
        Market(key, "full_game", None, outcomes)

    assert Market(key.upper(), "full_game", 0, outcomes).line == 0.0


@pytest.mark.parametrize(
    ("key", "outcomes", "required"),
    [
        ("totals", (Outcome("over", "Más de 2.5", 1.90),), "over.*under"),
        ("spreads", (Outcome("home", "América -1.5", 1.90),), "home.*away"),
    ],
)
def test_canonical_line_markets_require_both_sides(
    key: str, outcomes: tuple[Outcome, ...], required: str
):
    with pytest.raises(ValueError, match=required):
        Market(key, "full_game", 2.5, outcomes)


def test_market_requires_a_nonempty_tuple_of_typed_unique_outcomes():
    with pytest.raises(ValueError, match="outcomes"):
        Market("h2h", "full_game", None, ())
    with pytest.raises(TypeError, match="tuple"):
        Market("h2h", "full_game", None, [_outcome()])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Outcome"):
        Market("h2h", "full_game", None, (object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        Market(
            "h2h",
            "full_game",
            None,
            (_outcome("home"), _outcome(" HOME ", "Club América")),
        )


@pytest.mark.parametrize("field", ["key", "period"])
def test_market_requires_nonempty_text_fields(field: str):
    values = {"key": "h2h", "period": "full_game", "line": None, "outcomes": (_outcome(),)}
    values[field] = "  "

    with pytest.raises(ValueError, match=field):
        Market(**values)  # type: ignore[arg-type]


def test_event_rejects_naive_or_non_future_start_times():
    naive = datetime(2026, 8, 21)

    with pytest.raises(ValueError, match="timezone-aware"):
        _event(starts_at=naive)
    with pytest.raises(ValueError, match="future"):
        _event(starts_at=NOW)


@pytest.mark.parametrize("field", ["starts_at", "observed_at"])
def test_event_rejects_non_datetime_timestamps(field: str):
    with pytest.raises(TypeError, match=field):
        _event(**{field: "2026-08-21T02:00:00Z"})


@pytest.mark.parametrize(
    "field",
    ["source", "source_event_id", "sport", "league", "home_team", "away_team"],
)
def test_event_requires_nonempty_identity_and_name_fields(field: str):
    with pytest.raises(ValueError, match=field):
        _event(**{field: "  "})


def test_event_trims_identity_and_name_fields_and_requires_distinct_teams():
    event = _event(source=" playdoit ", league=" Liga MX ", home_team=" América ")

    assert event.source == "playdoit"
    assert event.league == "Liga MX"
    assert event.home_team == "América"
    with pytest.raises(ValueError, match="distinct"):
        _event(home_team="América", away_team=" américa ")


def test_event_requires_a_tuple_of_markets_with_expected_types():
    assert _event(markets=()).markets == ()
    with pytest.raises(TypeError, match="tuple"):
        _event(markets=[_market()])
    with pytest.raises(TypeError, match="Market"):
        _event(markets=(object(),))


def test_domain_objects_and_their_collections_are_immutable():
    outcome = _outcome()
    market = _market((outcome,))
    event = _event(markets=(market,))

    with pytest.raises(FrozenInstanceError):
        outcome.price = 2.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        market.outcomes = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        event.markets = ()  # type: ignore[misc]
    assert isinstance(market.outcomes, tuple)
    assert isinstance(event.markets, tuple)

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.pick_selection import (
    CandidatePick,
    build_candidates,
    build_same_day_parlay,
)
from backend.scraper_domain import Event, Market, Outcome


MEXICO = ZoneInfo("America/Mexico_City")
OBSERVED = datetime(2026, 8, 20, 10, tzinfo=MEXICO)


def event_with(
    *,
    source: str = "playdoit",
    source_event_id: str = "event-2",
    starts_at: datetime | None = None,
    markets: tuple[Market, ...] | None = None,
    home_team: str = "Dodgers",
    away_team: str = "Padres",
) -> Event:
    return Event(
        source=source,
        source_event_id=source_event_id,
        sport="baseball",
        league="MLB",
        home_team=home_team,
        away_team=away_team,
        starts_at=starts_at or OBSERVED + timedelta(hours=10),
        observed_at=OBSERVED,
        markets=markets
        or (
            Market(
                "h2h",
                "full_game",
                None,
                (
                    Outcome("home", home_team, 1.82),
                    Outcome("away", away_team, 2.04),
                ),
                bookmaker_key="playdoit",
            ),
        ),
    )


def test_candidate_copies_exact_normalized_source_market_and_price(event_fixture):
    candidates = build_candidates([event_fixture])
    home = next(row for row in candidates if row.selection_key == "home")

    assert home.source == event_fixture.source
    assert home.source_event_id == event_fixture.source_event_id
    assert home.bookmaker_key == event_fixture.markets[0].bookmaker_key
    assert home.starts_at is event_fixture.starts_at
    assert home.observed_at is event_fixture.observed_at
    assert home.sport == event_fixture.sport
    assert home.league == event_fixture.league
    assert home.home_team == event_fixture.home_team
    assert home.away_team == event_fixture.away_team
    assert home.market_key == event_fixture.markets[0].key
    assert home.period == event_fixture.markets[0].period
    assert home.line == event_fixture.markets[0].line
    assert home.selection_key == event_fixture.markets[0].outcome("home").key
    assert home.selection_name == event_fixture.markets[0].outcome("home").name
    assert home.price == event_fixture.markets[0].outcome("home").price


def test_only_supported_full_game_markets_become_candidates(partial_market_event):
    unsupported = Market(
        "team_total",
        "full_game",
        3.5,
        (Outcome("over", "Dodgers más de 3.5", 1.91),),
        bookmaker_key="playdoit",
    )
    event = event_with(markets=(unsupported,))

    assert build_candidates([partial_market_event, event]) == []


def test_unsupported_outcome_keys_do_not_become_candidates():
    market = Market(
        "h2h",
        "full_game",
        None,
        (
            Outcome("home", "Dodgers", 1.82),
            Outcome("away", "Padres", 2.04),
            Outcome("double_chance", "Dodgers o empate", 1.20),
        ),
        bookmaker_key="playdoit",
    )

    assert [
        candidate.selection_key
        for candidate in build_candidates([event_with(markets=(market,))])
    ] == ["home", "away"]


def test_market_without_bookmaker_identity_is_not_a_candidate():
    market = Market(
        "h2h",
        "full_game",
        None,
        (Outcome("home", "Dodgers", 1.82), Outcome("away", "Padres", 2.04)),
    )

    assert build_candidates([event_with(markets=(market,))]) == []


def test_candidate_ids_do_not_collide_across_bookmakers_lines_or_selections():
    outcomes = (Outcome("over", "Más", 1.90), Outcome("under", "Menos", 1.92))
    event = event_with(
        markets=(
            Market("totals", "full_game", 2.5, outcomes, bookmaker_key="book:a"),
            Market("totals", "full_game", 2.5, outcomes, bookmaker_key="book"),
            Market("totals", "full_game", 3.5, outcomes, bookmaker_key="book:a"),
        )
    )

    candidates = build_candidates([event])

    assert len(candidates) == 6
    assert len({candidate.candidate_id for candidate in candidates}) == 6


def test_exact_duplicate_candidates_are_deduplicated():
    event = event_with()

    candidates = build_candidates([event, event])

    assert [candidate.selection_key for candidate in candidates] == ["home", "away"]


def test_conflicting_prices_for_same_candidate_identity_fail_closed():
    first = Market(
        "h2h",
        "full_game",
        None,
        (Outcome("home", "Dodgers", 1.82), Outcome("away", "Padres", 2.04)),
        bookmaker_key="playdoit",
    )
    conflicting = Market(
        "h2h",
        "full_game",
        None,
        (Outcome("home", "Dodgers", 9.99), Outcome("away", "Padres", 2.04)),
        bookmaker_key="playdoit",
    )

    candidates = build_candidates([event_with(markets=(first, conflicting))])

    assert [candidate.selection_key for candidate in candidates] == ["away"]
    assert candidates[0].price == 2.04


def test_same_price_with_conflicting_selection_name_fails_closed():
    first = Market(
        "h2h",
        "full_game",
        None,
        (Outcome("home", "Dodgers", 1.82), Outcome("away", "Padres", 2.04)),
        bookmaker_key="playdoit",
    )
    renamed = Market(
        "h2h",
        "full_game",
        None,
        (
            Outcome("home", "Los Angeles Dodgers", 1.82),
            Outcome("away", "Padres", 2.04),
        ),
        bookmaker_key="playdoit",
    )

    candidates = build_candidates([event_with(markets=(first, renamed))])

    assert [candidate.selection_key for candidate in candidates] == ["away"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("starts_at", OBSERVED + timedelta(hours=11)),
        ("observed_at", OBSERVED + timedelta(minutes=1)),
        ("sport", "softball"),
        ("league", "Liga distinta"),
        ("home_team", "Yankees"),
        ("away_team", "Mets"),
    ],
)
def test_same_identity_with_different_event_evidence_fails_closed(field, value):
    event = event_with()
    conflicting = replace(event, **{field: value})

    assert build_candidates([event, conflicting]) == []


def test_candidate_is_frozen_and_slotted(event_fixture):
    candidate = build_candidates([event_fixture])[0]

    with pytest.raises(FrozenInstanceError):
        candidate.price = 9.99  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        candidate.fabricated_field = "x"  # type: ignore[attr-defined]
    assert not hasattr(candidate, "__dict__")


def test_parlay_uses_mexico_calendar_date_across_utc_boundary():
    first = event_with(
        source_event_id="event-night",
        starts_at=datetime(2026, 8, 21, 5, 30, tzinfo=timezone.utc),
    )
    second = event_with(
        source_event_id="event-late",
        starts_at=datetime(2026, 8, 20, 23, 45, tzinfo=MEXICO),
        home_team="Yankees",
        away_team="Mets",
    )
    legs = [build_candidates([first])[0], build_candidates([second])[0]]

    assert build_same_day_parlay(legs) == tuple(legs)


def test_parlay_rejects_dates_that_differ_in_mexico():
    today = build_candidates([event_with(source_event_id="today")])[0]
    tomorrow = build_candidates(
        [
            event_with(
                source_event_id="tomorrow",
                starts_at=OBSERVED + timedelta(days=1, hours=10),
                home_team="Yankees",
                away_team="Mets",
            )
        ]
    )[0]

    assert build_same_day_parlay([today, tomorrow]) is None


def test_parlay_ignores_nonmatching_extra_candidates_and_finds_a_pair():
    extra = build_candidates(
        [event_with(source_event_id="extra", starts_at=OBSERVED + timedelta(hours=2))]
    )[0]
    first = build_candidates(
        [
            event_with(
                source_event_id="first",
                starts_at=OBSERVED + timedelta(days=1, hours=2),
                home_team="Yankees",
                away_team="Mets",
            )
        ]
    )[0]
    second = build_candidates(
        [
            event_with(
                source_event_id="second",
                starts_at=OBSERVED + timedelta(days=1, hours=3),
                home_team="Cubs",
                away_team="Reds",
            )
        ]
    )[0]

    assert build_same_day_parlay([extra, second, first]) == (first, second)


def test_parlay_returns_the_first_pair_in_stable_start_and_id_order():
    earlier = build_candidates(
        [event_with(source_event_id="z-event", starts_at=OBSERVED + timedelta(hours=8))]
    )[0]
    later = build_candidates(
        [
            event_with(
                source_event_id="a-event",
                starts_at=OBSERVED + timedelta(hours=9),
                home_team="Yankees",
                away_team="Mets",
            )
        ]
    )[0]

    assert build_same_day_parlay([later, earlier]) == (earlier, later)


def test_parlay_rejects_duplicate_candidate_or_correlated_event_legs():
    candidates = build_candidates([event_with()])

    assert build_same_day_parlay([candidates[0], candidates[0]]) is None
    assert build_same_day_parlay(candidates) is None


def test_event_identity_includes_source_when_source_event_ids_match():
    first = build_candidates(
        [event_with(source="playdoit", source_event_id="shared")]
    )[0]
    second = build_candidates(
        [
            event_with(
                source="the_odds_api",
                source_event_id="shared",
                home_team="Yankees",
                away_team="Mets",
            )
        ]
    )[0]

    assert build_same_day_parlay([first, second]) == (first, second)


def test_parlay_rejects_same_physical_event_observed_by_different_sources():
    starts_at = OBSERVED + timedelta(hours=8)
    playdoit = build_candidates(
        [
            event_with(
                source="playdoit",
                source_event_id="playdoit-123",
                starts_at=starts_at,
                home_team="Club América",
                away_team="Tigres UANL",
            )
        ]
    )[0]
    odds_api = build_candidates(
        [
            event_with(
                source="the_odds_api",
                source_event_id="odds-987",
                starts_at=starts_at.astimezone(timezone.utc),
                home_team="  CLUB  AME\u0301RICA  ",
                away_team="tigres uanl",
            )
        ]
    )[0]

    assert build_same_day_parlay([playdoit, odds_api]) is None


def test_physical_event_identity_preserves_exact_home_away_orientation():
    starts_at = OBSERVED + timedelta(hours=8)
    first = build_candidates(
        [
            event_with(
                source="playdoit",
                source_event_id="playdoit-123",
                starts_at=starts_at,
                home_team="Club América",
                away_team="Tigres UANL",
            )
        ]
    )[0]
    reversed_orientation = build_candidates(
        [
            event_with(
                source="the_odds_api",
                source_event_id="odds-987",
                starts_at=starts_at.astimezone(timezone.utc),
                home_team="Tigres UANL",
                away_team="Club América",
            )
        ]
    )[0]

    assert build_same_day_parlay([first, reversed_orientation]) == (
        first,
        reversed_orientation,
    )


def test_parlay_is_only_an_explicit_leg_bundle_without_synthesized_quote():
    first = build_candidates([event_with(source_event_id="event-a")])[0]
    second = build_candidates(
        [
            event_with(
                source_event_id="event-b",
                home_team="Yankees",
                away_team="Mets",
            )
        ]
    )[0]

    bundle = build_same_day_parlay([first, second])

    assert isinstance(bundle, tuple)
    assert bundle == (first, second)
    assert not hasattr(bundle, "price")


def test_candidate_type_rejects_an_id_that_does_not_match_its_evidence(event_fixture):
    candidate = build_candidates([event_fixture])[0]
    values = {
        field: getattr(candidate, field)
        for field in CandidatePick.__dataclass_fields__
    }
    values["candidate_id"] = "invented"

    with pytest.raises(ValueError, match="candidate_id"):
        CandidatePick(**values)

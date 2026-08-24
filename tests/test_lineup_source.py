from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.lineup_source import (
    ApiFootballClient,
    ApiFootballError,
    ConfirmedLineups,
    FixtureRef,
    InMemoryLineupStore,
    LineupResolver,
    PlayerRef,
    SupabaseLineupStore,
    TeamStartingXI,
)
from backend.scraper_domain import Event, Market, Outcome
from backend.pick_selection import build_candidates


NOW = datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


def fixture_payload():
    return {
        "errors": [],
        "response": [{
            "fixture": {
                "id": 991,
                "date": "2026-08-23T18:55:00+00:00",
                "status": {"short": "NS"},
            },
            "league": {"id": 39, "name": "Premier League"},
            "teams": {
                "home": {"id": 36, "name": "Fulham"},
                "away": {"id": 49, "name": "Chelsea"},
            },
        }],
    }


def lineup_payload(*, cole_starts=True, home_count=11, away_count=11):
    def players(prefix, count):
        return [
            {"player": {"id": index + 1, "name": f"{prefix} {index + 1}"}}
            for index in range(count)
        ]

    away = players("Chelsea Player", away_count)
    cole = {"player": {"id": 777, "name": "Cole Palmer"}}
    if cole_starts and away:
        away[0] = cole
    return {
        "errors": [],
        "response": [
            {
                "team": {"id": 36, "name": "Fulham"},
                "startXI": players("Fulham Player", home_count),
                "substitutes": [],
            },
            {
                "team": {"id": 49, "name": "Chelsea"},
                "startXI": away,
                "substitutes": [] if cole_starts else [cole],
            },
        ],
    }


def test_api_client_authenticates_and_caches_daily_fixture_discovery():
    calls = []

    def request(url, *, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        return FakeResponse(
            fixture_payload(),
            headers={
                "x-ratelimit-requests-remaining": "99",
                "x-ratelimit-remaining": "9",
            },
        )

    store = InMemoryLineupStore()
    client = ApiFootballClient(
        "secret-key",
        store=store,
        requester=request,
        clock=lambda: NOW,
    )

    first = client.fixtures_for_date(date(2026, 8, 23))
    second = client.fixtures_for_date(date(2026, 8, 23))

    assert first == second
    assert len(first) == 1
    assert first[0].fixture_id == "991"
    assert first[0].home_name == "Fulham"
    assert len(calls) == 1
    assert calls[0][0].endswith("/fixtures")
    assert calls[0][1] == {"date": "2026-08-23"}
    assert calls[0][2] == {"x-apisports-key": "secret-key"}
    assert store.requests_used(date(2026, 8, 23)) == 1


def test_api_client_accepts_only_two_complete_confirmed_starting_elevens():
    responses = [
        FakeResponse(lineup_payload()),
        FakeResponse(lineup_payload(home_count=10)),
    ]
    client = ApiFootballClient(
        "secret-key",
        store=InMemoryLineupStore(),
        requester=lambda *_args, **_kwargs: responses.pop(0),
        clock=lambda: NOW,
    )

    confirmed = client.confirmed_lineups("991")
    incomplete = client.confirmed_lineups("992")

    assert confirmed is not None
    assert len(confirmed.teams) == 2
    assert [len(team.starters) for team in confirmed.teams] == [11, 11]
    assert incomplete is None


def test_api_client_fails_closed_on_provider_errors_or_malformed_json():
    payloads = [
        {"errors": {"rateLimit": "blocked"}, "response": []},
        {"errors": [], "response": "not-a-list"},
    ]
    client = ApiFootballClient(
        "secret-key",
        store=InMemoryLineupStore(),
        requester=lambda *_args, **_kwargs: FakeResponse(payloads.pop(0)),
        clock=lambda: NOW,
    )

    with pytest.raises(ApiFootballError):
        client.fixtures_for_date(date(2026, 8, 23))
    with pytest.raises(ApiFootballError):
        client.fixtures_for_date(date(2026, 8, 24))


def test_daily_budget_never_authorizes_more_than_40_requests():
    store = InMemoryLineupStore(daily_limit=40)

    assert [store.claim_request(NOW) for _ in range(41)].count(True) == 40
    assert store.requests_used(NOW.date()) == 40
    assert store.claim_request(NOW + timedelta(days=1)) is True


def test_provider_remaining_header_stops_before_reserved_60_calls():
    store = InMemoryLineupStore(daily_limit=40, provider_reserve=60)
    assert store.claim_request(NOW) is True

    store.observe_provider_remaining(60)

    assert store.claim_request(NOW) is False


def test_provider_per_minute_header_pauses_additional_requests():
    store = InMemoryLineupStore()
    assert store.claim_request(NOW) is True

    store.observe_provider_minute_remaining(0)

    assert store.claim_request(NOW) is False


class FakeRpcExecution:
    def __init__(self, callback):
        self._callback = callback

    def execute(self):
        return type("Response", (), {"data": self._callback()})()


class FakeSupabase:
    def __init__(self):
        self.calls = []
        self.cache = {}

    def rpc(self, name, params):
        self.calls.append((name, params))

        def execute():
            if name == "claim_api_football_request":
                return True
            if name == "put_api_football_cache":
                self.cache[params["requested_cache_key"]] = params[
                    "requested_payload"
                ]
                return None
            if name == "get_api_football_cache":
                return self.cache.get(params["requested_cache_key"])
            raise AssertionError(name)

        return FakeRpcExecution(execute)


def test_supabase_store_claims_shared_budget_and_round_trips_typed_cache():
    database = FakeSupabase()
    store = SupabaseLineupStore(database, clock=lambda: NOW)
    fixture = exact_fixture()
    lineups = complete_lineups()

    assert store.claim_request(NOW) is True
    store.put_fixtures(NOW.date(), (fixture,))
    store.put_lineups(lineups)

    assert store.get_fixtures(NOW.date()) == (fixture,)
    assert store.get_lineups("991") == lineups
    assert database.calls[0] == (
        "claim_api_football_request",
        {
            "requested_quota_day": "2026-08-23",
            "requested_limit": 40,
        },
    )


def soccer_event(*, starts_at=None, lineup_confirmed=False):
    player_market = Market(
        "playdoit_market:shots-1",
        "source_unspecified",
        None,
        (
            Outcome(
                "playdoit_odd:shots-over",
                "Más de 0.5",
                1.8,
                source_id="shots-over",
                competitor_id="playdoit-player-7",
            ),
        ),
        bookmaker_key="playdoit",
        name="Remates a Puerta - Cole Palmer",
        source_id="shots-1",
        sport_market_id="shots",
        scope="player",
        participant_id="playdoit-player-7",
        offer_kind="standard",
        source_selection_ids=("shots-over",),
        lineup_confirmed=lineup_confirmed,
    )
    team_market = Market(
        "playdoit_market:corners-1",
        "first_half",
        None,
        (
            Outcome(
                "playdoit_odd:corners-over",
                "Más de 4.5",
                1.85,
                source_id="corners-over",
            ),
        ),
        bookmaker_key="playdoit",
        name="Total de córners de Chelsea",
        source_id="corners-1",
        scope="team_total",
        team_id="playdoit-chelsea",
        offer_kind="standard",
        source_selection_ids=("corners-over",),
    )
    return Event(
        source="playdoit",
        source_event_id="event-1",
        sport="soccer",
        league="Premier League",
        home_team="Fulham",
        away_team="Chelsea",
        starts_at=starts_at or NOW + timedelta(minutes=55),
        observed_at=NOW,
        markets=(player_market, team_market),
    )


class FakeLineupClient:
    def __init__(self, fixtures, lineups):
        self.fixtures = fixtures
        self.lineups = lineups
        self.fixture_calls = 0
        self.lineup_calls = 0

    def fixtures_for_date(self, _date):
        self.fixture_calls += 1
        return self.fixtures

    def confirmed_lineups(self, _fixture_id):
        self.lineup_calls += 1
        return self.lineups


def exact_fixture(*, fixture_id="991", home="Fulham", away="Chelsea"):
    return FixtureRef(
        fixture_id=fixture_id,
        starts_at=NOW + timedelta(minutes=55),
        league_id="39",
        league_name="Premier League",
        home_id="36",
        home_name=home,
        away_id="49",
        away_name=away,
    )


def complete_lineups(*, duplicate_cole=False, cole_is_substitute=False):
    home_players = tuple(
        PlayerRef(str(index), f"Fulham Player {index}")
        for index in range(1, 12)
    )
    away_players = [
        PlayerRef(str(index + 20), f"Chelsea Player {index}")
        for index in range(1, 12)
    ]
    if not cole_is_substitute:
        away_players[0] = PlayerRef("777", "Cole Palmer")
    if duplicate_cole:
        home_players = (
            PlayerRef("888", "Cole Palmer"),
            *home_players[1:],
        )
    return ConfirmedLineups(
        fixture_id="991",
        teams=(
            TeamStartingXI("36", "Fulham", home_players),
            TeamStartingXI("49", "Chelsea", tuple(away_players)),
        ),
    )


def test_resolver_confirms_only_exact_unambiguous_starting_player():
    client = FakeLineupClient((exact_fixture(),), complete_lineups())
    event = soccer_event()
    resolver = LineupResolver(client, clock=lambda: NOW)

    enriched = resolver.resolve(event)

    assert enriched.markets[0].lineup_confirmed is True
    assert enriched.markets[1] == event.markets[1]
    assert client.fixture_calls == 1
    assert client.lineup_calls == 1
    assert resolver.stats == {
        "events_checked": 1,
        "confirmed_markets": 1,
        "excluded_player_markets": 0,
        "requests_used": 0,
    }


@pytest.mark.parametrize(
    "fixtures,lineups",
    [
        ((exact_fixture(home="Fulham FC"),), complete_lineups()),
        ((exact_fixture(), exact_fixture(fixture_id="992")), complete_lineups()),
        ((exact_fixture(),), complete_lineups(duplicate_cole=True)),
        ((exact_fixture(),), complete_lineups(cole_is_substitute=True)),
        ((exact_fixture(),), None),
    ],
)
def test_resolver_fails_closed_on_fixture_or_player_ambiguity(fixtures, lineups):
    event = soccer_event()

    enriched = LineupResolver(
        FakeLineupClient(fixtures, lineups),
        clock=lambda: NOW,
    ).resolve(event)

    assert enriched == event
    assert enriched.markets[0].lineup_confirmed is False


def test_resolver_does_not_spend_calls_outside_lineup_windows_or_for_team_only():
    client = FakeLineupClient((exact_fixture(),), complete_lineups())
    distant = soccer_event(starts_at=NOW + timedelta(hours=4))
    team_only = replace(distant, markets=(distant.markets[1],))

    assert LineupResolver(client, clock=lambda: NOW).resolve(distant) == distant
    assert LineupResolver(client, clock=lambda: NOW).resolve(team_only) == team_only
    assert client.fixture_calls == 0
    assert client.lineup_calls == 0


def test_multi_player_market_enables_only_the_confirmed_starting_selection():
    base = soccer_event()
    multi_player = replace(
        base.markets[0],
        name="Jugador que anota",
        participant_id=None,
        outcomes=(
            Outcome(
                "playdoit_odd:starter",
                "Starter One",
                2.1,
                source_id="starter",
                competitor_id="starter-1",
            ),
            Outcome(
                "playdoit_odd:bench",
                "Bench Guy",
                3.2,
                source_id="bench",
                competitor_id="bench-1",
            ),
        ),
        source_selection_ids=("starter", "bench"),
    )
    event = replace(base, markets=(multi_player, base.markets[1]))
    lineups = complete_lineups()
    away = lineups.teams[1]
    away = replace(
        away,
        starters=(
            PlayerRef("901", "Starter One"),
            *away.starters[1:],
        ),
    )
    resolver = LineupResolver(
        FakeLineupClient(
            (exact_fixture(),),
            replace(lineups, teams=(lineups.teams[0], away)),
        ),
        clock=lambda: NOW,
    )

    enriched = resolver.resolve(event)
    candidates = build_candidates([enriched])

    assert [outcome.lineup_confirmed for outcome in enriched.markets[0].outcomes] == [
        True,
        False,
    ]
    assert [
        candidate.selection_name
        for candidate in candidates
        if candidate.source_market_id == "shots-1"
    ] == ["Starter One"]


def test_short_starter_name_does_not_match_inside_another_player_name():
    base = soccer_event()
    market = replace(
        base.markets[0],
        name="Jugador que anota",
        participant_id=None,
        outcomes=(Outcome(
            "playdoit_odd:leonardo",
            "Leonardo Silva",
            2.5,
            source_id="leonardo",
            competitor_id="leonardo-9",
        ),),
        source_selection_ids=("leonardo",),
    )
    event = replace(base, markets=(market,))
    lineups = complete_lineups()
    away = replace(
        lineups.teams[1],
        starters=(
            PlayerRef("902", "Leo"),
            *lineups.teams[1].starters[1:],
        ),
    )

    enriched = LineupResolver(
        FakeLineupClient(
            (exact_fixture(),),
            replace(lineups, teams=(lineups.teams[0], away)),
        ),
        clock=lambda: NOW,
    ).resolve(event)

    assert enriched.markets[0].outcomes[0].lineup_confirmed is False
    assert build_candidates([enriched]) == []

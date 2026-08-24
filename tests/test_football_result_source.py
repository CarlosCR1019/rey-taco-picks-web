from datetime import datetime, timezone

import pytest

from backend.football_result_source import (
    ApiFootballResultsClient,
    ApiFootballResultsError,
    InMemoryResultStore,
    SupabaseResultStore,
)


NOW = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload, *, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {
            "x-ratelimit-requests-remaining": "79",
            "x-ratelimit-remaining": "9",
        }

    def json(self):
        return self._payload


def fixtures_payload():
    return {
        "errors": [],
        "response": [
            {
                "fixture": {
                    "id": 991,
                    "date": "2026-08-24T01:00:00+00:00",
                    "status": {"short": "FT"},
                },
                "teams": {
                    "home": {"id": 36, "name": "Fulham"},
                    "away": {"id": 49, "name": "Chelsea"},
                },
                "score": {
                    "halftime": {"home": 0, "away": 1},
                    "fulltime": {"home": 1, "away": 2},
                },
            },
            {
                "fixture": {
                    "id": 992,
                    "date": "2026-08-24T03:00:00+00:00",
                    "status": {"short": "NS"},
                },
                "teams": {
                    "home": {"id": 1, "name": "Future"},
                    "away": {"id": 2, "name": "Later"},
                },
                "score": {
                    "halftime": {"home": None, "away": None},
                    "fulltime": {"home": None, "away": None},
                },
            },
        ],
    }


def statistics_payload():
    def team(team_id, name, corners, shots_on):
        return {
            "team": {"id": team_id, "name": name},
            "statistics": [
                {"type": "Corner Kicks", "value": corners},
                {"type": "Shots on Goal", "value": shots_on},
                {"type": "Total Shots", "value": shots_on + 3},
                {"type": "Fouls", "value": 8},
                {"type": "Offsides", "value": 2},
                {"type": "Yellow Cards", "value": 1},
                {"type": "Red Cards", "value": 0},
            ],
        }

    return {"errors": [], "response": [team(36, "Fulham", 3, 2), team(49, "Chelsea", 6, 7)]}


def players_payload():
    return {
        "errors": [],
        "response": [
            {"team": {"id": 36, "name": "Fulham"}, "players": []},
            {
                "team": {"id": 49, "name": "Chelsea"},
                "players": [
                    {
                        "player": {"id": 777, "name": "Cole Palmer"},
                        "statistics": [
                            {
                                "games": {"minutes": 90},
                                "shots": {"total": 4, "on": 2},
                                "goals": {"total": 1, "assists": 0},
                                "cards": {"yellow": 0, "red": 0},
                            }
                        ],
                    }
                ],
            },
        ],
    }


def deep_pick(**overrides):
    row = {
        "partido": "Fulham vs Chelsea",
        "fecha_evento": "2026-08-23",
        "mercado": "Total de tiros de esquina",
        "pick": "Más de 8.5",
        "source_market_key": (
            'market:v1:["playdoit","playdoit_market:corners-1",'
            '"source_unspecified",null,"corners-1",'
            '{"scope":"event","participant_id":null,"team_id":null,'
            '"competitor_id":null,"offer_kind":"standard",'
            '"lineup_confirmed":false}]'
        ),
    }
    row.update(overrides)
    return row


def test_result_client_fetches_only_completed_fixtures_and_needed_details():
    calls = []
    responses = [fixtures_payload(), statistics_payload(), players_payload()]

    def request(url, *, params, headers, timeout):
        calls.append((url, params, headers, timeout))
        return FakeResponse(responses.pop(0))

    client = ApiFootballResultsClient(
        "secret",
        store=InMemoryResultStore(),
        requester=request,
        clock=lambda: NOW,
    )
    results = client.results_for_picks([
        deep_pick(),
        deep_pick(
            mercado="Remates a puerta - Cole Palmer",
            pick="Más de 1.5",
        ),
    ])

    assert len(results) == 1
    result = results[0]
    assert result["source"] == "api_football"
    assert result["source_id"] == "991"
    assert result["event_date"] == "2026-08-23"
    assert result["home_corners"] == 3.0
    assert result["away_shots_on"] == 7.0
    assert result["players"][0]["name"] == "Cole Palmer"
    assert result["players"][0]["goals"] == 1.0
    assert [call[0].rsplit("/", 1)[-1] for call in calls] == [
        "fixtures",
        "statistics",
        "players",
    ]
    assert calls[0][1] == {
        "date": "2026-08-23",
        "timezone": "America/Mexico_City",
    }
    assert calls[1][1] == {"fixture": "991"}
    assert calls[0][2] == {"x-apisports-key": "secret"}


def test_canonical_picks_do_not_spend_detailed_statistics_calls():
    calls = []

    def request(url, *, params, headers, timeout):
        calls.append((url, params))
        return FakeResponse(fixtures_payload())

    client = ApiFootballResultsClient(
        "secret",
        store=InMemoryResultStore(),
        requester=request,
        clock=lambda: NOW,
    )
    results = client.results_for_picks([
        deep_pick(
            mercado="Resultado final",
            pick="Chelsea",
            source_market_key='market:v1:["playdoit","h2h","full_game",null]',
        )
    ])

    assert len(results) == 1
    assert len(calls) == 1


def test_result_client_cache_avoids_duplicate_provider_calls():
    calls = []
    responses = [fixtures_payload(), statistics_payload(), players_payload()]

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse(responses.pop(0))

    client = ApiFootballResultsClient(
        "secret",
        store=InMemoryResultStore(),
        requester=request,
        clock=lambda: NOW,
    )

    assert client.results_for_picks([deep_pick()]) == client.results_for_picks([deep_pick()])
    assert len(calls) == 3


def test_corrupt_cached_fixture_is_rejected_and_refetched():
    store = InMemoryResultStore()
    corrupt = {
        "source": "api_football",
        "source_id": "991",
        "home_team": "Fulham",
        "away_team": "Chelsea",
        "event_date": "2026-08-23",
        "completed": True,
        "scores": [{"score": "not-a-score"}, {"score": 2}],
        "home_first_half_score": 0,
        "away_first_half_score": 1,
        "_home_id": "36",
        "_away_id": "49",
        "_detail_safe": True,
    }
    store.put("results:fixtures:2026-08-23", {"rows": [corrupt]}, final=True)
    calls = []

    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse(fixtures_payload())

    results = ApiFootballResultsClient(
        "secret",
        store=store,
        requester=request,
        clock=lambda: NOW,
    ).results_for_picks([
        deep_pick(
            source_market_key='market:v1:["playdoit","h2h","full_game",null]'
        )
    ])

    assert len(results) == 1
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse({"errors": {"limit": "reached"}, "response": []}),
        FakeResponse({"errors": [], "response": "invalid"}),
        FakeResponse({"errors": [], "response": []}, status_code=500),
    ],
)
def test_result_client_fails_closed_on_provider_errors(response):
    client = ApiFootballResultsClient(
        "secret",
        store=InMemoryResultStore(),
        requester=lambda *_args, **_kwargs: response,
        clock=lambda: NOW,
    )

    with pytest.raises(ApiFootballResultsError):
        client.results_for_picks([deep_pick()])


class FakeExecution:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return type("Response", (), {"data": self.value})()


class FakeDatabase:
    def __init__(self):
        self.calls = []
        self.cache = {}

    def rpc(self, name, params):
        self.calls.append((name, params))
        if name == "claim_api_football_request":
            return FakeExecution(True)
        if name == "get_api_football_cache":
            return FakeExecution(self.cache.get(params["requested_cache_key"]))
        if name == "put_api_football_cache":
            self.cache[params["requested_cache_key"]] = params["requested_payload"]
            return FakeExecution(None)
        raise AssertionError(name)


def test_supabase_result_store_shares_eighty_call_budget_and_cache():
    database = FakeDatabase()
    store = SupabaseResultStore(database, clock=lambda: NOW)

    assert store.claim_request(NOW) is True
    store.put("results:test", {"ok": True}, final=True)
    assert store.get("results:test") == {"ok": True}
    assert database.calls[0] == (
        "claim_api_football_request",
        {"requested_quota_day": "2026-08-24", "requested_limit": 80},
    )

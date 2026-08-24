"""Bounded API-Football result enrichment for source-audited pending picks."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
import math
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

import requests

from backend.results_domain import (
    EventResult,
    match_event,
    parse_market_identity,
)


API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
RESULT_DAILY_REQUEST_LIMIT = 80
RESULT_PROVIDER_RESERVE = 20
MAX_RESULT_DATES = 7
MAX_DETAILED_FIXTURES = 6
MEXICO_CITY = ZoneInfo("America/Mexico_City")
_FINAL_STATUSES = frozenset({"FT", "AET", "PEN"})


class ApiFootballResultsError(RuntimeError):
    """Raised when final result evidence cannot be obtained safely."""


def _required_text(value: object, field: str, *, maximum: int = 2048) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} is invalid")
    return normalized


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        normalized = value.strip().removesuffix("%")
        if not normalized:
            return None
        value = normalized
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


class InMemoryResultStore:
    """Deterministic quota/cache store for tests and local dry runs."""

    def __init__(self, *, daily_limit: int = RESULT_DAILY_REQUEST_LIMIT) -> None:
        if not isinstance(daily_limit, int) or not 1 <= daily_limit <= 80:
            raise ValueError("daily_limit must be between 1 and 80")
        self._daily_limit = daily_limit
        self._counts: dict[date, int] = {}
        self._cache: dict[str, object] = {}
        self._lock = Lock()

    def claim_request(self, now: datetime) -> bool:
        quota_day = _aware_datetime(now, "now").astimezone(timezone.utc).date()
        with self._lock:
            used = self._counts.get(quota_day, 0)
            if used >= self._daily_limit:
                return False
            self._counts[quota_day] = used + 1
            return True

    def get(self, cache_key: str) -> object | None:
        with self._lock:
            return self._cache.get(cache_key)

    def put(self, cache_key: str, payload: object, *, final: bool) -> None:
        if type(final) is not bool:
            raise TypeError("final must be boolean")
        with self._lock:
            self._cache[cache_key] = payload


class SupabaseResultStore:
    """Service-role result cache sharing one provider budget with lineups."""

    def __init__(
        self,
        client: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if client is None or not callable(getattr(client, "rpc", None)):
            raise TypeError("client must provide rpc")
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def claim_request(self, now: datetime) -> bool:
        observed = _aware_datetime(now, "now").astimezone(timezone.utc)
        try:
            response = self._client.rpc(
                "claim_api_football_request",
                {
                    "requested_quota_day": observed.date().isoformat(),
                    "requested_limit": RESULT_DAILY_REQUEST_LIMIT,
                },
            ).execute()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return False
        return getattr(response, "data", None) is True

    def get(self, cache_key: str) -> object | None:
        normalized = _required_text(cache_key, "cache_key", maximum=200)
        try:
            response = self._client.rpc(
                "get_api_football_cache",
                {"requested_cache_key": normalized},
            ).execute()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return None
        return getattr(response, "data", None)

    def put(self, cache_key: str, payload: object, *, final: bool) -> None:
        normalized = _required_text(cache_key, "cache_key", maximum=200)
        if type(final) is not bool:
            raise TypeError("final must be boolean")
        now = _aware_datetime(self._clock(), "clock").astimezone(timezone.utc)
        expires_at = now + (timedelta(days=30) if final else timedelta(minutes=20))
        try:
            self._client.rpc(
                "put_api_football_cache",
                {
                    "requested_cache_key": normalized,
                    "requested_payload": payload,
                    "requested_expires_at": expires_at.isoformat(),
                },
            ).execute()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return


class ApiFootballResultsClient:
    """Fetch final fixtures and detail only for pending source-backed picks."""

    def __init__(
        self,
        api_key: str,
        *,
        store: Any,
        requester: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = _required_text(api_key, "api_key", maximum=8192)
        if not all(callable(getattr(store, method, None)) for method in ("claim_request", "get", "put")):
            raise TypeError("store must provide claim_request, get, and put")
        self._store = store
        self._requester = requester or requests.get
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or not 0 < float(timeout) <= 30
        ):
            raise ValueError("timeout must be between 0 and 30 seconds")
        self._timeout = float(timeout)
        self._provider_remaining: int | None = None
        self._provider_minute_remaining: int | None = None

    def _get(self, path: str, params: Mapping[str, str]) -> list[Any]:
        now = _aware_datetime(self._clock(), "clock")
        if (
            self._provider_remaining is not None
            and self._provider_remaining <= RESULT_PROVIDER_RESERVE
        ) or self._provider_minute_remaining == 0:
            raise ApiFootballResultsError("result request reserve reached")
        if self._store.claim_request(now) is not True:
            raise ApiFootballResultsError("result request budget exhausted")
        try:
            response = self._requester(
                f"{API_FOOTBALL_BASE_URL}{path}",
                params=dict(params),
                headers={"x-apisports-key": self._api_key},
                timeout=self._timeout,
            )
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise ApiFootballResultsError("result provider request failed") from exc

        headers = getattr(response, "headers", {})
        if isinstance(headers, Mapping):
            try:
                self._provider_remaining = int(
                    headers.get("x-ratelimit-requests-remaining")
                )
            except (TypeError, ValueError):
                pass
            try:
                self._provider_minute_remaining = int(
                    headers.get("x-ratelimit-remaining")
                )
            except (TypeError, ValueError):
                pass
        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int) or not 200 <= status_code < 300:
            raise ApiFootballResultsError("result provider returned non-success")
        try:
            payload = response.json()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise ApiFootballResultsError("result provider returned invalid JSON") from exc
        if not isinstance(payload, Mapping) or payload.get("errors") not in (None, [], {}):
            raise ApiFootballResultsError("result provider reported an error")
        records = payload.get("response")
        if not isinstance(records, list):
            raise ApiFootballResultsError("result provider response must be a list")
        return records

    @staticmethod
    def _parse_fixture(raw: object) -> dict[str, object] | None:
        if not isinstance(raw, Mapping):
            return None
        fixture = raw.get("fixture")
        teams = raw.get("teams")
        score = raw.get("score")
        if not all(isinstance(item, Mapping) for item in (fixture, teams, score)):
            return None
        status = fixture.get("status")
        home = teams.get("home")
        away = teams.get("away")
        fulltime = score.get("fulltime")
        halftime = score.get("halftime")
        if (
            not isinstance(status, Mapping)
            or status.get("short") not in _FINAL_STATUSES
            or not all(isinstance(item, Mapping) for item in (home, away, fulltime))
        ):
            return None
        home_score = _number(fulltime.get("home"))
        away_score = _number(fulltime.get("away"))
        if home_score is None or away_score is None:
            return None
        try:
            starts_at = datetime.fromisoformat(
                _required_text(fixture.get("date"), "fixture date").replace("Z", "+00:00")
            )
            starts_at = _aware_datetime(starts_at, "fixture date")
            fixture_id = _required_text(str(fixture.get("id") or ""), "fixture id")
            home_id = _required_text(str(home.get("id") or ""), "home id")
            away_id = _required_text(str(away.get("id") or ""), "away id")
            home_name = _required_text(home.get("name"), "home name")
            away_name = _required_text(away.get("name"), "away name")
        except (TypeError, ValueError, OverflowError):
            return None
        return {
            "source": "api_football",
            "source_id": fixture_id,
            "home_team": home_name,
            "away_team": away_name,
            "event_date": starts_at.astimezone(MEXICO_CITY).date().isoformat(),
            "completed": True,
            "scores": [
                {"name": home_name, "score": home_score},
                {"name": away_name, "score": away_score},
            ],
            "home_first_half_score": (
                _number(halftime.get("home")) if isinstance(halftime, Mapping) else None
            ),
            "away_first_half_score": (
                _number(halftime.get("away")) if isinstance(halftime, Mapping) else None
            ),
            "_home_id": home_id,
            "_away_id": away_id,
            "_detail_safe": status.get("short") == "FT",
        }

    def _fixtures_for_date(self, fixture_date: str) -> list[dict[str, object]]:
        cache_key = f"results:fixtures:{fixture_date}"
        cached = self._store.get(cache_key)
        if isinstance(cached, Mapping) and isinstance(cached.get("rows"), list):
            parsed = [self._validated_cached_fixture(row) for row in cached["rows"]]
            if all(row is not None for row in parsed):
                return [row for row in parsed if row is not None]
        records = self._get(
            "/fixtures",
            {
                "date": fixture_date,
                "timezone": "America/Mexico_City",
            },
        )
        rows = [row for row in (self._parse_fixture(item) for item in records) if row]
        # A date can contain an early final plus later unfinished fixtures.
        # Keep the daily index short-lived; only per-fixture final detail is
        # immutable enough for the long cache.
        self._store.put(cache_key, {"rows": rows}, final=False)
        return rows

    @staticmethod
    def _validated_cached_fixture(raw: object) -> dict[str, object] | None:
        if not isinstance(raw, Mapping):
            return None
        required = {
            "source", "source_id", "home_team", "away_team", "event_date",
            "completed", "scores", "home_first_half_score",
            "away_first_half_score", "_home_id", "_away_id", "_detail_safe",
        }
        if set(raw) != required or raw.get("source") != "api_football":
            return None
        if type(raw.get("completed")) is not bool or type(raw.get("_detail_safe")) is not bool:
            return None
        if not isinstance(raw.get("scores"), list) or len(raw["scores"]) != 2:
            return None
        try:
            if any(
                not isinstance(raw.get(field), str)
                or not str(raw[field]).strip()
                for field in (
                    "source_id", "home_team", "away_team", "event_date",
                    "_home_id", "_away_id",
                )
            ):
                return None
            if date.fromisoformat(str(raw["event_date"])).isoformat() != raw["event_date"]:
                return None
            for score in raw["scores"]:
                if (
                    not isinstance(score, Mapping)
                    or set(score) != {"name", "score"}
                    or not isinstance(score.get("name"), str)
                    or not score["name"].strip()
                    or _number(score.get("score")) is None
                ):
                    return None
            for field in ("home_first_half_score", "away_first_half_score"):
                if raw.get(field) is not None and _number(raw.get(field)) is None:
                    return None
        except (TypeError, ValueError):
            return None
        return dict(raw)

    @staticmethod
    def _stats(records: Sequence[object], fixture: Mapping[str, object]) -> dict[str, float]:
        by_team: dict[str, dict[str, float]] = {}
        aliases = {
            "Corner Kicks": "corners",
            "Shots on Goal": "shots_on",
            "Total Shots": "shots_total",
            "Fouls": "fouls",
            "Offsides": "offsides",
            "Yellow Cards": "yellow_cards",
            "Red Cards": "red_cards",
        }
        for raw in records:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("team"), Mapping):
                continue
            team_id = str(raw["team"].get("id") or "")
            statistics = raw.get("statistics")
            if team_id not in {fixture["_home_id"], fixture["_away_id"]} or not isinstance(statistics, list):
                continue
            parsed: dict[str, float] = {}
            for statistic in statistics:
                if not isinstance(statistic, Mapping):
                    continue
                key = aliases.get(statistic.get("type"))
                value = _number(statistic.get("value"))
                if key is not None and value is not None:
                    parsed[key] = value
            by_team[team_id] = parsed
        result: dict[str, float] = {}
        for side, team_key in (("home", "_home_id"), ("away", "_away_id")):
            for key, value in by_team.get(str(fixture[team_key]), {}).items():
                result[f"{side}_{key}"] = value
        return result

    @staticmethod
    def _players(records: Sequence[object], fixture: Mapping[str, object]) -> list[dict[str, object]]:
        allowed_ids = {str(fixture["_home_id"]), str(fixture["_away_id"])}
        players: list[dict[str, object]] = []
        for raw_team in records:
            if not isinstance(raw_team, Mapping) or not isinstance(raw_team.get("team"), Mapping):
                continue
            team_id = str(raw_team["team"].get("id") or "")
            team_name = raw_team["team"].get("name")
            raw_players = raw_team.get("players")
            if team_id not in allowed_ids or not isinstance(team_name, str) or not isinstance(raw_players, list):
                continue
            for raw_player in raw_players:
                if not isinstance(raw_player, Mapping) or not isinstance(raw_player.get("player"), Mapping):
                    continue
                statistics = raw_player.get("statistics")
                if not isinstance(statistics, list) or len(statistics) != 1 or not isinstance(statistics[0], Mapping):
                    continue
                player = raw_player["player"]
                name = player.get("name")
                if not isinstance(name, str) or not name.strip():
                    continue
                row = statistics[0]
                games = row.get("games") if isinstance(row.get("games"), Mapping) else {}
                shots = row.get("shots") if isinstance(row.get("shots"), Mapping) else {}
                goals = row.get("goals") if isinstance(row.get("goals"), Mapping) else {}
                cards = row.get("cards") if isinstance(row.get("cards"), Mapping) else {}
                players.append({
                    "name": name.strip(),
                    "team": team_name.strip(),
                    "minutes": _number(games.get("minutes")),
                    "shots_total": _number(shots.get("total")),
                    "shots_on": _number(shots.get("on")),
                    "goals": _number(goals.get("total")),
                    "assists": _number(goals.get("assists")),
                    "yellow_cards": _number(cards.get("yellow")),
                    "red_cards": _number(cards.get("red")),
                })
        return players

    def _detail(self, fixture: Mapping[str, object]) -> dict[str, object]:
        fixture_id = str(fixture["source_id"])
        cache_key = f"results:detail:{fixture_id}"
        cached = self._store.get(cache_key)
        if isinstance(cached, Mapping) and set(cached) == {"stats", "players"}:
            if isinstance(cached["stats"], Mapping) and isinstance(cached["players"], list):
                return {**dict(cached["stats"]), "players": list(cached["players"])}
        statistics = self._get("/fixtures/statistics", {"fixture": fixture_id})
        raw_players = self._get("/fixtures/players", {"fixture": fixture_id})
        stats = self._stats(statistics, fixture)
        players = self._players(raw_players, fixture)
        self._store.put(
            cache_key,
            {"stats": stats, "players": players},
            final=bool(stats or players),
        )
        return {**stats, "players": players}

    @staticmethod
    def _pick_date(pick: Mapping[str, object]) -> str | None:
        raw = pick.get("fecha_evento") or pick.get("fecha_generacion")
        if not isinstance(raw, str):
            return None
        normalized = raw.strip()[:10]
        try:
            return date.fromisoformat(normalized).isoformat()
        except ValueError:
            return None

    @staticmethod
    def _needs_detail(pick: Mapping[str, object]) -> bool:
        identity = parse_market_identity(pick.get("source_market_key"))
        return bool(identity is not None and identity.market_key.startswith("playdoit_market:"))

    @staticmethod
    def _event(fixture: Mapping[str, object]) -> EventResult:
        scores = fixture["scores"]
        return EventResult(
            str(fixture["home_team"]),
            str(fixture["away_team"]),
            float(scores[0]["score"]),
            float(scores[1]["score"]),
            True,
            source="api_football",
            source_id=str(fixture["source_id"]),
            event_date=str(fixture["event_date"]),
        )

    def results_for_picks(
        self, picks: Sequence[Mapping[str, object]]
    ) -> list[dict[str, object]]:
        if not isinstance(picks, Sequence) or isinstance(picks, (str, bytes)):
            raise TypeError("picks must be a sequence")
        dates = sorted(
            {value for pick in picks if (value := self._pick_date(pick))},
            reverse=True,
        )[:MAX_RESULT_DATES]
        if not dates:
            return []
        fixtures = [row for day in dates for row in self._fixtures_for_date(day)]
        detailed_ids: set[str] = set()
        for pick in picks:
            expected_date = self._pick_date(pick)
            if not self._needs_detail(pick) or expected_date is None:
                continue
            label = str(pick.get("partido", ""))
            matches = [
                fixture for fixture in fixtures
                if fixture["event_date"] == expected_date
                and match_event(label, self._event(fixture))
            ]
            if len(matches) == 1 and matches[0].get("_detail_safe") is True:
                detailed_ids.add(str(matches[0]["source_id"]))
        if len(detailed_ids) > MAX_DETAILED_FIXTURES:
            detailed_ids = set(sorted(detailed_ids)[:MAX_DETAILED_FIXTURES])

        results = []
        for fixture in fixtures:
            public = {key: value for key, value in fixture.items() if not key.startswith("_")}
            if str(fixture["source_id"]) in detailed_ids:
                try:
                    public.update(self._detail(fixture))
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    pass
            results.append(public)
        return results

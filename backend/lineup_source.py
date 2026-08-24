"""Strict API-Football boundary for confirmed soccer starting elevens."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import math
from threading import Lock
from typing import Any, Callable, Mapping
import unicodedata

import requests

from backend.scraper_domain import Event, Market


API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
LINEUP_DAILY_REQUEST_LIMIT = 40
LINEUP_PROVIDER_RESERVE = 60
LINEUP_MIN_MINUTES = 15
LINEUP_MAX_MINUTES = 70
FIXTURE_KICKOFF_TOLERANCE_MINUTES = 10


class ApiFootballError(RuntimeError):
    """Raised when lineup evidence cannot be obtained safely."""


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _normalized_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.category(character).startswith("M")
    )
    return " ".join(
        "".join(
            character if character.isalnum() else " "
            for character in without_marks.casefold()
        ).split()
    )


@dataclass(frozen=True, slots=True)
class FixtureRef:
    fixture_id: str
    starts_at: datetime
    league_id: str
    league_name: str
    home_id: str
    home_name: str
    away_id: str
    away_name: str

    def __post_init__(self) -> None:
        for field in (
            "fixture_id",
            "league_id",
            "league_name",
            "home_id",
            "home_name",
            "away_id",
            "away_name",
        ):
            object.__setattr__(
                self, field, _required_text(getattr(self, field), field)
            )
        object.__setattr__(
            self, "starts_at", _aware_datetime(self.starts_at, "starts_at")
        )
        if self.home_id == self.away_id:
            raise ValueError("fixture teams must be distinct")


@dataclass(frozen=True, slots=True)
class PlayerRef:
    player_id: str
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "player_id", _required_text(self.player_id, "player_id")
        )
        object.__setattr__(self, "name", _required_text(self.name, "name"))


@dataclass(frozen=True, slots=True)
class TeamStartingXI:
    team_id: str
    team_name: str
    starters: tuple[PlayerRef, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "team_id", _required_text(self.team_id, "team_id")
        )
        object.__setattr__(
            self, "team_name", _required_text(self.team_name, "team_name")
        )
        if not isinstance(self.starters, tuple):
            raise TypeError("starters must be a tuple")
        if len(self.starters) != 11 or not all(
            isinstance(player, PlayerRef) for player in self.starters
        ):
            raise ValueError("a confirmed starting eleven requires 11 players")
        player_ids = [player.player_id for player in self.starters]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("starter player IDs must be unique per team")


@dataclass(frozen=True, slots=True)
class ConfirmedLineups:
    fixture_id: str
    teams: tuple[TeamStartingXI, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fixture_id", _required_text(self.fixture_id, "fixture_id")
        )
        if (
            not isinstance(self.teams, tuple)
            or len(self.teams) != 2
            or not all(isinstance(team, TeamStartingXI) for team in self.teams)
        ):
            raise ValueError("confirmed lineups require exactly two teams")
        team_ids = [team.team_id for team in self.teams]
        if len(team_ids) != len(set(team_ids)):
            raise ValueError("lineup teams must be distinct")


class InMemoryLineupStore:
    """Thread-safe cache and quota implementation used by dry runs/tests."""

    def __init__(
        self,
        *,
        daily_limit: int = LINEUP_DAILY_REQUEST_LIMIT,
        provider_reserve: int = LINEUP_PROVIDER_RESERVE,
    ) -> None:
        if not isinstance(daily_limit, int) or not 1 <= daily_limit <= 100:
            raise ValueError("daily_limit must be between 1 and 100")
        if not isinstance(provider_reserve, int) or provider_reserve < 0:
            raise ValueError("provider_reserve must be nonnegative")
        self._daily_limit = daily_limit
        self._provider_reserve = provider_reserve
        self._counts: dict[date, int] = {}
        self._provider_remaining: int | None = None
        self._provider_minute_remaining: int | None = None
        self._fixtures: dict[date, tuple[FixtureRef, ...]] = {}
        self._lineups: dict[str, ConfirmedLineups] = {}
        self._lock = Lock()

    def claim_request(self, now: datetime) -> bool:
        observed = _aware_datetime(now, "now").astimezone(timezone.utc)
        quota_day = observed.date()
        with self._lock:
            if (
                self._provider_remaining is not None
                and self._provider_remaining <= self._provider_reserve
            ):
                return False
            if self._provider_minute_remaining == 0:
                return False
            used = self._counts.get(quota_day, 0)
            if used >= self._daily_limit:
                return False
            self._counts[quota_day] = used + 1
            return True

    def observe_provider_remaining(self, remaining: int | None) -> None:
        if remaining is None:
            return
        if not isinstance(remaining, int) or remaining < 0:
            return
        with self._lock:
            if self._provider_remaining is None:
                self._provider_remaining = remaining
            else:
                self._provider_remaining = min(
                    self._provider_remaining, remaining
                )

    def observe_provider_minute_remaining(self, remaining: int | None) -> None:
        if not isinstance(remaining, int) or remaining < 0:
            return
        with self._lock:
            self._provider_minute_remaining = remaining

    def requests_used(self, quota_day: date) -> int:
        with self._lock:
            return self._counts.get(quota_day, 0)

    def get_fixtures(self, fixture_date: date) -> tuple[FixtureRef, ...] | None:
        with self._lock:
            return self._fixtures.get(fixture_date)

    def put_fixtures(
        self, fixture_date: date, fixtures: tuple[FixtureRef, ...]
    ) -> None:
        with self._lock:
            self._fixtures[fixture_date] = fixtures

    def get_lineups(self, fixture_id: str) -> ConfirmedLineups | None:
        with self._lock:
            return self._lineups.get(fixture_id)

    def put_lineups(self, lineups: ConfirmedLineups) -> None:
        with self._lock:
            self._lineups[lineups.fixture_id] = lineups


def _fixture_payload(fixture: FixtureRef) -> dict[str, str]:
    return {
        "fixture_id": fixture.fixture_id,
        "starts_at": fixture.starts_at.isoformat(),
        "league_id": fixture.league_id,
        "league_name": fixture.league_name,
        "home_id": fixture.home_id,
        "home_name": fixture.home_name,
        "away_id": fixture.away_id,
        "away_name": fixture.away_name,
    }


def _fixture_from_payload(raw: object) -> FixtureRef:
    if not isinstance(raw, Mapping):
        raise TypeError("fixture cache entry must be an object")
    return FixtureRef(
        fixture_id=_required_text(raw.get("fixture_id"), "fixture_id"),
        starts_at=datetime.fromisoformat(
            _required_text(raw.get("starts_at"), "starts_at")
        ),
        league_id=_required_text(raw.get("league_id"), "league_id"),
        league_name=_required_text(raw.get("league_name"), "league_name"),
        home_id=_required_text(raw.get("home_id"), "home_id"),
        home_name=_required_text(raw.get("home_name"), "home_name"),
        away_id=_required_text(raw.get("away_id"), "away_id"),
        away_name=_required_text(raw.get("away_name"), "away_name"),
    )


def _lineups_payload(lineups: ConfirmedLineups) -> dict[str, object]:
    return {
        "fixture_id": lineups.fixture_id,
        "teams": [
            {
                "team_id": team.team_id,
                "team_name": team.team_name,
                "starters": [
                    {
                        "player_id": player.player_id,
                        "name": player.name,
                    }
                    for player in team.starters
                ],
            }
            for team in lineups.teams
        ],
    }


def _lineups_from_payload(raw: object) -> ConfirmedLineups:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("teams"), list):
        raise TypeError("lineup cache entry must be an object")
    teams = []
    for raw_team in raw["teams"]:
        if not isinstance(raw_team, Mapping) or not isinstance(
            raw_team.get("starters"), list
        ):
            raise TypeError("lineup team cache entry must be an object")
        starters = tuple(
            PlayerRef(
                _required_text(player.get("player_id"), "player_id"),
                _required_text(player.get("name"), "player name"),
            )
            for player in raw_team["starters"]
            if isinstance(player, Mapping)
        )
        teams.append(TeamStartingXI(
            _required_text(raw_team.get("team_id"), "team_id"),
            _required_text(raw_team.get("team_name"), "team_name"),
            starters,
        ))
    return ConfirmedLineups(
        _required_text(raw.get("fixture_id"), "fixture_id"), tuple(teams)
    )


class SupabaseLineupStore:
    """Shared service-role cache and atomic request budget for both PCs."""

    def __init__(
        self,
        client: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        daily_limit: int = LINEUP_DAILY_REQUEST_LIMIT,
        provider_reserve: int = LINEUP_PROVIDER_RESERVE,
    ) -> None:
        if client is None or not callable(getattr(client, "rpc", None)):
            raise TypeError("client must provide rpc")
        if not isinstance(daily_limit, int) or not 1 <= daily_limit <= 40:
            raise ValueError("daily_limit must be between 1 and 40")
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._daily_limit = daily_limit
        self._provider_reserve = provider_reserve
        self._provider_remaining: int | None = None
        self._provider_minute_remaining: int | None = None

    def claim_request(self, now: datetime) -> bool:
        observed = _aware_datetime(now, "now").astimezone(timezone.utc)
        if (
            self._provider_remaining is not None
            and self._provider_remaining <= self._provider_reserve
        ):
            return False
        if self._provider_minute_remaining == 0:
            return False
        try:
            response = self._client.rpc(
                "claim_api_football_request",
                {
                    "requested_quota_day": observed.date().isoformat(),
                    "requested_limit": self._daily_limit,
                },
            ).execute()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return False
        return getattr(response, "data", None) is True

    def observe_provider_remaining(self, remaining: int | None) -> None:
        if not isinstance(remaining, int) or remaining < 0:
            return
        if self._provider_remaining is None:
            self._provider_remaining = remaining
        else:
            self._provider_remaining = min(
                self._provider_remaining, remaining
            )

    def observe_provider_minute_remaining(self, remaining: int | None) -> None:
        if isinstance(remaining, int) and remaining >= 0:
            self._provider_minute_remaining = remaining

    def _get_cache(self, cache_key: str) -> object | None:
        try:
            response = self._client.rpc(
                "get_api_football_cache",
                {"requested_cache_key": cache_key},
            ).execute()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return None
        return getattr(response, "data", None)

    def _put_cache(
        self, cache_key: str, payload: object, expires_at: datetime
    ) -> None:
        try:
            self._client.rpc(
                "put_api_football_cache",
                {
                    "requested_cache_key": cache_key,
                    "requested_payload": payload,
                    "requested_expires_at": expires_at.isoformat(),
                },
            ).execute()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return

    def get_fixtures(self, fixture_date: date) -> tuple[FixtureRef, ...] | None:
        payload = self._get_cache(f"fixtures:{fixture_date.isoformat()}")
        if payload is None:
            return None
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("fixtures"), list
        ):
            return None
        try:
            return tuple(
                _fixture_from_payload(item) for item in payload["fixtures"]
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    def put_fixtures(
        self, fixture_date: date, fixtures: tuple[FixtureRef, ...]
    ) -> None:
        expires_at = datetime.combine(
            fixture_date + timedelta(days=1),
            time(hour=2),
            tzinfo=timezone.utc,
        )
        now = _aware_datetime(self._clock(), "clock").astimezone(timezone.utc)
        if expires_at <= now:
            expires_at = now + timedelta(hours=2)
        self._put_cache(
            f"fixtures:{fixture_date.isoformat()}",
            {"fixtures": [_fixture_payload(item) for item in fixtures]},
            expires_at,
        )

    def get_lineups(self, fixture_id: str) -> ConfirmedLineups | None:
        payload = self._get_cache(f"lineups:{fixture_id}")
        if payload is None:
            return None
        try:
            return _lineups_from_payload(payload)
        except (KeyError, TypeError, ValueError, OverflowError):
            return None

    def put_lineups(self, lineups: ConfirmedLineups) -> None:
        now = _aware_datetime(self._clock(), "clock").astimezone(timezone.utc)
        self._put_cache(
            f"lineups:{lineups.fixture_id}",
            _lineups_payload(lineups),
            now + timedelta(hours=6),
        )


class ApiFootballClient:
    """Fetch and validate only exact fixtures and confirmed starting elevens."""

    def __init__(
        self,
        api_key: str,
        *,
        store: Any,
        requester: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = _required_text(api_key, "api_key")
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
        self._lineup_attempted: set[str] = set()
        self._requests_used = 0

    @property
    def requests_used(self) -> int:
        return self._requests_used

    def _get(self, path: str, params: Mapping[str, str]) -> list[Any]:
        now = _aware_datetime(self._clock(), "clock")
        if self._store.claim_request(now) is not True:
            raise ApiFootballError("lineup request budget exhausted")
        self._requests_used += 1
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
            raise ApiFootballError("API-Football request failed") from exc

        headers = getattr(response, "headers", {})
        remaining_value = (
            headers.get("x-ratelimit-requests-remaining")
            if isinstance(headers, Mapping)
            else None
        )
        try:
            remaining = int(remaining_value)
        except (TypeError, ValueError):
            remaining = None
        self._store.observe_provider_remaining(remaining)
        minute_value = (
            headers.get("x-ratelimit-remaining")
            if isinstance(headers, Mapping)
            else None
        )
        try:
            minute_remaining = int(minute_value)
        except (TypeError, ValueError):
            minute_remaining = None
        self._store.observe_provider_minute_remaining(minute_remaining)

        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int) or not 200 <= status_code < 300:
            raise ApiFootballError("API-Football returned a non-success status")
        try:
            payload = response.json()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            raise ApiFootballError("API-Football returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise ApiFootballError("API-Football payload must be an object")
        errors = payload.get("errors")
        if errors not in (None, [], {}):
            raise ApiFootballError("API-Football reported an error")
        records = payload.get("response")
        if not isinstance(records, list):
            raise ApiFootballError("API-Football response must be a list")
        return records

    def fixtures_for_date(self, fixture_date: date) -> tuple[FixtureRef, ...]:
        if not isinstance(fixture_date, date):
            raise TypeError("fixture_date must be a date")
        cached = self._store.get_fixtures(fixture_date)
        if cached is not None:
            return cached
        raw_records = self._get(
            "/fixtures", {"date": fixture_date.isoformat()}
        )
        fixtures: list[FixtureRef] = []
        for raw in raw_records:
            try:
                parsed = self._parse_fixture(raw)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if parsed is not None:
                fixtures.append(parsed)
        result = tuple(fixtures)
        self._store.put_fixtures(fixture_date, result)
        return result

    @staticmethod
    def _parse_fixture(raw: object) -> FixtureRef | None:
        if not isinstance(raw, Mapping):
            return None
        fixture = raw.get("fixture")
        league = raw.get("league")
        teams = raw.get("teams")
        if not all(isinstance(item, Mapping) for item in (fixture, league, teams)):
            return None
        status = fixture.get("status")
        if not isinstance(status, Mapping) or status.get("short") != "NS":
            return None
        home = teams.get("home")
        away = teams.get("away")
        if not isinstance(home, Mapping) or not isinstance(away, Mapping):
            return None
        starts_at = datetime.fromisoformat(
            _required_text(fixture.get("date"), "fixture date").replace(
                "Z", "+00:00"
            )
        )
        return FixtureRef(
            fixture_id=_required_text(
                str(fixture.get("id") or ""), "fixture id"
            ),
            starts_at=starts_at,
            league_id=_required_text(
                str(league.get("id") or ""), "league id"
            ),
            league_name=_required_text(league.get("name"), "league name"),
            home_id=_required_text(str(home.get("id") or ""), "home id"),
            home_name=_required_text(home.get("name"), "home name"),
            away_id=_required_text(str(away.get("id") or ""), "away id"),
            away_name=_required_text(away.get("name"), "away name"),
        )

    def confirmed_lineups(self, fixture_id: str) -> ConfirmedLineups | None:
        normalized_fixture_id = _required_text(fixture_id, "fixture_id")
        cached = self._store.get_lineups(normalized_fixture_id)
        if cached is not None:
            return cached
        if normalized_fixture_id in self._lineup_attempted:
            return None
        self._lineup_attempted.add(normalized_fixture_id)
        records = self._get(
            "/fixtures/lineups", {"fixture": normalized_fixture_id}
        )
        if len(records) != 2:
            return None
        teams: list[TeamStartingXI] = []
        try:
            for raw in records:
                if not isinstance(raw, Mapping):
                    return None
                raw_team = raw.get("team")
                start_xi = raw.get("startXI")
                if not isinstance(raw_team, Mapping) or not isinstance(start_xi, list):
                    return None
                players: list[PlayerRef] = []
                for raw_player in start_xi:
                    if not isinstance(raw_player, Mapping):
                        return None
                    player = raw_player.get("player")
                    if not isinstance(player, Mapping):
                        return None
                    players.append(PlayerRef(
                        _required_text(
                            str(player.get("id") or ""), "player id"
                        ),
                        _required_text(player.get("name"), "player name"),
                    ))
                teams.append(TeamStartingXI(
                    _required_text(
                        str(raw_team.get("id") or ""), "team id"
                    ),
                    _required_text(raw_team.get("name"), "team name"),
                    tuple(players),
                ))
            confirmed = ConfirmedLineups(
                normalized_fixture_id, tuple(teams)
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        self._store.put_lineups(confirmed)
        return confirmed


def _is_soccer(event: Event) -> bool:
    return _normalized_name(event.sport) in {"soccer", "football", "futbol"}


def _is_player_market(market: Market) -> bool:
    if market.participant_id is not None:
        return True
    if market.scope is not None and market.scope.casefold() in {
        "player",
        "participant",
        "player_prop",
    }:
        return True
    return (
        market.scope is not None
        and market.scope.casefold() == "source_unspecified"
        and market.team_id is None
        and (
            market.competitor_id is not None
            or any(
                outcome.competitor_id is not None
                for outcome in market.outcomes
            )
        )
    )


class LineupResolver:
    """Copy an event with only exactly confirmed player markets enabled."""

    def __init__(
        self,
        client: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._events_checked: set[str] = set()
        self._confirmed_markets: set[tuple[str, str]] = set()
        self._excluded_markets: set[tuple[str, str]] = set()

    @property
    def stats(self) -> dict[str, int]:
        requests_used = getattr(self._client, "requests_used", 0)
        if isinstance(requests_used, bool) or not isinstance(requests_used, int):
            requests_used = 0
        return {
            "events_checked": len(self._events_checked),
            "confirmed_markets": len(self._confirmed_markets),
            "excluded_player_markets": len(self._excluded_markets),
            "requests_used": requests_used,
        }

    def resolve(self, event: Event) -> Event:
        if not isinstance(event, Event) or not _is_soccer(event):
            return event
        all_player_indexes = [
            index
            for index, market in enumerate(event.markets)
            if _is_player_market(market)
        ]
        for index in all_player_indexes:
            market = event.markets[index]
            identity = (
                event.source_event_id,
                market.source_id or market.key,
            )
            if market.lineup_confirmed:
                self._confirmed_markets.add(identity)
                self._excluded_markets.discard(identity)
            else:
                self._excluded_markets.add(identity)
        player_indexes = [
            index
            for index in all_player_indexes
            if not event.markets[index].lineup_confirmed
        ]
        if not player_indexes:
            return event
        now = _aware_datetime(self._clock(), "clock")
        minutes = (
            event.starts_at.astimezone(timezone.utc)
            - now.astimezone(timezone.utc)
        ).total_seconds() / 60
        if not LINEUP_MIN_MINUTES <= minutes <= LINEUP_MAX_MINUTES:
            return event
        self._events_checked.add(event.source_event_id)
        try:
            fixtures = self._client.fixtures_for_date(
                event.starts_at.astimezone(timezone.utc).date()
            )
            matches = [
                fixture
                for fixture in fixtures
                if self._fixture_matches(event, fixture)
            ]
            if len(matches) != 1:
                return event
            fixture = matches[0]
            lineups = self._client.confirmed_lineups(fixture.fixture_id)
            if (
                not isinstance(lineups, ConfirmedLineups)
                or lineups.fixture_id != fixture.fixture_id
                or {team.team_id for team in lineups.teams}
                != {fixture.home_id, fixture.away_id}
            ):
                return event
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return event

        markets = list(event.markets)
        changed = False
        for index in player_indexes:
            market = markets[index]
            resolved_outcomes = []
            for outcome in market.outcomes:
                player_matches = self._matching_starters_for_outcome(
                    market, outcome.name, lineups
                )
                resolved_outcomes.append(replace(
                    outcome,
                    lineup_confirmed=(
                        outcome.lineup_confirmed
                        or len(player_matches) == 1
                    ),
                ))
            market_confirmed = all(
                outcome.lineup_confirmed for outcome in resolved_outcomes
            )
            if any(
                outcome.lineup_confirmed for outcome in resolved_outcomes
            ):
                markets[index] = replace(
                    market,
                    outcomes=tuple(resolved_outcomes),
                    lineup_confirmed=market_confirmed,
                )
                identity = (
                    event.source_event_id,
                    markets[index].source_id or markets[index].key,
                )
                self._confirmed_markets.add(identity)
                self._excluded_markets.discard(identity)
                changed = True
        return replace(event, markets=tuple(markets)) if changed else event

    @staticmethod
    def _fixture_matches(event: Event, fixture: FixtureRef) -> bool:
        if (
            _normalized_name(event.home_team)
            != _normalized_name(fixture.home_name)
            or _normalized_name(event.away_team)
            != _normalized_name(fixture.away_name)
            or _normalized_name(event.league)
            != _normalized_name(fixture.league_name)
        ):
            return False
        kickoff_difference = abs(
            (
                event.starts_at.astimezone(timezone.utc)
                - fixture.starts_at.astimezone(timezone.utc)
            ).total_seconds()
        )
        return kickoff_difference <= FIXTURE_KICKOFF_TOLERANCE_MINUTES * 60

    @staticmethod
    def _matching_starters_for_outcome(
        market: Market,
        outcome_name: str,
        lineups: ConfirmedLineups,
    ) -> list[PlayerRef]:
        evidence = _normalized_name(" ".join([
            market.name or "",
            outcome_name,
        ]))
        if not evidence:
            return []
        matches = []
        for team in lineups.teams:
            for player in team.starters:
                normalized_player = _normalized_name(player.name)
                if (
                    normalized_player
                    and f" {normalized_player} " in f" {evidence} "
                ):
                    matches.append(player)
        return matches

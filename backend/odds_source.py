"""Strict The Odds API boundary and normalized market adapter.

The provider response is untrusted input.  A market is accepted only when all
of the fields needed to identify its selections and observed prices are
present; incomplete markets are omitted rather than repaired with defaults.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
import json
import math
from numbers import Real
from typing import Any
from urllib.parse import urlencode
import urllib.request

from backend.scraper_domain import Event, Market, Outcome


ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
SUPPORTED_SPORT_KEYS = (
    "soccer_uefa_champs_league_qualification",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_conmebol_copa_libertadores",
    "soccer_mexico_ligamx",
    "baseball_mlb",
    "soccer_spain_la_liga",
    "soccer_epl",
    "soccer_usa_mls",
    "americanfootball_nfl",
)
SUPPORTED_MARKETS = ("h2h", "totals", "spreads")
SPREAD_POINT_TOLERANCE = 1e-6
MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class OddsSourceError(RuntimeError):
    """A provider-boundary failure whose message is safe to log."""


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _raw_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be finite")
    return normalized


def _named_key(name: str, home: str, away: str) -> str | None:
    normalized = name.strip().casefold()
    if normalized == home.casefold():
        return "home"
    if normalized == away.casefold():
        return "away"
    if normalized in {"draw", "empate"}:
        return "draw"
    return None


def _raw_outcomes(raw: Mapping[str, object]) -> list[Mapping[str, object]]:
    outcomes = raw.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        raise ValueError("market outcomes must be a non-empty list")
    if not all(isinstance(outcome, Mapping) for outcome in outcomes):
        raise TypeError("market outcomes must contain objects")
    return outcomes


def _normalize_h2h(
    raw: Mapping[str, object],
    home: str,
    away: str,
    sport_key: str,
    bookmaker_key: str,
) -> Market:
    by_key: dict[str, Outcome] = {}
    for row in _raw_outcomes(raw):
        name = _required_text(row.get("name"), "outcome name")
        key = _named_key(name, home, away)
        if key is None or key in by_key:
            raise ValueError("h2h contains an unknown or duplicate selection")
        by_key[key] = Outcome(key, name, _raw_number(row.get("price"), "price"))

    expected = (
        {"home", "draw", "away"}
        if sport_key.casefold().startswith("soccer_")
        else {"home", "away"}
    )
    if set(by_key) != expected:
        raise ValueError("h2h selections do not match the sport format")
    order = ("home", "draw", "away") if "draw" in expected else ("home", "away")
    outcomes = tuple(by_key[key] for key in order)
    return Market("h2h", "full_game", None, outcomes, bookmaker_key)


def _normalize_totals(raw: Mapping[str, object], bookmaker_key: str) -> Market:
    by_key: dict[str, Outcome] = {}
    points: dict[str, float] = {}
    for row in _raw_outcomes(raw):
        name = _required_text(row.get("name"), "outcome name")
        key = name.casefold()
        if key not in {"over", "under"} or key in by_key:
            raise ValueError("totals contains an unknown or duplicate selection")
        points[key] = _raw_number(row.get("point"), "point")
        by_key[key] = Outcome(key, name, _raw_number(row.get("price"), "price"))

    if set(by_key) != {"over", "under"}:
        raise ValueError("totals must contain over and under")
    if not math.isclose(
        points["over"], points["under"], rel_tol=0.0, abs_tol=1e-9
    ):
        raise ValueError("totals points must share one line")
    return Market(
        "totals",
        "full_game",
        points["over"],
        (by_key["over"], by_key["under"]),
        bookmaker_key,
    )


def _normalize_spreads(
    raw: Mapping[str, object], home: str, away: str, bookmaker_key: str
) -> Market:
    by_key: dict[str, Outcome] = {}
    points: dict[str, float] = {}
    for row in _raw_outcomes(raw):
        name = _required_text(row.get("name"), "outcome name")
        key = _named_key(name, home, away)
        if key not in {"home", "away"} or key in by_key:
            raise ValueError("spreads contains an unknown or duplicate selection")
        points[key] = _raw_number(row.get("point"), "point")
        by_key[key] = Outcome(key, name, _raw_number(row.get("price"), "price"))

    if set(by_key) != {"home", "away"}:
        raise ValueError("spreads must contain home and away")
    if not math.isclose(
        points["home"],
        -points["away"],
        rel_tol=0.0,
        abs_tol=SPREAD_POINT_TOLERANCE,
    ):
        raise ValueError("spread points must be opposing")
    return Market(
        "spreads",
        "full_game",
        points["home"],
        (by_key["home"], by_key["away"]),
        bookmaker_key,
    )


def _normalize_market(
    raw: Mapping[str, object],
    home: str,
    away: str,
    sport_key: str,
    bookmaker_key: str,
) -> Market | None:
    key = raw.get("key")
    if not isinstance(key, str):
        return None
    try:
        if key.casefold() == "h2h":
            return _normalize_h2h(raw, home, away, sport_key, bookmaker_key)
        if key.casefold() == "totals":
            return _normalize_totals(raw, bookmaker_key)
        if key.casefold() == "spreads":
            return _normalize_spreads(raw, home, away, bookmaker_key)
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return None


def _market_signature(market: Market) -> tuple[object, ...]:
    return (
        market.key,
        market.bookmaker_key,
        market.period,
        market.line,
        tuple((outcome.key, outcome.price) for outcome in market.outcomes),
    )


def normalize_odds_event(raw: dict[str, Any], observed_at: datetime) -> Event:
    """Normalize one event while rejecting invalid event identity or time.

    Market-level provider defects are isolated by omitting the entire affected
    market.  Event-level defects intentionally propagate to the caller because
    silently accepting an event without stable identity would break auditing.
    """

    home = _required_text(raw["home_team"], "home_team")
    away = _required_text(raw["away_team"], "away_team")
    sport_key = _required_text(raw["sport_key"], "sport_key")

    markets: list[Market] = []
    seen: set[tuple[object, ...]] = set()
    bookmakers = raw.get("bookmakers", [])
    if isinstance(bookmakers, list):
        for bookmaker in bookmakers:
            if not isinstance(bookmaker, Mapping):
                continue
            try:
                bookmaker_key = _required_text(bookmaker.get("key"), "bookmaker key")
            except (TypeError, ValueError):
                continue
            raw_markets = bookmaker.get("markets", [])
            if not isinstance(raw_markets, list):
                continue
            for raw_market in raw_markets:
                if not isinstance(raw_market, Mapping):
                    continue
                market = _normalize_market(
                    raw_market, home, away, sport_key, bookmaker_key
                )
                if market is None:
                    continue
                signature = _market_signature(market)
                if signature not in seen:
                    seen.add(signature)
                    markets.append(market)

    commence_time = _required_text(raw["commence_time"], "commence_time")
    starts_at = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
    return Event(
        source="the_odds_api",
        source_event_id=raw["id"],
        sport=sport_key,
        league=raw["sport_title"],
        home_team=home,
        away_team=away,
        starts_at=starts_at,
        observed_at=observed_at,
        markets=tuple(markets),
    )


def build_odds_url(
    sport_key: str,
    api_key: str,
    *,
    regions: Sequence[str] = ("us", "eu"),
    markets: Sequence[str] = SUPPORTED_MARKETS,
) -> str:
    """Build a provider URL with an encoded query and explicit decimal odds."""

    if sport_key not in SUPPORTED_SPORT_KEYS:
        raise ValueError("sport_key must be a concrete configured sport")
    secret = _required_text(api_key, "api_key")
    normalized_regions = tuple(_required_text(item, "region") for item in regions)
    normalized_markets = tuple(_required_text(item, "market") for item in markets)
    if not normalized_regions:
        raise ValueError("at least one region is required")
    if not normalized_markets or not set(normalized_markets).issubset(SUPPORTED_MARKETS):
        raise ValueError("markets must be configured supported markets")

    query = urlencode(
        {
            "apiKey": secret,
            "regions": ",".join(normalized_regions),
            "markets": ",".join(normalized_markets),
            "oddsFormat": "decimal",
        }
    )
    return f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds/?{query}"


def fetch_odds_events(
    api_key: str,
    sport_key: str,
    *,
    regions: Sequence[str] = ("us", "eu"),
    markets: Sequence[str] = SUPPORTED_MARKETS,
    timeout: float = 10.0,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> list[dict[str, Any]]:
    """Fetch a raw provider array without exposing provider response secrets."""

    url = build_odds_url(
        sport_key,
        api_key,
        regions=regions,
        markets=markets,
    )
    request = urllib.request.Request(url, headers={"User-Agent": "rey-taco-picks/1"})
    if (
        isinstance(max_response_bytes, bool)
        or not isinstance(max_response_bytes, int)
        or max_response_bytes <= 0
    ):
        raise ValueError("max_response_bytes must be a positive integer")
    try:
        with opener(request, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None and callable(getattr(response, "getcode", None)):
                status = response.getcode()
            if (
                isinstance(status, bool)
                or not isinstance(status, int)
                or not 200 <= status < 300
            ):
                raise OddsSourceError("The Odds API returned a non-2xx HTTP status")
            body = response.read(max_response_bytes + 1)
            if not isinstance(body, bytes):
                raise OddsSourceError("The Odds API response body must be bytes")
            if len(body) > max_response_bytes:
                raise OddsSourceError("The Odds API response body exceeds the configured limit")
            payload = json.loads(body.decode("utf-8"))
    except (KeyboardInterrupt, SystemExit):
        raise
    except OddsSourceError:
        raise
    except Exception as exc:
        raise OddsSourceError(
            f"The Odds API request failed; failure={type(exc).__name__}"
        ) from None

    if not isinstance(payload, list):
        raise OddsSourceError("The Odds API response must be a JSON list")
    if not all(isinstance(row, dict) for row in payload):
        raise OddsSourceError("The Odds API JSON list must contain objects")
    return payload

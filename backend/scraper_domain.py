"""Immutable normalized sportsbook market objects.

These types form the validation boundary between untrusted source adapters and
the rest of the pick-selection pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import math
from numbers import Real
from typing import NoReturn


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _canonical_key(value: object, field: str) -> str:
    return _required_text(value, field).casefold()


def _finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be finite")
    return normalized


def _raise_timestamp_error(field: str, reason: str) -> NoReturn:
    raise ValueError(f"{field} must be a timezone-aware datetime with a valid offset: {reason}")


def _validate_aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None:
        _raise_timestamp_error(field, "timezone is missing")
    try:
        offset = value.utcoffset()
    except (OverflowError, TypeError, ValueError) as exc:
        _raise_timestamp_error(field, str(exc))
    if offset is None:
        _raise_timestamp_error(field, "UTC offset is missing")
    return value


@dataclass(frozen=True, slots=True)
class Outcome:
    """A named quote whose key is whitespace-trimmed and case-insensitive."""

    key: str
    name: str
    price: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _canonical_key(self.key, "key"))
        object.__setattr__(self, "name", _required_text(self.name, "name"))
        price = _finite_float(self.price, "price")
        if not 1.01 <= price <= 50.0:
            raise ValueError("price must be decimal odds between 1.01 and 50")
        object.__setattr__(self, "price", price)


@dataclass(frozen=True, slots=True)
class Market:
    """A canonical market and its observed outcomes.

    ``totals`` uses ``line`` as the shared over/under threshold and must carry
    at least ``over`` and ``under`` outcomes. ``spreads`` uses ``line`` as the
    home handicap; adapters validate that the away handicap is its arithmetic
    negation, and the market must carry at least ``home`` and ``away``. A zero
    line is valid for both. Other market keys may omit a line.
    """

    key: str
    period: str
    line: float | None
    outcomes: tuple[Outcome, ...]
    bookmaker_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _canonical_key(self.key, "key"))
        object.__setattr__(self, "period", _canonical_key(self.period, "period"))
        if self.bookmaker_key is not None:
            object.__setattr__(
                self,
                "bookmaker_key",
                _canonical_key(self.bookmaker_key, "bookmaker_key"),
            )
        if self.line is not None:
            object.__setattr__(self, "line", _finite_float(self.line, "line"))
        if not isinstance(self.outcomes, tuple):
            raise TypeError("outcomes must be a tuple")
        if not self.outcomes:
            raise ValueError("outcomes must not be empty")
        if not all(isinstance(outcome, Outcome) for outcome in self.outcomes):
            raise TypeError("outcomes must contain only Outcome values")
        keys = [outcome.key for outcome in self.outcomes]
        if len(keys) != len(set(keys)):
            raise ValueError("outcome keys must be unique within a market")

        required_outcomes = {
            "totals": ("over", "under"),
            "spreads": ("home", "away"),
        }
        required = required_outcomes.get(self.key)
        if required is not None:
            if self.line is None:
                raise ValueError(f"{self.key} line is required")
            missing = set(required).difference(keys)
            if missing:
                expected = " and ".join(required)
                raise ValueError(f"{self.key} outcomes must include {expected}")

    def outcome(self, key: str) -> Outcome:
        normalized_key = _canonical_key(key, "outcome key")
        for outcome in self.outcomes:
            if outcome.key == normalized_key:
                return outcome
        raise KeyError(f"outcome {normalized_key!r} is not present in market {self.key!r}")


@dataclass(frozen=True, slots=True)
class Event:
    source: str
    source_event_id: str
    sport: str
    league: str
    home_team: str
    away_team: str
    starts_at: datetime
    observed_at: datetime
    markets: tuple[Market, ...]

    def __post_init__(self) -> None:
        for field in (
            "source",
            "source_event_id",
            "sport",
            "league",
            "home_team",
            "away_team",
        ):
            object.__setattr__(self, field, _required_text(getattr(self, field), field))

        if self.home_team.casefold() == self.away_team.casefold():
            raise ValueError("home_team and away_team must be distinct")

        starts_at = _validate_aware_datetime(self.starts_at, "starts_at")
        observed_at = _validate_aware_datetime(self.observed_at, "observed_at")
        if starts_at <= observed_at:
            raise ValueError("event must start in the future relative to observed_at")

        if not isinstance(self.markets, tuple):
            raise TypeError("markets must be a tuple")
        if not all(isinstance(market, Market) for market in self.markets):
            raise TypeError("markets must contain only Market values")

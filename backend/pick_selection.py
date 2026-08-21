"""Build publishable pick candidates from normalized sportsbook evidence only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
from numbers import Real
from typing import Iterable
import unicodedata
from zoneinfo import ZoneInfo

from backend.scraper_domain import Event


SUPPORTED_MARKETS = frozenset(
    {
        ("h2h", "full_game"),
        ("totals", "full_game"),
        ("spreads", "full_game"),
    }
)
SUPPORTED_SELECTIONS = {
    "h2h": frozenset({"home", "draw", "away"}),
    "totals": frozenset({"over", "under"}),
    "spreads": frozenset({"home", "away"}),
}
MEXICO = ZoneInfo("America/Mexico_City")
PHYSICAL_EVENT_KICKOFF_TOLERANCE = timedelta(minutes=5)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _canonical_key(value: object, field: str) -> str:
    return _required_text(value, field).casefold()


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _finite_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be finite")
    return normalized


def _canonical_line(line: float | None) -> str | None:
    if line is None:
        return None
    number = Decimal(str(line)).normalize()
    if number == 0:
        return "0"
    return format(number, "f")


def _candidate_id(
    source: str,
    source_event_id: str,
    bookmaker_key: str,
    market_key: str,
    period: str,
    line: float | None,
    selection_key: str,
) -> str:
    identity = [
        source,
        source_event_id,
        bookmaker_key,
        market_key,
        period,
        _canonical_line(line),
        selection_key,
    ]
    return "candidate:v1:" + json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class CandidatePick:
    """One exact normalized outcome quote eligible for deterministic ranking."""

    candidate_id: str
    source: str
    source_event_id: str
    bookmaker_key: str
    starts_at: datetime
    observed_at: datetime
    sport: str
    league: str
    home_team: str
    away_team: str
    market_key: str
    period: str
    line: float | None
    selection_key: str
    selection_name: str
    price: float

    def __post_init__(self) -> None:
        for field in (
            "source",
            "source_event_id",
            "sport",
            "league",
            "home_team",
            "away_team",
            "selection_name",
        ):
            object.__setattr__(
                self,
                field,
                _required_text(getattr(self, field), field),
            )
        for field in ("bookmaker_key", "market_key", "period", "selection_key"):
            object.__setattr__(
                self,
                field,
                _canonical_key(getattr(self, field), field),
            )

        starts_at = _aware_datetime(self.starts_at, "starts_at")
        observed_at = _aware_datetime(self.observed_at, "observed_at")
        if starts_at <= observed_at:
            raise ValueError("candidate event must start after it was observed")
        if (self.market_key, self.period) not in SUPPORTED_MARKETS:
            raise ValueError("candidate market and period are not supported")
        if self.selection_key not in SUPPORTED_SELECTIONS[self.market_key]:
            raise ValueError("candidate selection is not supported for its market")
        if self.market_key == "h2h" and self.line is not None:
            raise ValueError("h2h line must be absent")
        if self.market_key in {"totals", "spreads"} and self.line is None:
            raise ValueError(f"{self.market_key} line is required")

        if self.line is not None:
            object.__setattr__(self, "line", _finite_float(self.line, "line"))
        price = _finite_float(self.price, "price")
        if not 1.01 <= price <= 50.0:
            raise ValueError("price must be decimal odds between 1.01 and 50")
        object.__setattr__(self, "price", price)

        expected_id = _candidate_id(
            self.source,
            self.source_event_id,
            self.bookmaker_key,
            self.market_key,
            self.period,
            self.line,
            self.selection_key,
        )
        if self.candidate_id != expected_id:
            raise ValueError("candidate_id does not match candidate evidence")


def _candidate_from_evidence(event: Event, market_index: int, outcome_index: int) -> CandidatePick:
    market = event.markets[market_index]
    outcome = market.outcomes[outcome_index]
    if market.bookmaker_key is None:
        raise ValueError("bookmaker identity is required")
    candidate_id = _candidate_id(
        event.source,
        event.source_event_id,
        market.bookmaker_key,
        market.key,
        market.period,
        market.line,
        outcome.key,
    )
    return CandidatePick(
        candidate_id=candidate_id,
        source=event.source,
        source_event_id=event.source_event_id,
        bookmaker_key=market.bookmaker_key,
        starts_at=event.starts_at,
        observed_at=event.observed_at,
        sport=event.sport,
        league=event.league,
        home_team=event.home_team,
        away_team=event.away_team,
        market_key=market.key,
        period=market.period,
        line=market.line,
        selection_key=outcome.key,
        selection_name=outcome.name,
        price=outcome.price,
    )


def build_candidates(events: Iterable[Event]) -> list[CandidatePick]:
    """Return exact supported outcome quotes, omitting conflicting identities."""

    candidates: dict[str, CandidatePick] = {}
    conflicted: set[str] = set()
    for event in events:
        if not isinstance(event, Event):
            continue
        for market_index, market in enumerate(event.markets):
            if (
                (market.key, market.period) not in SUPPORTED_MARKETS
                or market.bookmaker_key is None
                or (market.key == "h2h" and market.line is not None)
                or (market.key in {"totals", "spreads"} and market.line is None)
            ):
                continue
            for outcome_index, _outcome in enumerate(market.outcomes):
                if _outcome.key not in SUPPORTED_SELECTIONS[market.key]:
                    continue
                candidate = _candidate_from_evidence(
                    event,
                    market_index,
                    outcome_index,
                )
                identity = candidate.candidate_id
                if identity in conflicted:
                    continue
                existing = candidates.get(identity)
                if existing is None:
                    candidates[identity] = candidate
                elif existing != candidate:
                    candidates.pop(identity, None)
                    conflicted.add(identity)
    return list(candidates.values())


def _is_individually_valid(candidate: object) -> bool:
    if not isinstance(candidate, CandidatePick):
        return False
    return candidate.candidate_id == _candidate_id(
        candidate.source,
        candidate.source_event_id,
        candidate.bookmaker_key,
        candidate.market_key,
        candidate.period,
        candidate.line,
        candidate.selection_key,
    )


def _normalized_competitor(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value.casefold())
    return " ".join(normalized.split())


def _physical_competitor_pair(candidate: CandidatePick) -> tuple[str, str]:
    competitors = sorted(
        (
            _normalized_competitor(candidate.home_team),
            _normalized_competitor(candidate.away_team),
        )
    )
    return competitors[0], competitors[1]


def _same_physical_event(first: CandidatePick, second: CandidatePick) -> bool:
    """Fail closed on cross-source kickoff drift of five minutes or less."""

    if _physical_competitor_pair(first) != _physical_competitor_pair(second):
        return False
    kickoff_delta = abs(
        first.starts_at.astimezone(timezone.utc)
        - second.starts_at.astimezone(timezone.utc)
    )
    return kickoff_delta <= PHYSICAL_EVENT_KICKOFF_TOLERANCE


def build_same_day_parlay(
    candidates: Iterable[CandidatePick],
) -> tuple[CandidatePick, ...] | None:
    """Validate and bundle legs without calculating or claiming a parlay quote."""

    catalog: dict[str, CandidatePick] = {}
    conflicted: set[str] = set()
    for candidate in candidates:
        if not _is_individually_valid(candidate):
            continue
        identity = candidate.candidate_id
        if identity in conflicted:
            continue
        existing = catalog.get(identity)
        if existing is None:
            catalog[identity] = candidate
        elif existing != candidate:
            catalog.pop(identity, None)
            conflicted.add(identity)

    eligible = sorted(
        catalog.values(),
        key=lambda candidate: (candidate.starts_at, candidate.candidate_id),
    )
    for index, first in enumerate(eligible):
        first_date = first.starts_at.astimezone(MEXICO).date()
        for second in eligible[index + 1 :]:
            if (first.source, first.source_event_id) == (
                second.source,
                second.source_event_id,
            ):
                continue
            if _same_physical_event(first, second):
                continue
            if second.starts_at.astimezone(MEXICO).date() != first_date:
                continue
            return first, second
    return None

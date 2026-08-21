"""Build publishable pick candidates from normalized sportsbook evidence only."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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
# Bound model-controlled output before persistence and notification fan-out.
MAX_AI_RANKED_PICKS = 12


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
    try:
        reconstructed = CandidatePick(
            **{
                field: getattr(candidate, field)
                for field in CandidatePick.__dataclass_fields__
            }
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return reconstructed == candidate


def _normalized_competitor(value: str) -> str:
    """Fold accents/case/space; preserve non-mark alphanumerics and punctuation."""

    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.category(character).startswith("M")
    )
    return " ".join(without_marks.casefold().split())


def _physical_competitor_pair(candidate: CandidatePick) -> tuple[str, str]:
    competitors = sorted(
        (
            _normalized_competitor(candidate.home_team),
            _normalized_competitor(candidate.away_team),
        )
    )
    return competitors[0], competitors[1]


def _same_physical_event(first: CandidatePick, second: CandidatePick) -> bool:
    """Fail closed on an unordered competitor pair on one Mexico date."""

    if _physical_competitor_pair(first) != _physical_competitor_pair(second):
        return False
    return (
        first.starts_at.astimezone(MEXICO).date()
        == second.starts_at.astimezone(MEXICO).date()
    )


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


@dataclass(frozen=True, slots=True)
class RankedPick:
    """A model-supplied rationale bound to one verified catalog object."""

    candidate: CandidatePick
    rationale: str

    def __post_init__(self) -> None:
        if not _is_individually_valid(self.candidate):
            raise ValueError("ranked candidate must be valid")
        if not isinstance(self.rationale, str):
            raise TypeError("rationale must be a string")
        rationale = self.rationale.strip()
        if len(rationale) < 10:
            raise ValueError("rationale must contain at least 10 characters")
        object.__setattr__(self, "rationale", rationale[:500])


def validate_ai_ranking(
    response: object,
    candidates: Iterable[CandidatePick],
) -> list[RankedPick]:
    """Allow-list untrusted model rankings against an unambiguous catalog."""

    if not isinstance(response, list):
        return []

    catalog: dict[str, CandidatePick] = {}
    ambiguous_ids: set[str] = set()
    for candidate in candidates:
        if not _is_individually_valid(candidate):
            continue
        candidate_id = candidate.candidate_id
        if candidate_id in ambiguous_ids:
            continue
        if candidate_id in catalog:
            catalog.pop(candidate_id, None)
            ambiguous_ids.add(candidate_id)
        else:
            catalog[candidate_id] = candidate

    ranked: list[RankedPick] = []
    seen: set[str] = set()
    for item in response:
        if not isinstance(item, Mapping):
            continue
        response_candidate_id = item.get("candidate_id")
        rationale = item.get("rationale")
        if (
            not isinstance(response_candidate_id, str)
            or not response_candidate_id
            or response_candidate_id in seen
            or response_candidate_id not in catalog
            or not isinstance(rationale, str)
        ):
            continue
        trimmed_rationale = rationale.strip()
        if len(trimmed_rationale) < 10:
            continue
        seen.add(response_candidate_id)
        ranked.append(
            RankedPick(catalog[response_candidate_id], trimmed_rationale[:500])
        )
        if len(ranked) >= MAX_AI_RANKED_PICKS:
            break
    return ranked

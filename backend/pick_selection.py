"""Build publishable pick candidates from normalized sportsbook evidence only."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import math
from numbers import Real
import unicodedata
from zoneinfo import ZoneInfo

from backend.scraper_domain import Event, Market


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
MAX_DAILY_PICKS = 6
EVIDENCE_LABEL_LIMITED = "Datos limitados"
EVIDENCE_LABEL_HIGH = "Respaldo alto"
EVIDENCE_START_TOLERANCE = timedelta(minutes=5)
_PLAYER_PROP_MARKERS = (
    "remates",
    "tiros a puerta",
    "tiros del jugador",
    "anota",
    "goleador",
    "pases del jugador",
    "tarjetas del jugador",
)


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


def _non_negative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class Evidence:
    """Documented quote signals; never a probability estimate."""

    source_count: int
    age_minutes: int
    price_spread: float | None
    market_complete: bool

    def __post_init__(self) -> None:
        _non_negative_int(self.source_count, "source_count")
        _non_negative_int(self.age_minutes, "age_minutes")
        if self.price_spread is not None:
            if not isinstance(self.price_spread, float):
                raise TypeError("price_spread must be a float or None")
            if not math.isfinite(self.price_spread):
                raise ValueError("price_spread must be finite")
            if self.price_spread < 0:
                raise ValueError("price_spread must be non-negative")
        if not isinstance(self.market_complete, bool):
            raise TypeError("market_complete must be a bool")


@dataclass(frozen=True, slots=True)
class EvidenceScore:
    """Bounded data-support score, not a claimed chance of winning."""

    percent: int
    label: str
    has_value: bool

    def __post_init__(self) -> None:
        percent = _non_negative_int(self.percent, "percent")
        if percent > 85:
            raise ValueError("percent must be at most 85")
        if self.label not in {EVIDENCE_LABEL_LIMITED, EVIDENCE_LABEL_HIGH}:
            raise ValueError("label must be a documented evidence label")
        if not isinstance(self.has_value, bool):
            raise TypeError("has_value must be a bool")
        if self.has_value != (self.label == EVIDENCE_LABEL_HIGH):
            raise ValueError("has_value and label must describe the same evidence")


def score_evidence(evidence: Evidence) -> EvidenceScore:
    """Score observable quote support without estimating win probability."""

    if not isinstance(evidence, Evidence):
        raise TypeError("evidence must be Evidence")
    agrees = evidence.price_spread is not None and evidence.price_spread <= 0.05
    fresh = evidence.age_minutes <= 10
    strong = (
        evidence.source_count >= 2
        and fresh
        and evidence.market_complete
        and agrees
    )
    points = 45
    points += 15 if evidence.source_count >= 2 else 0
    points += 10 if fresh else 0
    points += 10 if evidence.market_complete else 0
    points += 5 if agrees else 0
    return EvidenceScore(
        percent=min(points, 85),
        label=EVIDENCE_LABEL_HIGH if strong else EVIDENCE_LABEL_LIMITED,
        has_value=strong,
    )


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
    offer_kind: str | None = None,
    offer_description: str | None = None,
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
    if offer_kind is not None or offer_description is not None:
        identity.extend([
            "offer",
            offer_kind,
            offer_description,
        ])
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
    market_name: str | None = None
    source_market_id: str | None = None
    source_selection_id: str | None = None
    market_scope: str | None = None
    participant_id: str | None = None
    team_id: str | None = None
    competitor_id: str | None = None
    offer_kind: str | None = None
    offer_description: str | None = None
    source_market_selection_ids: tuple[str, ...] | None = None
    lineup_confirmed: bool = False

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
        canonical_market = (self.market_key, self.period) in SUPPORTED_MARKETS
        generic_market = self.market_key.startswith("playdoit_market:")
        if not canonical_market and not generic_market:
            raise ValueError("candidate market and period are not supported")
        if generic_market:
            if (
                self.source.casefold() != "playdoit"
                or self.bookmaker_key != "playdoit"
            ):
                raise ValueError(
                    "generic market requires Playdoit provenance"
                )
            for field in (
                "market_name",
                "source_market_id",
                "source_selection_id",
                "market_scope",
                "offer_kind",
            ):
                object.__setattr__(
                    self,
                    field,
                    _required_text(getattr(self, field), field),
                )
            for field in (
                "participant_id",
                "team_id",
                "competitor_id",
                "offer_description",
            ):
                value = getattr(self, field)
                if value is not None:
                    object.__setattr__(
                        self,
                        field,
                        _required_text(value, field),
                    )
            if not isinstance(self.source_market_selection_ids, tuple):
                raise TypeError(
                    "source_market_selection_ids must be a tuple"
                )
            normalized_selection_ids = tuple(
                _required_text(value, "source_market_selection_ids")
                for value in self.source_market_selection_ids
            )
            if (
                not normalized_selection_ids
                or len(normalized_selection_ids)
                != len(set(normalized_selection_ids))
            ):
                raise ValueError(
                    "source_market_selection_ids must be nonempty and unique"
                )
            object.__setattr__(
                self,
                "source_market_selection_ids",
                normalized_selection_ids,
            )
            if self.market_key != (
                f"playdoit_market:{self.source_market_id}".casefold()
            ):
                raise ValueError("generic market key must contain its source id")
            if self.selection_key != (
                f"playdoit_odd:{self.source_selection_id}".casefold()
            ):
                raise ValueError(
                    "generic selection key must contain its source id"
                )
            if self.source_selection_id not in normalized_selection_ids:
                raise ValueError(
                    "generic selection must belong to its declared market"
                )
            if not isinstance(self.lineup_confirmed, bool):
                raise TypeError("lineup_confirmed must be a bool")
            if _candidate_requires_confirmed_lineup(self) and not (
                self.lineup_confirmed
            ):
                raise ValueError(
                    "player prop requires confirmed starting lineup"
                )
        else:
            if self.selection_key not in SUPPORTED_SELECTIONS[self.market_key]:
                raise ValueError(
                    "candidate selection is not supported for its market"
                )
            if self.market_key == "h2h" and self.line is not None:
                raise ValueError("h2h line must be absent")
            if self.market_key in {"totals", "spreads"} and self.line is None:
                raise ValueError(f"{self.market_key} line is required")

        if self.line is not None:
            object.__setattr__(self, "line", _finite_float(self.line, "line"))
        price = _finite_float(self.price, "price")
        maximum_price = 1000.0 if generic_market else 50.0
        if not 1.01 <= price <= maximum_price:
            raise ValueError(
                "price must be decimal odds between "
                f"1.01 and {maximum_price:g}"
            )
        object.__setattr__(self, "price", price)

        expected_id = _candidate_id(
            self.source,
            self.source_event_id,
            self.bookmaker_key,
            self.market_key,
            self.period,
            self.line,
            self.selection_key,
            self.offer_kind,
            self.offer_description,
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
        market.offer_kind,
        market.offer_description,
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
        market_name=market.name,
        source_market_id=market.source_id,
        source_selection_id=outcome.source_id,
        market_scope=market.scope,
        participant_id=market.participant_id,
        team_id=market.team_id,
        competitor_id=outcome.competitor_id or market.competitor_id,
        offer_kind=market.offer_kind,
        offer_description=market.offer_description,
        source_market_selection_ids=market.source_selection_ids,
        lineup_confirmed=(
            market.lineup_confirmed or outcome.lineup_confirmed
        ),
    )


def _market_requires_confirmed_lineup(market: Market) -> bool:
    if market.participant_id is not None:
        return True
    if market.scope is not None and market.scope.casefold() in {
        "player",
        "participant",
        "player_prop",
    }:
        return True
    if (
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
    ):
        return True
    title = (market.name or "").casefold()
    return any(marker in title for marker in _PLAYER_PROP_MARKERS)


def _candidate_requires_confirmed_lineup(candidate: CandidatePick) -> bool:
    if candidate.participant_id is not None:
        return True
    if candidate.market_scope is not None and candidate.market_scope.casefold() in {
        "player",
        "participant",
        "player_prop",
    }:
        return True
    if (
        candidate.market_scope is not None
        and candidate.market_scope.casefold() == "source_unspecified"
        and candidate.team_id is None
        and candidate.competitor_id is not None
    ):
        return True
    title = (candidate.market_name or "").casefold()
    return any(marker in title for marker in _PLAYER_PROP_MARKERS)


def build_candidates(events: Iterable[Event]) -> list[CandidatePick]:
    """Return exact supported outcome quotes, omitting conflicting identities."""

    candidates: dict[str, CandidatePick] = {}
    conflicted: set[str] = set()
    for event in events:
        if not isinstance(event, Event):
            continue
        for market_index, market in enumerate(event.markets):
            generic_market = market.key.startswith("playdoit_market:")
            if (
                (
                    (market.key, market.period) not in SUPPORTED_MARKETS
                    and not generic_market
                )
                or market.bookmaker_key is None
                or (market.key == "h2h" and market.line is not None)
                or (market.key in {"totals", "spreads"} and market.line is None)
                or (
                    generic_market
                    and (
                        market.name is None
                        or market.source_id is None
                        or market.scope is None
                        or market.offer_kind is None
                        or market.source_selection_ids is None
                    )
                )
            ):
                continue
            for outcome_index, _outcome in enumerate(market.outcomes):
                if (
                    generic_market
                    and _market_requires_confirmed_lineup(market)
                    and not (
                        market.lineup_confirmed
                        or _outcome.lineup_confirmed
                    )
                ):
                    continue
                if (
                    generic_market and _outcome.source_id is None
                ) or (
                    not generic_market
                    and _outcome.key not in SUPPORTED_SELECTIONS[market.key]
                ):
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


def _candidate_exclusivity_group(candidate: CandidatePick) -> tuple[object, ...]:
    """Return the conservative cross-provider portfolio identity."""

    return (
        _physical_competitor_pair(candidate),
        candidate.starts_at.astimezone(MEXICO).date(),
        candidate.market_key,
        candidate.period,
        _canonical_line(candidate.line),
    )


def _canonical_sport(value: str) -> str:
    normalized = _normalized_competitor(value)
    families = {
        "football": "soccer",
        "futbol": "soccer",
    }
    for prefix in ("soccer", "baseball", "basketball", "icehockey"):
        if normalized == prefix or normalized.startswith(f"{prefix}_"):
            return prefix
    return families.get(normalized, normalized)


def _selection_anchor(candidate: CandidatePick) -> str:
    if candidate.market_key in {"h2h", "spreads"}:
        if candidate.selection_key == "home":
            return _normalized_competitor(candidate.home_team)
        if candidate.selection_key == "away":
            return _normalized_competitor(candidate.away_team)
    return candidate.selection_key


def _selection_line(candidate: CandidatePick) -> str | None:
    line = candidate.line
    if (
        candidate.market_key == "spreads"
        and candidate.selection_key == "away"
        and line is not None
    ):
        line = -line
    return _canonical_line(line)


def _same_evidence_selection(
    candidate: CandidatePick,
    quote: CandidatePick,
) -> bool:
    starts_delta = abs(
        (
            candidate.starts_at.astimezone(timezone.utc)
            - quote.starts_at.astimezone(timezone.utc)
        ).total_seconds()
    )
    return (
        _canonical_sport(candidate.sport) == _canonical_sport(quote.sport)
        and _normalized_competitor(candidate.league)
        == _normalized_competitor(quote.league)
        and _physical_competitor_pair(candidate) == _physical_competitor_pair(quote)
        and starts_delta <= EVIDENCE_START_TOLERANCE.total_seconds()
        and candidate.market_key == quote.market_key
        and candidate.period == quote.period
        and _selection_line(candidate) == _selection_line(quote)
        and _selection_anchor(candidate) == _selection_anchor(quote)
    )


def _canonical_bookmaker_origin(candidate: CandidatePick) -> str:
    decomposed = unicodedata.normalize("NFKD", candidate.bookmaker_key)
    return "".join(
        character.casefold()
        for character in decomposed
        if character.isalnum()
        and not unicodedata.category(character).startswith("M")
    )


def _market_quote_identity(candidate: CandidatePick) -> tuple[object, ...]:
    return (
        candidate.source.casefold(),
        candidate.source_event_id,
        _canonical_bookmaker_origin(candidate),
        _canonical_sport(candidate.sport),
        _normalized_competitor(candidate.league),
        _normalized_competitor(candidate.home_team),
        _normalized_competitor(candidate.away_team),
        candidate.starts_at.astimezone(timezone.utc),
        candidate.observed_at.astimezone(timezone.utc),
        candidate.market_key,
        candidate.period,
        _canonical_line(candidate.line),
    )


def _required_market_outcomes(candidate: CandidatePick) -> frozenset[str]:
    if candidate.market_key.startswith("playdoit_market:"):
        assert candidate.source_market_selection_ids is not None
        return frozenset(
            f"playdoit_odd:{source_id}".casefold()
            for source_id in candidate.source_market_selection_ids
        )
    if candidate.market_key == "h2h":
        sport = candidate.sport.casefold()
        if sport.startswith("soccer") or sport in {
            "football",
            "fútbol",
            "futbol",
        }:
            return frozenset({"home", "draw", "away"})
        return frozenset({"home", "away"})
    if candidate.market_key == "totals":
        return frozenset({"over", "under"})
    return frozenset({"home", "away"})


def _resolved_candidate_catalog(candidates: object) -> list[CandidatePick]:
    if not isinstance(candidates, Iterable):
        raise TypeError("candidates must be iterable")
    selected: dict[str, CandidatePick] = {}
    conflicts: set[str] = set()
    try:
        for candidate in candidates:
            if not _is_individually_valid(candidate):
                continue
            candidate_id = candidate.candidate_id
            if candidate_id in conflicts:
                continue
            existing = selected.get(candidate_id)
            if existing is None:
                selected[candidate_id] = candidate
            elif existing != candidate:
                selected.pop(candidate_id, None)
                conflicts.add(candidate_id)
    except Exception as exc:
        raise ValueError("candidate catalog could not be read safely") from exc
    return list(selected.values())


def evidence_for_candidate(
    candidate: CandidatePick,
    candidates: object,
    *,
    reference_at: datetime,
) -> Evidence:
    """Derive conservative quote support for one exact catalog candidate.

    Quotes are comparable only for the same physical event, Mexico date,
    market, period, canonical line, and selection. Independence means a unique
    ``(source, bookmaker_key)`` pair. The oldest observation controls freshness.
    """

    if not _is_individually_valid(candidate):
        raise ValueError("candidate must be a valid CandidatePick")
    reference = _aware_datetime(reference_at, "reference_at")
    catalog = _resolved_candidate_catalog(candidates)
    if candidate not in catalog or candidate.observed_at > reference:
        return Evidence(0, 11, None, False)
    usable_catalog = [
        quote for quote in catalog if quote.observed_at <= reference
    ]

    by_provider: dict[str, list[CandidatePick]] = {}
    for quote in usable_catalog:
        if _same_evidence_selection(candidate, quote):
            by_provider.setdefault(
                _canonical_bookmaker_origin(quote),
                [],
            ).append(quote)

    # Multiple same-provider event identities for one physical match are
    # ambiguous (for example, an untrusted doubleheader match) and contribute
    # no evidence instead of being selected heuristically.
    comparable = []
    for rows in by_provider.values():
        if len(rows) == 1:
            comparable.append(rows[0])
            continue
        event_signatures = {
            (
                row.starts_at.astimezone(timezone.utc),
                _selection_anchor(row),
                _selection_line(row),
            )
            for row in rows
        }
        prices = {Decimal(str(row.price)) for row in rows}
        if len(event_signatures) == 1 and len(prices) == 1:
            comparable.append(min(rows, key=lambda row: row.observed_at))
    if not comparable:
        return Evidence(0, 11, None, False)

    market_outcomes: dict[tuple[object, ...], set[str]] = {}
    market_sports: dict[tuple[object, ...], set[str]] = {}
    market_observations: dict[tuple[object, ...], list[datetime]] = {}
    for quote in usable_catalog:
        market_identity = _market_quote_identity(quote)
        market_outcomes.setdefault(market_identity, set()).add(quote.selection_key)
        market_sports.setdefault(market_identity, set()).add(quote.sport.casefold())
        market_observations.setdefault(market_identity, []).append(
            quote.observed_at
        )

    market_complete = True
    used_observations = []
    for quote in comparable:
        market_identity = _market_quote_identity(quote)
        observed_outcomes = market_outcomes.get(market_identity, set())
        used_observations.extend(
            market_observations.get(market_identity, [quote.observed_at])
        )
        if (
            len(market_sports.get(market_identity, set())) != 1
            or not _required_market_outcomes(quote).issubset(observed_outcomes)
        ):
            market_complete = False
            break

    oldest_age_seconds = max(
        (reference - observed_at).total_seconds()
        for observed_at in used_observations
    )
    age_minutes = math.ceil(oldest_age_seconds / 60)

    prices = [quote.price for quote in comparable]
    price_spread = (
        float(Decimal(str(max(prices))) - Decimal(str(min(prices))))
        if len(prices) >= 2
        else None
    )
    return Evidence(
        source_count=len(comparable),
        age_minutes=age_minutes,
        price_spread=price_spread,
        market_complete=market_complete,
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


def select_daily_portfolio(ranked: object) -> list[RankedPick]:
    """Keep the highest-ranked pick from at most six physical events."""

    if isinstance(ranked, (str, bytes)) or not isinstance(ranked, Iterable):
        return []
    try:
        rows = list(ranked)
    except Exception:
        return []
    if not all(isinstance(row, RankedPick) for row in rows):
        return []

    selected: list[RankedPick] = []
    for row in rows:
        if any(
            _same_physical_event(row.candidate, existing.candidate)
            for existing in selected
        ):
            continue
        selected.append(row)
        if len(selected) == MAX_DAILY_PICKS:
            break
    return selected


def validate_ai_ranking(
    response: object,
    candidates: object,
) -> list[RankedPick]:
    """Allow-list an untrusted ranking and fail closed on portfolio conflicts.

    Exclusivity deliberately ignores source and bookmaker: opposing selections
    for the same normalized competitors, Mexico date, market, period, and line
    are contradictory even when quoted by different providers.
    """

    if not isinstance(response, list):
        return []
    if not isinstance(candidates, Iterable):
        return []
    try:
        response_items = list(response)
    except Exception:
        return []

    catalog: dict[str, CandidatePick] = {}
    ambiguous_ids: set[str] = set()
    try:
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
    except Exception:
        return []

    valid_rows: list[RankedPick] = []
    seen: set[str] = set()
    try:
        for item in response_items:
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
            valid_rows.append(
                RankedPick(
                    catalog[response_candidate_id],
                    trimmed_rationale[:500],
                )
            )
    except Exception:
        return []

    first_by_group: dict[tuple[object, ...], RankedPick] = {}
    group_order: list[tuple[object, ...]] = []
    conflicted_groups: set[tuple[object, ...]] = set()
    for row in valid_rows:
        candidate = row.candidate
        group = _candidate_exclusivity_group(candidate)
        if group in conflicted_groups:
            continue
        existing = first_by_group.get(group)
        if existing is None:
            first_by_group[group] = row
            group_order.append(group)
        elif existing.candidate.selection_key != candidate.selection_key:
            first_by_group.pop(group, None)
            conflicted_groups.add(group)

    resolved = [
        first_by_group[group]
        for group in group_order
        if group in first_by_group
    ]
    return resolved[:MAX_AI_RANKED_PICKS]

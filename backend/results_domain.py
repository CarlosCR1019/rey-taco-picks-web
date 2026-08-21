"""Pure, conservative grading rules for completed sporting events."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable


REVIEW = "revision_pendiente"
PENDING = "pendiente"
WON = "ganado"
LOST = "perdido"
VOID = "void"

_TEAM_STOP_WORDS = {
    "ac",
    "cd",
    "cf",
    "club",
    "deportivo",
    "fc",
    "sc",
}


@dataclass(frozen=True)
class EventResult:
    home: str
    away: str
    home_score: float
    away_score: float
    completed: bool
    home_corners: float | None = None
    away_corners: float | None = None
    source: str = ""
    source_id: str = ""


def _plain(value: str) -> str:
    return (
        unicodedata.normalize("NFKD", str(value).lower())
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def normalize_team(value: str) -> frozenset[str]:
    tokens = re.findall(r"[a-z0-9]+", _plain(value))
    return frozenset(token for token in tokens if token not in _TEAM_STOP_WORDS)


def _team_matches(expected: str, actual: str) -> bool:
    left = normalize_team(expected)
    right = normalize_team(actual)
    if not left or not right:
        return False
    if left <= right or right <= left:
        return True
    overlap = left & right
    return len(overlap) >= 2 and len(overlap) / max(len(left), len(right)) >= 0.67


def _selection_names_team(selection: str, team: str) -> bool:
    selection_tokens = normalize_team(selection)
    team_tokens = normalize_team(team)
    return bool(
        selection_tokens
        and team_tokens
        and any(token in selection_tokens for token in team_tokens if len(token) >= 4)
    )


def _split_match(label: str) -> tuple[str, str] | None:
    parts = re.split(r"\s+(?:vs?\.?|-)\s+", str(label), maxsplit=1, flags=re.I)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        return None
    return parts[0].strip(), parts[1].strip()


def match_event(label: str, event: EventResult) -> bool:
    teams = _split_match(label)
    if not teams:
        return False
    first, second = teams
    same_order = _team_matches(first, event.home) and _team_matches(second, event.away)
    reverse_order = _team_matches(first, event.away) and _team_matches(second, event.home)
    return same_order or reverse_order


def find_matching_event(label: str, events: Iterable[EventResult]) -> EventResult | None:
    matches = [event for event in events if event.completed and match_event(label, event)]
    return matches[0] if len(matches) == 1 else None


def _comparison(selection: str, total: float) -> str | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)", selection)
    if not match:
        return None
    line = float(match.group(1).replace(",", "."))
    if total == line:
        return VOID
    if "mas de" in selection or "over" in selection:
        return WON if total > line else LOST
    if "menos de" in selection or "under" in selection:
        return WON if total < line else LOST
    return None


def grade_pick(selection: str, event: EventResult) -> str:
    if not event.completed:
        return PENDING

    text = _plain(selection)

    if any(term in text for term in ("corner", "esquina")):
        if event.home_corners is None or event.away_corners is None:
            return REVIEW
        decision = _comparison(text, event.home_corners + event.away_corners)
        return decision or REVIEW

    if "ambos equipos anotan" in text or "btts" in text:
        both_scored = event.home_score > 0 and event.away_score > 0
        wants_no = bool(re.search(r"(?:no|: no)\s*$", text))
        won = not both_scored if wants_no else both_scored
        return WON if won else LOST

    if any(term in text for term in ("gol", "carrera", "total", "over", "under")):
        decision = _comparison(text, event.home_score + event.away_score)
        return decision or REVIEW

    if "1x" in text:
        return WON if event.home_score >= event.away_score else LOST
    if "x2" in text:
        return WON if event.away_score >= event.home_score else LOST

    if "empate" in text and not any(term in text for term in ("gana o empata", "doble")):
        return WON if event.home_score == event.away_score else LOST

    if any(term in text for term in ("gana", "ganador", "moneyline", " ml")):
        if _selection_names_team(selection, event.home):
            return WON if event.home_score > event.away_score else LOST
        if _selection_names_team(selection, event.away):
            return WON if event.away_score > event.home_score else LOST

    return REVIEW


def unit_result(status: str, decimal_odds: float) -> float:
    if status == WON:
        return round(float(decimal_odds) - 1.0, 4)
    if status == LOST:
        return -1.0
    return 0.0

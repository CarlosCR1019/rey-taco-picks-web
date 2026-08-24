"""Pure, conservative grading rules for completed sporting events."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
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
class PlayerResult:
    name: str
    team: str
    minutes: float | None = None
    shots_total: float | None = None
    shots_on: float | None = None
    goals: float | None = None
    assists: float | None = None
    yellow_cards: float | None = None
    red_cards: float | None = None


@dataclass(frozen=True)
class MarketIdentity:
    bookmaker_key: str
    market_key: str
    period: str
    line: float | None
    source_market_id: str | None = None
    scope: str | None = None
    participant_id: str | None = None
    team_id: str | None = None
    competitor_id: str | None = None
    offer_kind: str | None = None
    lineup_confirmed: bool = False


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
    event_date: str = ""
    home_first_half_score: float | None = None
    away_first_half_score: float | None = None
    home_shots_total: float | None = None
    away_shots_total: float | None = None
    home_shots_on: float | None = None
    away_shots_on: float | None = None
    home_fouls: float | None = None
    away_fouls: float | None = None
    home_offsides: float | None = None
    away_offsides: float | None = None
    home_yellow_cards: float | None = None
    away_yellow_cards: float | None = None
    home_red_cards: float | None = None
    away_red_cards: float | None = None
    players: tuple[PlayerResult, ...] = ()


def parse_market_identity(value: object) -> MarketIdentity | None:
    """Decode one immutable source audit key without accepting partial data."""

    if (
        not isinstance(value, str)
        or not value.startswith("market:v1:")
        or len(value) > 1000
    ):
        return None
    try:
        raw = json.loads(value.removeprefix("market:v1:"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, list) or len(raw) not in {4, 6}:
        return None
    bookmaker_key, market_key, period, line = raw[:4]
    if not all(
        isinstance(item, str) and bool(item.strip())
        for item in (bookmaker_key, market_key, period)
    ):
        return None
    if line is not None and (
        isinstance(line, bool)
        or not isinstance(line, (int, float))
        or not math.isfinite(float(line))
    ):
        return None
    if len(raw) == 4:
        canonical_market = market_key.strip().casefold()
        canonical_period = period.strip().casefold()
        if (
            canonical_period != "full_game"
            or canonical_market not in {"h2h", "totals", "spreads"}
            or (canonical_market == "h2h") != (line is None)
        ):
            return None
        return MarketIdentity(
            bookmaker_key.strip().casefold(),
            canonical_market,
            canonical_period,
            None if line is None else float(line),
        )

    source_market_id, metadata = raw[4:]
    expected_metadata = {
        "scope",
        "participant_id",
        "team_id",
        "competitor_id",
        "offer_kind",
        "lineup_confirmed",
    }
    if (
        not isinstance(source_market_id, str)
        or not source_market_id.strip()
        or bookmaker_key.strip().casefold() != "playdoit"
        or market_key.strip().casefold()
        != f"playdoit_market:{source_market_id.strip()}".casefold()
        or line is not None
        or not isinstance(metadata, dict)
        or set(metadata) != expected_metadata
        or not isinstance(metadata.get("scope"), str)
        or not metadata["scope"].strip()
        or not isinstance(metadata.get("offer_kind"), str)
        or not metadata["offer_kind"].strip()
        or type(metadata.get("lineup_confirmed")) is not bool
        or any(
            item is not None
            and (not isinstance(item, str) or not item.strip())
            for item in (
                metadata.get("participant_id"),
                metadata.get("team_id"),
                metadata.get("competitor_id"),
            )
        )
    ):
        return None
    return MarketIdentity(
        bookmaker_key.strip().casefold(),
        market_key.strip().casefold(),
        period.strip().casefold(),
        None if line is None else float(line),
        source_market_id=source_market_id.strip(),
        scope=metadata["scope"].strip().casefold(),
        participant_id=metadata.get("participant_id"),
        team_id=metadata.get("team_id"),
        competitor_id=metadata.get("competitor_id"),
        offer_kind=metadata["offer_kind"].strip().casefold(),
        lineup_confirmed=metadata["lineup_confirmed"],
    )


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


def find_matching_event(
    label: str,
    events: Iterable[EventResult],
    expected_date: str = "",
) -> EventResult | None:
    matches = [
        event for event in events
        if event.completed
        and match_event(label, event)
        and (not expected_date or event.event_date[:10] == expected_date[:10])
    ]
    return matches[0] if len(matches) == 1 else None


def find_matching_parlay_events(
    label: str,
    events: Iterable[EventResult],
    expected_date: str = "",
) -> list[EventResult] | None:
    legs = [part.strip() for part in re.split(r"\s+\+\s+", str(label)) if part.strip()]
    if len(legs) < 2:
        return None
    event_list = list(events)
    matches = [find_matching_event(leg, event_list, expected_date) for leg in legs]
    if any(event is None for event in matches):
        return None
    resolved = [event for event in matches if event is not None]
    unique_ids = {(event.source, event.source_id) for event in resolved}
    return resolved if len(unique_ids) == len(resolved) else None


def _comparison(selection: str, total: float) -> str | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)", selection)
    if not match:
        return None
    line = float(match.group(1).replace(",", "."))
    plus = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*[+]", selection)
    if plus:
        threshold = float(plus.group(1).replace(",", "."))
        return WON if total >= threshold else LOST
    if math.isclose(abs(line * 4) % 2, 1.0, abs_tol=1e-9):
        return REVIEW
    if total == line:
        return VOID
    if "mas de" in selection or "over" in selection:
        return WON if total > line else LOST
    if "menos de" in selection or "under" in selection:
        return WON if total < line else LOST
    return None


def _display_line(selection: str) -> float | None:
    match = re.search(r"(?<!\d)([+-]?\d+(?:[.,]\d+)?)", selection)
    if match is None:
        return None
    try:
        line = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return line if math.isfinite(line) else None


def _score_pair(
    event: EventResult, period: str
) -> tuple[float, float] | None:
    if period in {"first_half", "first half", "1st_half"}:
        if (
            event.home_first_half_score is None
            or event.away_first_half_score is None
        ):
            return None
        return event.home_first_half_score, event.away_first_half_score
    if period == "full_game":
        return event.home_score, event.away_score
    return None


def _grade_h2h(
    selection: str, event: EventResult, scores: tuple[float, float]
) -> str:
    home_score, away_score = scores
    text = _plain(selection)
    if "empate" in text or text.strip() in {"draw", "x"}:
        return WON if home_score == away_score else LOST
    names_home = _selection_names_team(selection, event.home)
    names_away = _selection_names_team(selection, event.away)
    if names_home == names_away:
        return REVIEW
    if names_home:
        return WON if home_score > away_score else LOST
    return WON if away_score > home_score else LOST


def _team_value(
    context: str,
    event: EventResult,
    home_value: float | None,
    away_value: float | None,
) -> float | None:
    names_home = _selection_names_team(context, event.home)
    names_away = _selection_names_team(context, event.away)
    if names_home == names_away:
        return None
    return home_value if names_home else away_value


def _matching_player(context: str, event: EventResult) -> PlayerResult | None:
    normalized_context = f" {_plain(context)} "
    matches = []
    for player in event.players:
        normalized_name = " ".join(normalize_team(player.name))
        if normalized_name and f" {normalized_name} " in normalized_context:
            matches.append(player)
            continue
        tokens = normalize_team(player.name)
        if len(tokens) >= 2 and all(
            f" {token} " in normalized_context for token in tokens
        ):
            matches.append(player)
    return matches[0] if len(matches) == 1 else None


def _player_stat(context: str, player: PlayerResult) -> float | None:
    if "primer goleador" in context or "first scorer" in context:
        return None
    if any(term in context for term in ("remates a puerta", "tiros a puerta")):
        return player.shots_on
    if any(term in context for term in ("remates", "tiros")):
        return player.shots_total
    if "asistencia" in context or "assist" in context:
        return player.assists
    if "tarjeta amarilla" in context or "yellow card" in context:
        return player.yellow_cards
    if "tarjeta roja" in context or "red card" in context:
        return player.red_cards
    if any(term in context for term in ("anota", "goleador", " gol", "goal")):
        return player.goals
    return None


def _team_or_event_stat(
    context: str,
    event: EventResult,
    scope: str,
) -> float | None:
    values: tuple[float | None, float | None] | None = None
    if any(term in context for term in ("tiros de esquina", "corner")):
        values = (event.home_corners, event.away_corners)
    elif any(term in context for term in ("remates a puerta", "tiros a puerta")):
        values = (event.home_shots_on, event.away_shots_on)
    elif any(term in context for term in ("remates", "tiros totales", "total shots")):
        values = (event.home_shots_total, event.away_shots_total)
    elif "falta" in context or "foul" in context:
        values = (event.home_fouls, event.away_fouls)
    elif "fuera de juego" in context or "offside" in context:
        values = (event.home_offsides, event.away_offsides)
    elif "tarjeta amarilla" in context or "yellow card" in context:
        values = (event.home_yellow_cards, event.away_yellow_cards)
    elif "tarjeta roja" in context or "red card" in context:
        values = (event.home_red_cards, event.away_red_cards)
    if values is None:
        return None
    if scope in {"team", "team_total"}:
        return _team_value(context, event, *values)
    if values[0] is None or values[1] is None:
        return None
    return values[0] + values[1]


def grade_pick(
    selection: str,
    event: EventResult,
    *,
    market_name: str = "",
    market_identity: MarketIdentity | None = None,
) -> str:
    if not event.completed:
        return PENDING

    text = _plain(selection)
    market_text = _plain(market_name)
    context = " ".join(part for part in (market_text, text) if part)
    identity = market_identity
    period = identity.period if identity is not None else "full_game"
    scores = _score_pair(event, period)

    if identity is None and any(term in text for term in (
        "1er inning", "primer inning", "primera entrada", "first inning",
        "primera mitad", "primer tiempo", "1er tiempo", "first half",
        "primer cuarto", "first quarter", "team total", "total del equipo",
    )):
        return REVIEW

    if identity is not None and identity.market_key == "h2h":
        return _grade_h2h(selection, event, scores) if scores else REVIEW
    if identity is not None and identity.market_key == "totals":
        displayed_line = _display_line(text)
        if (
            scores is None
            or identity.line is None
            or displayed_line is None
            or not math.isclose(
                displayed_line, identity.line, rel_tol=0.0, abs_tol=1e-9
            )
        ):
            return REVIEW
        return _comparison(text, sum(scores)) or REVIEW
    if identity is not None and identity.market_key == "spreads":
        if scores is None:
            return REVIEW
        line_match = re.search(r"(?<!\d)([+-]\d+(?:[.,]\d+)?)", text)
        names_home = _selection_names_team(selection, event.home)
        names_away = _selection_names_team(selection, event.away)
        if (
            line_match is None
            or names_home == names_away
            or identity.line is None
        ):
            return REVIEW
        line = float(line_match.group(1).replace(",", "."))
        expected_line = identity.line if names_home else -identity.line
        if not math.isclose(
            line, expected_line, rel_tol=0.0, abs_tol=1e-9
        ):
            return REVIEW
        if math.isclose(abs(line * 4) % 2, 1.0, abs_tol=1e-9):
            return REVIEW
        selected_score = scores[0] if names_home else scores[1]
        opponent_score = scores[1] if names_home else scores[0]
        adjusted_margin = selected_score + line - opponent_score
        if adjusted_margin == 0:
            return VOID
        return WON if adjusted_margin > 0 else LOST

    scope = identity.scope if identity is not None else "event"
    is_player_market = bool(
        identity is not None
        and (
            scope in {"player", "participant", "player_prop"}
            or identity.participant_id is not None
            or (
                identity.competitor_id is not None
                and identity.team_id is None
            )
        )
    )
    if is_player_market:
        player = _matching_player(context, event)
        if (
            player is None
            or player.minutes is None
            or not math.isfinite(float(player.minutes))
            or player.minutes <= 0
        ):
            return REVIEW
        statistic = _player_stat(context, player)
        if statistic is None:
            return REVIEW
        decision = _comparison(text, statistic)
        if decision is not None:
            return decision
        if any(term in market_text for term in ("anota", "goleador", "goal")):
            return WON if statistic >= 1 else LOST
        return REVIEW

    if period in {"first_half", "first half", "1st_half"} and any(
        term in context
        for term in (
            "corner",
            "esquina",
            "remate",
            "tiro",
            "falta",
            "foul",
            "offside",
            "fuera de juego",
            "tarjeta",
            "card",
        )
    ):
        return REVIEW

    detailed_markers = (
        "tiros de esquina", "corner", "remates a puerta", "tiros a puerta",
        "remates", "tiros totales", "total shots", "falta", "foul",
        "fuera de juego", "offside", "tarjeta amarilla", "yellow card",
        "tarjeta roja", "red card",
    )
    if any(term in context for term in detailed_markers):
        detailed_stat = _team_or_event_stat(
            context, event, scope or "event"
        )
        if detailed_stat is None:
            return REVIEW
        return _comparison(text, detailed_stat) or REVIEW

    if scores is not None and (
        "ambos equipos anotan" in context or "btts" in context
    ):
        both_scored = scores[0] > 0 and scores[1] > 0
        wants_no = text.strip() in {"no", "no anotan"} or bool(
            re.search(r"(?:no|: no)\s*$", text)
        )
        return WON if (not both_scored if wants_no else both_scored) else LOST

    if scores is not None and any(
        term in context for term in ("gol", "carrera", " run", "runs")
    ):
        score_total = sum(scores)
        if scope in {"team", "team_total"}:
            team_score = _team_value(context, event, *scores)
            if team_score is None:
                return REVIEW
            score_total = team_score
        decision = _comparison(text, score_total)
        if decision is not None:
            return decision

    if scores is not None and text.strip() in {"1x", "x2"}:
        if text.strip() == "1x":
            return WON if scores[0] >= scores[1] else LOST
        return WON if scores[1] >= scores[0] else LOST

    if scores is not None and any(
        term in market_text for term in ("doble oportunidad", "double chance")
    ):
        names_home = _selection_names_team(selection, event.home)
        names_away = _selection_names_team(selection, event.away)
        if names_home == names_away:
            return REVIEW
        if names_home:
            return WON if scores[0] >= scores[1] else LOST
        return WON if scores[1] >= scores[0] else LOST

    if scores is not None and any(
        term in market_text
        for term in ("empate no apuesta", "draw no bet", "dnb")
    ):
        if scores[0] == scores[1]:
            return VOID
        return _grade_h2h(selection, event, scores)

    if scores is not None and any(
        term in market_text
        for term in ("resultado", "ganador", "moneyline", "1x2")
    ):
        return _grade_h2h(selection, event, scores)

    if scores is not None and any(
        term in context for term in ("handicap", "spread", "run line")
    ):
        line_match = re.search(r"(?<!\d)([+-]\d+(?:[.,]\d+)?)", text)
        names_home = _selection_names_team(selection, event.home)
        names_away = _selection_names_team(selection, event.away)
        if line_match is None or names_home == names_away:
            return REVIEW
        line = float(line_match.group(1).replace(",", "."))
        if math.isclose(abs(line * 4) % 2, 1.0, abs_tol=1e-9):
            return REVIEW
        selected_score = scores[0] if names_home else scores[1]
        opponent_score = scores[1] if names_home else scores[0]
        adjusted_margin = selected_score + line - opponent_score
        if adjusted_margin == 0:
            return VOID
        return WON if adjusted_margin > 0 else LOST

    if identity is not None and identity.market_key.startswith(
        "playdoit_market:"
    ):
        return REVIEW

    if any(term in text for term in (
        "1er inning", "primer inning", "primera entrada", "first inning",
        "primera mitad", "primer tiempo", "1er tiempo", "first half",
        "primer cuarto", "first quarter", "team total", "total del equipo",
    )):
        return REVIEW

    line_match = re.search(r"(?<!\d)([+-]\d+(?:[.,]\d+)?)", text)
    names_home = _selection_names_team(selection, event.home)
    names_away = _selection_names_team(selection, event.away)
    if line_match and (names_home or names_away) and any(
        term in text for term in ("handicap", "spread", "run line")
    ):
        line = float(line_match.group(1).replace(",", "."))
        if math.isclose(abs(line * 4) % 2, 1.0, abs_tol=1e-9):
            return REVIEW
        selected_score = event.home_score if names_home else event.away_score
        opponent_score = event.away_score if names_home else event.home_score
        adjusted_margin = selected_score + line - opponent_score
        if adjusted_margin == 0:
            return VOID
        return WON if adjusted_margin > 0 else LOST

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

"""Fail-closed public content and deterministic social caption boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, DecimalException, ROUND_HALF_UP
import re
from typing import Mapping
from unicodedata import normalize as normalize_unicode
from uuid import UUID
from zoneinfo import ZoneInfo

from backend.evidence_messaging import format_evidence_support


SOCIAL_PICK_FIELDS = frozenset(
    {
        "id",
        "categoria",
        "partido",
        "pick",
        "cuota",
        "confianza",
        "estado",
        "es_parlay",
        "liga",
        "mercado",
        "riesgo",
        "fecha_generacion",
        "fecha_evento",
        "horario",
        "tiene_valor",
        "visibility",
        "source",
        "source_event_id",
        "source_market_key",
        "source_selection_key",
        "source_observed_at",
        "source_starts_at",
    }
)

_ASCII_DIGITS = re.compile(r"^[0-9]+$")
_FORMATTED_ODDS = re.compile(r"^[1-9][0-9]*[.][0-9]{2}$")
_ISO_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:[.][0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_AUDIT_LIMITS = {
    "source": 100,
    "source_event_id": 500,
    "source_market_key": 1000,
    "source_selection_key": 500,
}
_MEXICO_CITY = ZoneInfo("America/Mexico_City")
_SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_FACEBOOK_HASHTAGS = "#ReyTacoPicks #ApuestasResponsables"
_INSTAGRAM_HASHTAGS = (
    "#ReyTacoPicks #ApuestasResponsables #PronósticosDeportivos #Deportes"
)
_UNSAFE_CAPTION_WORDING = (
    re.compile(r"\b(?:por\s+ciento|porcentajes?|percent(?:age)?s?)\b"),
    re.compile(r"\b(?:garant|guarant)\w*\b"),
    re.compile(r"\bsin\s+riesgo\b"),
    re.compile(r"\b(?:patrocin\w*|sponsor\w*)\b"),
    re.compile(r"\b(?:promes\w*|promet\w*|promis\w*)\b"),
    re.compile(r"\bdemo\s+no\s+vigente\b"),
)
_PROMOTIONAL_CONTENT_SUBJECTS = (
    re.compile(
        r"\b(?:this|that|these|those|the|my|your|his|her|its|our|their)\s+"
        r"(?:picks?|bets?|selections?)\b"
    ),
    re.compile(
        r"\b(?:este|esta|estos|estas|el|la|los|las|mi|mis|tu|tus|"
        r"su|sus|nuestro|nuestra|nuestros|nuestras)\s+"
        r"(?:picks?|apuestas?|selecci[oó]n|selecciones|pron[oó]sticos?)\b"
    ),
)
_PROBABILITY_CLAIM_WORDING = (
    re.compile(
        r"\b(?:probabilit(?:y|ies)|probabl(?:e|y)|likelihood|likely|expected|"
        r"sure(?:ly)?|certain(?:ly|ty)?)\b"
    ),
    re.compile(
        r"\b(?:probabilidad(?:es)?|probable(?:s|mente)?|esperad[oa]s?|"
        r"segur(?:[oa]s?|amente|idad)|ciert(?:[oa]s?|amente)|certeza)\b"
    ),
)
_CHANCE_OF_WIN_WORDING = (
    re.compile(r"\bchances?\s+(?:to\s+win|of\s+winning|de\s+ganar)\b"),
    re.compile(r"\bposibilidad(?:es)?\s+de\s+ganar\b"),
)
_ENGLISH_POSSIBILITY_OUTCOME = (
    r"(?:win(?:ning)?|be(?:\s+\w+){0,2}\s+winners?)"
)
_ENGLISH_POSSIBILITY_WORDING = (
    re.compile(
        rf"\b(?:may|might|could|can)(?:\s+\w+){{0,3}}\s+"
        rf"{_ENGLISH_POSSIBILITY_OUTCOME}\b"
    ),
    re.compile(
        r"\bpossibilit(?:y|ies)\s+(?:of|to)\s+(?:win|winning)\b"
    ),
)
_SPANISH_POSSIBILITY_WORDING = (
    re.compile(
        r"\b(?:puede|pueden|podr[ií]a|podr[ií]an)"
        r"(?:\s+\w+){0,3}\s+ganar\b"
    ),
    re.compile(
        r"\b(?:posible|probable)mente(?:\s+\w+){0,2}\s+"
        r"(?:gane|ganar(?:á|án))\b"
    ),
)
_RECIPIENT_WINNER_WORDING = (
    re.compile(
        r"\b(?:(?:you|we|they)(?:\s+\w+){0,2}\s+are|"
        r"i(?:\s+\w+){0,2}\s+am|(?:he|she)(?:\s+\w+){0,2}\s+is)\s+"
        r"(?:(?:a|the)\s+)?winners?\b"
    ),
    re.compile(
        r"\b(?:t[uú]\s+)?eres\s+(?:(?:un|una|el|la)\s+)?"
        r"ganador(?:a|es|as)?\b"
    ),
    re.compile(
        r"\b(?:(?:nosotros|nosotras)\s+)?somos\s+"
        r"(?:(?:un|una|el|la|los|las)\s+)?ganador(?:a|es|as)?\b"
    ),
    re.compile(
        r"\b(?:usted(?:es)?|ellos|ellas)\s+(?:es|son)\s+"
        r"(?:(?:un|una|el|la|los|las)\s+)?ganador(?:a|es|as)?\b"
    ),
)
_ENGLISH_WIN_OUTCOME = r"(?:win|be(?:\s+\w+){0,2}\s+winners?)"
_FUTURE_WIN_WORDING = (
    re.compile(
        rf"\b(?:will|should|must)(?:\s+\w+){{0,3}}\s+"
        rf"{_ENGLISH_WIN_OUTCOME}\b"
    ),
    re.compile(
        rf"\bgoing\s+to(?:\s+\w+){{0,3}}\s+{_ENGLISH_WIN_OUTCOME}\b"
    ),
    re.compile(r"\b(?:va|van)\s+a(?:\s+\w+){0,3}\s+ganar\b"),
    re.compile(r"\bganar(?:á|án)\b"),
    re.compile(r"\bdeber[ií]a(?:n)?(?:\s+\w+){0,2}\s+ganar\b"),
    re.compile(r"\bser(?:á|án)(?:\s+\w+){0,2}\s+ganador(?:a|es|as)?\b"),
    re.compile(r"\bprobable\s+que\s+gane\b"),
)
_PREDICTIVE_CAPTION_RULES = (
    _PROMOTIONAL_CONTENT_SUBJECTS,
    _PROBABILITY_CLAIM_WORDING,
    _CHANCE_OF_WIN_WORDING,
    _ENGLISH_POSSIBILITY_WORDING,
    _SPANISH_POSSIBILITY_WORDING,
    _RECIPIENT_WINNER_WORDING,
    _FUTURE_WIN_WORDING,
)


@dataclass(frozen=True)
class SocialContent:
    pick_id: str
    category: str
    event: str
    selection: str
    odds_text: str
    schedule: str
    observed_at: datetime
    starts_at: datetime
    league: str
    market: str
    risk_label: str
    evidence_label: str
    has_value_signal: bool
    is_demo: bool = False

    def object_key(self, *, batch_id: str) -> str:
        if not isinstance(batch_id, str) or batch_id != batch_id.lower():
            raise ValueError("batch_id must be a canonical UUID")
        try:
            normalized_batch_id = str(UUID(batch_id))
        except (AttributeError, TypeError, ValueError):
            raise ValueError("batch_id must be a canonical UUID") from None
        if normalized_batch_id != batch_id:
            raise ValueError("batch_id must be a canonical UUID")
        if not isinstance(self.pick_id, str) or _ASCII_DIGITS.fullmatch(
            self.pick_id
        ) is None:
            raise ValueError("pick_id must contain ASCII digits only")
        return f"daily/{normalized_batch_id}/{self.pick_id}.jpg"


@dataclass(frozen=True)
class SocialCaptions:
    facebook: str
    instagram: str


def _utc_reference(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("reference_at must be timezone-aware")
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError):
        offset = None
    if value.tzinfo is None or offset is None:
        raise ValueError("reference_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _normalized_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a nonblank string")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field} must be a nonblank string")
    return normalized


def _matches_any_rule(
    value: str,
    rule_groups: tuple[tuple[re.Pattern[str], ...], ...],
) -> bool:
    return any(
        pattern.search(value) is not None
        for rule_group in rule_groups
        for pattern in rule_group
    )


def _validate_caption_fact(value: object, *, field: str) -> None:
    normalized = _normalized_text(value, field=field)
    if normalized != value:
        raise ValueError(f"{field} must be normalized for a social caption")
    folded = normalize_unicode("NFKC", normalized).casefold()
    has_unsafe_wording = any(
        pattern.search(folded) is not None for pattern in _UNSAFE_CAPTION_WORDING
    )
    has_predictive_wording = _matches_any_rule(folded, _PREDICTIVE_CAPTION_RULES)
    if (
        "%" in folded
        or "#" in folded
        or has_unsafe_wording
        or has_predictive_wording
    ):
        raise ValueError(f"{field} contains unsafe social caption wording")


def _pick_id(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("id must contain ASCII digits only")
    if isinstance(value, int):
        normalized = str(value)
    elif isinstance(value, str):
        normalized = value
    else:
        raise ValueError("id must contain ASCII digits only")
    if _ASCII_DIGITS.fullmatch(normalized) is None:
        raise ValueError("id must contain ASCII digits only")
    return normalized


def _utc_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str) or _ISO_TIMESTAMP.fullmatch(value) is None:
        raise ValueError(f"{field} must be an ISO timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(
            f"{field} must be an ISO timezone-aware timestamp"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be an ISO timezone-aware timestamp")
    return parsed.astimezone(timezone.utc)


def _odds_text(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise ValueError("cuota must be finite decimal odds greater than 1")
    try:
        raw = value.strip() if isinstance(value, str) else str(value)
        decimal_odds = Decimal(raw)
        if not decimal_odds.is_finite() or decimal_odds <= Decimal("1"):
            raise ValueError("cuota must be finite decimal odds greater than 1")
        rounded = decimal_odds.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rounded <= Decimal("1"):
            raise ValueError("cuota must render above 1.00")
    except (DecimalException, ValueError):
        raise ValueError("cuota must be finite decimal odds greater than 1") from None
    return format(rounded, ".2f")


def _validate_odds_text(value: object) -> None:
    if (
        not isinstance(value, str)
        or _FORMATTED_ODDS.fullmatch(value) is None
        or Decimal(value) <= Decimal("1")
    ):
        raise ValueError("odds_text must be decimal odds above 1.00 with two places")


def content_from_public_pick(
    row: Mapping[str, object], *, reference_at: datetime
) -> SocialContent:
    """Validate and normalize the exact public-pick RPC projection."""

    reference = _utc_reference(reference_at)
    if not isinstance(row, Mapping):
        raise ValueError("row must be exactly one mapping")
    if set(row.keys()) != SOCIAL_PICK_FIELDS:
        raise ValueError("row must contain the exact public pick fields")

    if row["visibility"] != "public":
        raise ValueError("visibility must be exactly public")
    if row["estado"] != "pendiente":
        raise ValueError("estado must be exactly pendiente")
    if row["es_parlay"] is not False:
        raise ValueError("es_parlay must be boolean false")
    if type(row["tiene_valor"]) is not bool:
        raise ValueError("tiene_valor must be boolean")

    normalized = {
        field: _normalized_text(row[field], field=field)
        for field in (
            "categoria",
            "partido",
            "pick",
            "horario",
            "liga",
            "mercado",
            "riesgo",
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
        )
    }
    for field, limit in _AUDIT_LIMITS.items():
        raw_audit = row[field]
        if not isinstance(raw_audit, str) or len(raw_audit.strip()) > limit:
            raise ValueError(f"{field} must be at most {limit} characters")
    _validate_caption_fact(normalized["partido"], field="partido")
    _validate_caption_fact(normalized["pick"], field="pick")

    observed_at = _utc_timestamp(
        row["source_observed_at"],
        field="source_observed_at",
    )
    starts_at = _utc_timestamp(
        row["source_starts_at"],
        field="source_starts_at",
    )
    if observed_at > reference:
        raise ValueError("source_observed_at must not be later than reference_at")
    if starts_at <= observed_at:
        raise ValueError("source_starts_at must be after source_observed_at")
    if starts_at <= reference:
        raise ValueError("source_starts_at must be later than reference_at")

    return SocialContent(
        pick_id=_pick_id(row["id"]),
        category=normalized["categoria"],
        event=normalized["partido"],
        selection=normalized["pick"],
        odds_text=_odds_text(row["cuota"]),
        schedule=normalized["horario"],
        observed_at=observed_at,
        starts_at=starts_at,
        league=normalized["liga"],
        market=normalized["mercado"],
        risk_label=normalized["riesgo"],
        evidence_label=format_evidence_support(row["confianza"]),
        has_value_signal=row["tiene_valor"],
        is_demo=False,
    )


def _observation_label(observed_at: datetime) -> str:
    if not isinstance(observed_at, datetime):
        raise ValueError("observed_at must be timezone-aware")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    local = observed_at.astimezone(_MEXICO_CITY)
    month = _SPANISH_MONTHS[local.month - 1]
    return (
        f"Observado: {local.day} de {month} de {local.year}, "
        f"{local:%H:%M} (hora de Ciudad de México)"
    )


def _caption_lines(content: SocialContent) -> list[str]:
    _validate_caption_fact(content.event, field="event")
    _validate_caption_fact(content.selection, field="selection")
    _validate_odds_text(content.odds_text)
    lines = [
        "Información del pick",
        content.event,
        f"Selección: {content.selection}",
        f"Momio observado: {content.odds_text}",
        _observation_label(content.observed_at),
    ]
    if content.is_demo is True:
        lines.append("DEMO NO VIGENTE")
    elif content.has_value_signal is True:
        lines.append("Señal de valor comparada")
    lines.extend(
        [
            "Consulta: reytacopicks.com",
            "18+ · Apuesta con responsabilidad",
        ]
    )
    return lines


def build_fallback_captions(content: SocialContent) -> SocialCaptions:
    """Build fixed, factual Spanish copy without probabilistic claims."""

    if not isinstance(content, SocialContent):
        raise ValueError("content must be SocialContent")
    base = "\n".join(_caption_lines(content))
    return SocialCaptions(
        facebook=f"{base}\n{_FACEBOOK_HASHTAGS}",
        instagram=f"{base}\n{_INSTAGRAM_HASHTAGS}",
    )


def demo_social_content(*, reference_at: datetime) -> SocialContent:
    """Return a self-contained fictional fixture anchored to one caller clock."""

    reference = _utc_reference(reference_at)
    try:
        starts_at = reference + timedelta(days=30)
    except OverflowError:
        raise ValueError("reference_at must allow a future demo event") from None
    return SocialContent(
        pick_id="9000000000000000",
        category="Deporte ficticio",
        event="Club Ejemplo Norte vs Club Ejemplo Sur",
        selection="Club Ejemplo Norte gana",
        odds_text="1.90",
        schedule="Evento ficticio sin vigencia",
        observed_at=reference,
        starts_at=starts_at,
        league="Liga de ejemplo",
        market="Ganador del partido",
        risk_label="Riesgo no aplicable",
        evidence_label=format_evidence_support(None),
        has_value_signal=False,
        is_demo=True,
    )

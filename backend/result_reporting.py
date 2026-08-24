"""Deterministic, evidence-backed evening and final result reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Literal, Mapping, Sequence
from uuid import UUID


ReportKind = Literal["evening", "final"]
ALLOWED_STATES = frozenset(
    {"pendiente", "ganado", "perdido", "void", "revision_pendiente"}
)
SETTLED_STATES = frozenset({"ganado", "perdido", "void"})
REPORTABLE_STATES = SETTLED_STATES | {"revision_pendiente"}
STATE_ICON = {
    "ganado": "✅",
    "perdido": "❌",
    "void": "↩️",
    "revision_pendiente": "🟡",
    "pendiente": "⏳",
}
_EVIDENCE_FIELDS = (
    "resultado_fuente",
    "resultado_evento_id",
    "resultado_marcador",
    "resultado_verificado_at",
)


@dataclass(frozen=True)
class ResultReport:
    batch_id: str
    portfolio_date: str
    kind: ReportKind
    rows: tuple[Mapping[str, object], ...]
    eligible: bool
    terminal: bool
    record: str
    digest: str
    telegram: str
    facebook: str
    instagram: str


def build_result_report(
    rows: Sequence[Mapping[str, object]],
    *,
    kind: ReportKind,
) -> ResultReport:
    """Return one immutable report from exactly one six-pick portfolio."""
    if kind not in ("evening", "final"):
        raise ValueError("report kind must be evening or final")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or len(rows) != 6:
        raise ValueError("result report requires six rows")

    normalized = tuple(_normalize_row(row) for row in rows)
    pick_ids = [row["id"] for row in normalized]
    if any(type(value) is not int for value in pick_ids) or len(set(pick_ids)) != 6:
        raise ValueError("result report requires six unique integer pick ids")

    batch_ids = {str(row["batch_id"]) for row in normalized}
    if len(batch_ids) != 1:
        raise ValueError("result report rows must share one batch")
    batch_id = batch_ids.pop()
    _canonical_uuid(batch_id)

    portfolio_dates = {str(row["portfolio_date"]) for row in normalized}
    if len(portfolio_dates) != 1:
        raise ValueError("result report rows must share one portfolio date")
    portfolio_date = portfolio_dates.pop()
    _canonical_date(portfolio_date)

    reportable_rows = tuple(
        row for row in normalized if row["estado"] in REPORTABLE_STATES
    )
    if not reportable_rows:
        raise ValueError("evening report requires at least one verified row")
    terminal = all(row["estado"] in SETTLED_STATES for row in normalized)
    if kind == "final" and not terminal:
        raise ValueError("final report requires six settled rows")

    wins = sum(row["estado"] == "ganado" for row in reportable_rows)
    losses = sum(row["estado"] == "perdido" for row in reportable_rows)
    voids = sum(row["estado"] == "void" for row in reportable_rows)
    reviews = sum(row["estado"] == "revision_pendiente" for row in reportable_rows)
    record = f"{wins}-{losses}"

    heading = (
        "👑 REY TACO PICKS · CIERRE VERIFICADO"
        if kind == "final"
        else "👑 REY TACO PICKS · REPORTE VESPERTINO"
    )
    lines = [heading, "", f"📊 {len(reportable_rows)} verificados · Récord {record}"]
    detail = []
    if voids:
        detail.append(f"{voids} void")
    if reviews:
        detail.append(f"{reviews} en revisión")
    if detail:
        lines.append(" · ".join(detail))
    if not terminal:
        pending = 6 - len(reportable_rows)
        if pending:
            lines.append(f"⏳ {pending} selecciones pendientes")
    lines.append("")
    for row in reportable_rows:
        lines.append(
            f"{STATE_ICON[str(row['estado'])]} {row['partido']} ➜ "
            f"{row['pick']} @ {row['cuota']}"
        )
    lines.extend(
        (
            "",
            "Resultados respaldados por fuentes verificadas.",
            "🌐 Historial completo: reytacopicks.com",
            "18+ · Apuesta con responsabilidad",
        )
    )
    telegram = "\n".join(lines)
    digest = _report_digest(reportable_rows)
    facebook = f"{telegram}\n\n#ReyTacoPicks #ResultadosVerificados"
    instagram = (
        f"{telegram}\n\n"
        "#ReyTacoPicks #ResultadosVerificados #ApuestasResponsables"
    )
    return ResultReport(
        batch_id=batch_id,
        portfolio_date=portfolio_date,
        kind=kind,
        rows=tuple(MappingProxyType(dict(row)) for row in reportable_rows),
        eligible=True,
        terminal=terminal,
        record=record,
        digest=digest,
        telegram=telegram,
        facebook=facebook,
        instagram=instagram,
    )


def _normalize_row(row: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(row, Mapping):
        raise ValueError("result report row must be a mapping")
    required = {
        "id",
        "batch_id",
        "portfolio_date",
        "partido",
        "pick",
        "cuota",
        "estado",
        *_EVIDENCE_FIELDS,
    }
    if not required.issubset(row):
        raise ValueError("result report row is missing required fields")
    normalized = dict(row)
    state = row["estado"]
    if not isinstance(state, str) or state not in ALLOWED_STATES:
        raise ValueError("result report row has an invalid state")
    normalized["estado"] = state
    for field in ("partido", "pick"):
        normalized[field] = _bounded_text(row[field], field=field, limit=500)
    normalized["cuota"] = _decimal_odds(row["cuota"])
    if state in REPORTABLE_STATES:
        for field in _EVIDENCE_FIELDS:
            normalized[field] = _bounded_text(row[field], field=field, limit=500)
        _verified_timestamp(str(normalized["resultado_verificado_at"]))
    elif any(row[field] not in (None, "") for field in _EVIDENCE_FIELDS):
        raise ValueError("pending row must not contain result evidence")
    return normalized


def _bounded_text(value: object, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"verified row requires {field}")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > limit:
        raise ValueError(f"verified row requires {field}")
    return normalized


def _decimal_odds(value: object) -> str:
    if isinstance(value, bool):
        raise ValueError("result report odds must be decimal above 1")
    try:
        odds = Decimal(str(value))
        if not odds.is_finite() or odds <= Decimal("1"):
            raise ValueError
        return format(odds.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")
    except (DecimalException, TypeError, ValueError):
        raise ValueError("result report odds must be decimal above 1") from None


def _canonical_uuid(value: str) -> None:
    try:
        if str(UUID(value)) != value:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ValueError("result report batch_id must be a canonical UUID") from None


def _canonical_date(value: str) -> None:
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("result report portfolio date must be ISO format") from None


def _verified_timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("verified row requires resultado_verificado_at") from None


def _report_digest(rows: tuple[dict[str, object], ...]) -> str:
    payload = [
        (row["id"], row["estado"], row["resultado_verificado_at"])
        for row in rows
    ]
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

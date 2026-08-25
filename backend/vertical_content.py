"""Immutable, audited packages for vertical social media."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from hashlib import sha256
from typing import Literal
from unicodedata import category as unicode_category
import re

from backend.result_reporting import ResultReport
from backend.social_repository import MetaSocialBatch


StoryKind = Literal[
    "public_pick_story",
    "vip_teaser_story",
    "final_results_story",
    "verified_result_story",
    "ticket_evidence_story",
    "reel_cta_story",
]

_TEMPLATE_VERSIONS: dict[StoryKind, int] = {
    "public_pick_story": 1,
    "vip_teaser_story": 1,
    "final_results_story": 2,
    "verified_result_story": 2,
    "ticket_evidence_story": 1,
    "reel_cta_story": 2,
}
_DAILY_REEL_TEMPLATE_VERSION = 2


@dataclass(frozen=True, slots=True)
class VerticalRow:
    pick_id: int | None
    event: str
    selection: str
    odds: str
    state: str = ""
    score: str = ""


@dataclass(frozen=True, slots=True)
class VerticalCard:
    kind: StoryKind
    batch_id: str
    portfolio_date: str
    headline: str
    subtitle: str
    rows: tuple[VerticalRow, ...]
    cta: str
    digest: str
    template_version: int = 1
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReelPackage:
    batch_id: str
    portfolio_date: str
    digest: str
    caption: str
    template_version: int = 1
    kind: Literal["daily_results_reel"] = "daily_results_reel"


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _card(
    *,
    kind: StoryKind,
    batch_id: str,
    portfolio_date: str,
    headline: str,
    subtitle: str,
    rows: tuple[VerticalRow, ...],
    cta: str,
    provenance: tuple[str, ...] = (),
) -> VerticalCard:
    template_version = _TEMPLATE_VERSIONS[kind]
    payload = {
        "kind": kind,
        "batch_id": batch_id,
        "portfolio_date": portfolio_date,
        "headline": headline,
        "subtitle": subtitle,
        "rows": [asdict(row) for row in rows],
        "cta": cta,
        "template_version": template_version,
        "provenance": list(provenance),
    }
    return VerticalCard(
        kind=kind,
        batch_id=batch_id,
        portfolio_date=portfolio_date,
        headline=headline,
        subtitle=subtitle,
        rows=rows,
        cta=cta,
        digest=_canonical_digest(payload),
        template_version=template_version,
        provenance=provenance,
    )


def build_public_pick_story(
    batch: MetaSocialBatch,
    *,
    portfolio_date: str,
) -> VerticalCard:
    content = batch.content
    rows = (
        VerticalRow(
            pick_id=int(content.pick_id),
            event=content.event,
            selection=content.selection,
            odds=content.odds_text,
        ),
    )
    return _card(
        kind="public_pick_story",
        batch_id=batch.batch_id,
        portfolio_date=portfolio_date,
        headline="PICK PÚBLICO DEL DÍA",
        subtitle=content.schedule,
        rows=rows,
        cta="Consulta la cartelera · reytacopicks.com",
    )


def build_vip_teaser_story(
    batch: MetaSocialBatch,
    *,
    portfolio_date: str,
) -> VerticalCard:
    return _card(
        kind="vip_teaser_story",
        batch_id=batch.batch_id,
        portfolio_date=portfolio_date,
        headline="CARTELERA VIP LISTA",
        subtitle="6 selecciones analizadas · 4 selecciones adicionales en VIP",
        rows=(),
        cta="Acceso VIP · reytacopicks.com",
    )


def _require_final_report(report: ResultReport, *, error: str) -> None:
    if (
        not isinstance(report, ResultReport)
        or not report.eligible
        or report.kind != "final"
        or not report.terminal
        or len(report.rows) != 6
    ):
        raise ValueError(error)


def build_final_results_story(report: ResultReport) -> VerticalCard:
    _require_final_report(
        report,
        error="vertical result story requires a final six-pick report",
    )
    rows = tuple(
        VerticalRow(
            pick_id=int(row["id"]),
            event=str(row["partido"]),
            selection=str(row["pick"]),
            odds=str(row["cuota"]),
            state=str(row["estado"]),
            score=str(row["resultado_marcador"]),
        )
        for row in report.rows
    )
    return _card(
        kind="final_results_story",
        batch_id=report.batch_id,
        portfolio_date=report.portfolio_date,
        headline="CIERRE VERIFICADO",
        subtitle=f"Resultados completos · Récord {report.record}",
        rows=rows,
        cta="Historial completo · reytacopicks.com",
    )


def build_verified_result_story(report: ResultReport, *, pick_id: int) -> VerticalCard:
    summary = build_final_results_story(report)
    rows = tuple(row for row in summary.rows if row.pick_id == pick_id)
    if len(rows) != 1:
        raise ValueError("verified result story requires one known pick")
    if rows[0].state != "ganado":
        raise ValueError("verified result story requires a winning pick")
    return _card(
        kind="verified_result_story",
        batch_id=report.batch_id,
        portfolio_date=report.portfolio_date,
        headline="RESULTADO VERIFICADO",
        subtitle="La corona acertó",
        rows=rows,
        cta="Mira los 6 resultados · reytacopicks.com",
    )


def build_ticket_evidence_card(
    report: ResultReport,
    *,
    evidence_id: str,
    media_digest: str,
) -> VerticalCard:
    _require_final_report(report, error="ticket evidence requires a final report")
    _normalize_evidence_id(evidence_id)
    if (
        not isinstance(media_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", media_digest) is None
    ):
        raise ValueError("ticket evidence identity is invalid")
    return _card(
        kind="ticket_evidence_story",
        batch_id=report.batch_id,
        portfolio_date=report.portfolio_date,
        headline="EVIDENCIA ORIGINAL",
        subtitle=f"Comprobante · {media_digest[:12]}",
        rows=(),
        cta="Resultados completos · reytacopicks.com",
        provenance=(media_digest,),
    )


def _normalize_evidence_id(evidence_id: str) -> str:
    if not isinstance(evidence_id, str):
        raise ValueError("ticket evidence identity is invalid")
    if any(unicode_category(char).startswith("C") for char in evidence_id):
        raise ValueError("ticket evidence identity is invalid")
    normalized = evidence_id.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("ticket evidence identity is invalid")
    return normalized


def build_reel_cta_story(report: ResultReport) -> VerticalCard:
    _require_final_report(report, error="reel CTA requires a final report")
    rows = (
        VerticalRow(
            pick_id=None,
            event="2 PICKS GRATIS",
            selection="Conoce la calidad antes de entrar",
            odds="",
            state="GRATIS",
        ),
        VerticalRow(
            pick_id=None,
            event="6 PICKS VIP",
            selection="Cartelera completa con seguimiento",
            odds="",
            state="VIP",
        ),
        VerticalRow(
            pick_id=None,
            event="RESULTADOS PÚBLICOS",
            selection="Historial verificable, ganados y perdidos",
            odds="",
            state="CLARO",
        ),
    )
    return _card(
        kind="reel_cta_story",
        batch_id=report.batch_id,
        portfolio_date=report.portfolio_date,
        headline="¿QUIERES LA PRÓXIMA?",
        subtitle="Dos picks públicos · seis selecciones en VIP",
        rows=rows,
        cta="Únete en reytacopicks.com",
    )


def build_daily_reel_package(report: ResultReport) -> ReelPackage:
    summary = build_final_results_story(report)
    caption = (
        f"👑 Cierre verificado · {summary.subtitle}\n"
        "Consulta los seis resultados en reytacopicks.com\n"
        "18+ · Apuesta con responsabilidad"
    )
    payload = {
        "batch_id": report.batch_id,
        "portfolio_date": report.portfolio_date,
        "report_digest": report.digest,
        "caption": caption,
        "template_version": _DAILY_REEL_TEMPLATE_VERSION,
    }
    return ReelPackage(
        batch_id=report.batch_id,
        portfolio_date=report.portfolio_date,
        digest=_canonical_digest(payload),
        caption=caption,
        template_version=_DAILY_REEL_TEMPLATE_VERSION,
    )

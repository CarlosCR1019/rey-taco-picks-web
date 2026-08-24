"""Immutable, audited packages for vertical social media."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from hashlib import sha256
from typing import Literal

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
) -> VerticalCard:
    template_version = 1
    payload = {
        "kind": kind,
        "batch_id": batch_id,
        "portfolio_date": portfolio_date,
        "headline": headline,
        "subtitle": subtitle,
        "rows": [asdict(row) for row in rows],
        "cta": cta,
        "template_version": template_version,
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
    if report.kind != "final" or not report.terminal:
        raise ValueError(error)


def build_final_results_story(report: ResultReport) -> VerticalCard:
    if report.kind != "final" or not report.terminal or len(report.rows) != 6:
        raise ValueError("vertical result story requires a final six-pick report")
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
    if (
        not isinstance(evidence_id, str)
        or not evidence_id.strip()
        or not isinstance(media_digest, str)
        or len(media_digest) != 64
    ):
        raise ValueError("ticket evidence identity is invalid")
    return _card(
        kind="ticket_evidence_story",
        batch_id=report.batch_id,
        portfolio_date=report.portfolio_date,
        headline="EVIDENCIA ORIGINAL",
        subtitle=f"Ticket {evidence_id} · {media_digest[:12]}",
        rows=(),
        cta="Resultados completos · reytacopicks.com",
    )


def build_reel_cta_story(report: ResultReport) -> VerticalCard:
    _require_final_report(report, error="reel CTA requires a final report")
    return _card(
        kind="reel_cta_story",
        batch_id=report.batch_id,
        portfolio_date=report.portfolio_date,
        headline="¿QUIERES LA PRÓXIMA CARTELERA?",
        subtitle="Dos picks públicos · seis selecciones en VIP",
        rows=(),
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
        "template_version": 1,
    }
    return ReelPackage(
        batch_id=report.batch_id,
        portfolio_date=report.portfolio_date,
        digest=_canonical_digest(payload),
        caption=caption,
    )

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import re

import pytest

from backend.result_reporting import build_result_report
from backend.vertical_content import (
    VerticalCard,
    VerticalRow,
    build_daily_reel_package,
    build_final_results_story,
    build_public_pick_story,
    build_reel_cta_story,
    build_ticket_evidence_card,
    build_verified_result_story,
    build_vip_teaser_story,
)
from tests.test_result_reporting import rows_with_states
from tests.test_social_poster import batch


PORTFOLIO_DATE = "2026-08-24"
MEDIA_DIGEST = "a" * 64


def final_report(*states: str):
    return build_result_report(
        rows_with_states(*(states or ("ganado",) * 6)),
        kind="final",
    )


def test_public_pick_story_contains_one_row_and_a_sha256_digest():
    story = build_public_pick_story(batch(), portfolio_date=PORTFOLIO_DATE)

    assert story.kind == "public_pick_story"
    assert len(story.rows) == 1
    assert re.fullmatch(r"[0-9a-f]{64}", story.digest)
    assert story.rows[0].pick_id == 321


def test_vip_teaser_story_preserves_premium_privacy():
    source = batch()

    story = build_vip_teaser_story(source, portfolio_date=PORTFOLIO_DATE)

    assert story.kind == "vip_teaser_story"
    assert story.rows == ()
    assert "4 selecciones adicionales" in story.subtitle
    assert source.content.event not in story.headline
    assert source.content.event not in story.subtitle
    assert source.content.selection not in story.headline
    assert source.content.selection not in story.subtitle
    assert len(story.digest) == 64


def test_final_and_verified_result_stories_keep_report_identity():
    report = final_report()

    final_story = build_final_results_story(report)
    verified_story = build_verified_result_story(report, pick_id=int(report.rows[0]["id"]))

    assert final_story.kind == "final_results_story"
    assert len(final_story.rows) == 6
    assert verified_story.kind == "verified_result_story"
    assert len(verified_story.rows) == 1
    assert final_story.batch_id == verified_story.batch_id == report.batch_id


def test_final_results_story_rejects_non_final_reports():
    report = build_result_report(
        rows_with_states("ganado", "ganado", "pendiente", "pendiente", "pendiente", "pendiente"),
        kind="evening",
    )

    with pytest.raises(ValueError, match="final"):
        build_final_results_story(report)


def test_verified_result_story_rejects_an_unknown_pick_id():
    report = final_report()

    with pytest.raises(ValueError, match="known pick"):
        build_verified_result_story(report, pick_id=999)


@pytest.mark.parametrize("state", ["perdido", "void"])
def test_verified_result_story_rejects_known_non_winning_picks(state: str):
    report = final_report(state, *("ganado",) * 5)

    with pytest.raises(ValueError, match="winning pick"):
        build_verified_result_story(report, pick_id=1)


def test_all_public_builders_return_immutable_audited_packages():
    report = final_report()
    public = build_public_pick_story(batch(), portfolio_date=PORTFOLIO_DATE)
    teaser = build_vip_teaser_story(batch(), portfolio_date=PORTFOLIO_DATE)
    summary = build_final_results_story(report)
    verified = build_verified_result_story(report, pick_id=1)
    evidence = build_ticket_evidence_card(
        report,
        evidence_id="ticket-1",
        media_digest=MEDIA_DIGEST,
    )
    reel_cta = build_reel_cta_story(report)
    reel = build_daily_reel_package(report)

    assert isinstance(public, VerticalCard)
    assert isinstance(teaser, VerticalCard)
    assert isinstance(summary, VerticalCard)
    assert isinstance(verified, VerticalCard)
    assert isinstance(evidence, VerticalCard)
    assert isinstance(reel_cta, VerticalCard)
    assert reel.kind == "daily_results_reel"
    assert "18+ · Apuesta con responsabilidad" in reel.caption
    assert re.fullmatch(r"[0-9a-f]{64}", reel.digest)
    assert all(re.fullmatch(r"[0-9a-f]{64}", card.digest) for card in (
        public,
        teaser,
        summary,
        verified,
        evidence,
        reel_cta,
    ))
    with pytest.raises(FrozenInstanceError):
        public.headline = "mutated"
    with pytest.raises(FrozenInstanceError):
        public.rows[0].event = "mutated"
    assert isinstance(public.rows[0], VerticalRow)
    with pytest.raises(FrozenInstanceError):
        reel.caption = "mutated"


def test_digests_are_deterministic_and_sensitive_to_relevant_inputs():
    first = build_public_pick_story(batch(), portfolio_date=PORTFOLIO_DATE)
    same = build_public_pick_story(batch(), portfolio_date=PORTFOLIO_DATE)
    changed = build_public_pick_story(batch(), portfolio_date="2026-08-25")

    assert first == same
    assert first.digest == same.digest
    assert first.digest != changed.digest


def test_ticket_evidence_retains_full_media_digest_but_displays_prefix():
    report = final_report()
    same_prefix = "a" * 12 + "b" * 52
    other_suffix = "a" * 12 + "c" * 52

    first = build_ticket_evidence_card(
        report,
        evidence_id="ticket-1",
        media_digest=same_prefix,
    )
    second = build_ticket_evidence_card(
        report,
        evidence_id="ticket-1",
        media_digest=other_suffix,
    )

    assert first.subtitle == second.subtitle == "Comprobante · aaaaaaaaaaaa"
    assert first.provenance == (same_prefix,)
    assert second.provenance == (other_suffix,)
    assert first.digest != second.digest
    assert first == build_ticket_evidence_card(
        report,
        evidence_id="ticket-1",
        media_digest=same_prefix,
    )


def test_ticket_evidence_identity_is_stable_across_local_and_telegram_sources():
    report = final_report()

    local = build_ticket_evidence_card(
        report,
        evidence_id="ticket_1787585449.jpg",
        media_digest=MEDIA_DIGEST,
    )
    telegram = build_ticket_evidence_card(
        report,
        evidence_id="telegram-file-unique-id",
        media_digest=MEDIA_DIGEST,
    )

    assert local.digest == telegram.digest
    assert local.provenance == telegram.provenance == (MEDIA_DIGEST,)


@pytest.mark.parametrize(
    "media_digest",
    ["A" * 64, "g" * 64, "a" * 63, "a" * 65],
)
def test_ticket_evidence_rejects_non_sha256_media_digests(media_digest: str):
    with pytest.raises(ValueError, match="identity is invalid"):
        build_ticket_evidence_card(
            final_report(), evidence_id="ticket-1", media_digest=media_digest
        )


@pytest.mark.parametrize("evidence_id", ["   ", "ticket\n1", "ticket\x001"])
def test_ticket_evidence_rejects_blank_or_control_evidence_ids(evidence_id: str):
    with pytest.raises(ValueError, match="identity is invalid"):
        build_ticket_evidence_card(
            final_report(), evidence_id=evidence_id, media_digest=MEDIA_DIGEST
        )


def test_ticket_evidence_normalizes_surrounding_evidence_id_whitespace():
    normalized = build_ticket_evidence_card(
        final_report(), evidence_id="  ticket-1  ", media_digest=MEDIA_DIGEST
    )
    canonical = build_ticket_evidence_card(
        final_report(), evidence_id="ticket-1", media_digest=MEDIA_DIGEST
    )

    assert normalized.subtitle == "Comprobante · aaaaaaaaaaaa"
    assert normalized == canonical


def test_ticket_evidence_rejects_excessively_long_evidence_ids():
    with pytest.raises(ValueError, match="identity is invalid"):
        build_ticket_evidence_card(
            final_report(), evidence_id="t" * 129, media_digest=MEDIA_DIGEST
        )


def test_reel_cta_and_daily_reel_require_a_complete_final_six_pick_report():
    report = final_report()

    cta = build_reel_cta_story(report)
    reel = build_daily_reel_package(report)

    assert cta.kind == "reel_cta_story"
    assert cta.headline == "¿QUIERES LA PRÓXIMA?"
    assert len(cta.rows) == 3
    assert [row.event for row in cta.rows] == [
        "2 PICKS GRATIS",
        "6 PICKS VIP",
        "RESULTADOS PÚBLICOS",
    ]
    assert cta.template_version == 2
    assert reel.template_version == 2
    assert "18+ · Apuesta con responsabilidad" in reel.caption
    assert "Consulta los seis resultados en reytacopicks.com" in reel.caption


@pytest.mark.parametrize(
    ("builder", "message"),
    [
        (build_final_results_story, "vertical result story requires a final six-pick report"),
        (lambda report: build_ticket_evidence_card(
            report, evidence_id="ticket-1", media_digest=MEDIA_DIGEST
        ), "ticket evidence requires a final report"),
        (build_reel_cta_story, "reel CTA requires a final report"),
        (build_daily_reel_package, "vertical result story requires a final six-pick report"),
    ],
)
def test_final_builders_reject_terminal_reports_with_fewer_than_six_rows(builder, message):
    malformed = replace(final_report(), rows=final_report().rows[:5])

    with pytest.raises(ValueError, match=re.escape(message)):
        builder(malformed)


@pytest.mark.parametrize(
    ("builder", "message"),
    [
        (build_final_results_story, "vertical result story requires a final six-pick report"),
        (lambda report: build_verified_result_story(report, pick_id=1),
         "vertical result story requires a final six-pick report"),
        (lambda report: build_ticket_evidence_card(
            report, evidence_id="ticket-1", media_digest=MEDIA_DIGEST
        ), "ticket evidence requires a final report"),
        (build_reel_cta_story, "reel CTA requires a final report"),
        (build_daily_reel_package, "vertical result story requires a final six-pick report"),
    ],
)
def test_final_builders_reject_ineligible_final_reports(builder, message):
    ineligible = replace(final_report(), eligible=False)

    with pytest.raises(ValueError, match=re.escape(message)):
        builder(ineligible)


@pytest.mark.parametrize(
    ("builder", "message"),
    [
        (build_final_results_story, "vertical result story requires a final six-pick report"),
        (lambda report: build_verified_result_story(report, pick_id=1),
         "vertical result story requires a final six-pick report"),
        (lambda report: build_ticket_evidence_card(
            report, evidence_id="ticket-1", media_digest=MEDIA_DIGEST
        ), "ticket evidence requires a final report"),
        (build_reel_cta_story, "reel CTA requires a final report"),
        (build_daily_reel_package, "vertical result story requires a final six-pick report"),
    ],
)
def test_final_builders_reject_wrong_report_types(builder, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        builder(object())

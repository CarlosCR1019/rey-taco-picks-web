from __future__ import annotations

import pytest

from backend.result_reporting import build_result_report
from backend.vertical_content import (
    build_final_results_story,
    build_public_pick_story,
    build_verified_result_story,
    build_vip_teaser_story,
)
from tests.test_result_reporting import rows_with_states
from tests.test_social_poster import batch


PORTFOLIO_DATE = "2026-08-24"


def test_public_pick_story_contains_one_row_and_a_sha256_digest():
    story = build_public_pick_story(batch(), portfolio_date=PORTFOLIO_DATE)

    assert story.kind == "public_pick_story"
    assert len(story.rows) == 1
    assert len(story.digest) == 64
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
    report = build_result_report(rows_with_states(*(["ganado"] * 6)), kind="final")

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
    report = build_result_report(rows_with_states(*(["ganado"] * 6)), kind="final")

    with pytest.raises(ValueError, match="known pick"):
        build_verified_result_story(report, pick_id=999)

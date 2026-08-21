from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.pick_selection import build_candidates
from backend.scraper import PipelineResult, run_structured_pipeline


REFERENCE_AT = datetime(2026, 8, 20, 16, 5, tzinfo=timezone.utc)


class FakePublisher:
    def __init__(self, *, created: bool = True, mutate: bool = False):
        self.created = created
        self.mutate = mutate
        self.calls = []

    def publish(self, rows, *, dry_run):
        self.calls.append((rows, dry_run))
        if self.mutate:
            rows[0]["source"] = "fabricated"
            rows[0]["cuota"] = 49.0
        return SimpleNamespace(created=self.created, dry_run=dry_run)


def _rank_first(candidates):
    if not candidates:
        return []
    return [
        {
            "candidate_id": candidates[0].candidate_id,
            "rationale": "Mercado completo y precio observado recientemente.",
        }
    ]


def test_structured_pipeline_publishes_only_catalog_backed_rows(event_fixture):
    publisher = FakePublisher()
    candidate = build_candidates([event_fixture])[0]

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        publisher,
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    assert isinstance(result, PipelineResult)
    assert result.event_count == 1
    assert result.pick_count == 1
    assert result.persisted is True
    assert len(publisher.calls) == 1
    published_rows, published_dry_run = publisher.calls[0]
    assert published_dry_run is False
    assert len(published_rows) == 1
    row = result.picks[0]
    assert row["source"] == candidate.source
    assert row["source_event_id"] == candidate.source_event_id
    assert row["source_market_key"] == 'market:v1:["playdoit","h2h","full_game",null]'
    assert row["source_selection_key"] == candidate.selection_key
    assert row["source_observed_at"] == (
        candidate.observed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    assert row["cuota"] == candidate.price
    assert row["confianza"] == "65% respaldo de datos"
    assert row["riesgo"] == "Datos limitados"
    assert row["tiene_valor"] is False
    assert row["visibility"] == "public"
    assert "razonamiento" not in row
    assert row["es_parlay"] is False
    assert row["fecha_generacion"] == "2026-08-20"
    assert row["fecha_evento"] == candidate.starts_at.date().isoformat()
    assert row["estado"] == "pendiente"
    assert row["ganancia_simulada"] == 0


def test_structured_pipeline_empty_catalog_never_calls_ranker_or_publisher():
    publisher = FakePublisher()
    rank_calls = []

    result = run_structured_pipeline(
        [],
        lambda candidates: rank_calls.append(candidates),
        publisher,
        dry_run=True,
        reference_at=REFERENCE_AT,
    )

    assert result == PipelineResult(0, 0, False, ())
    assert result.picks == ()
    assert rank_calls == []
    assert publisher.calls == []


@pytest.mark.parametrize(
    "ranker",
    [
        lambda _candidates: [
            {
                "candidate_id": "candidate:v1:invented",
                "rationale": "Identificador inexistente que debe ser rechazado.",
            }
        ],
        lambda _candidates: (_ for _ in ()).throw(RuntimeError("ranker secret")),
        lambda _candidates: {"candidate_id": "not-an-array"},
    ],
)
def test_structured_pipeline_invalid_or_failed_ranker_never_publishes(
    event_fixture,
    ranker,
):
    publisher = FakePublisher()

    result = run_structured_pipeline(
        [event_fixture],
        ranker,
        publisher,
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    assert result == PipelineResult(1, 0, False, ())
    assert result.picks == ()
    assert publisher.calls == []


def test_structured_pipeline_detaches_immutable_result_from_publisher_mutation(
    event_fixture,
):
    publisher = FakePublisher(mutate=True)
    candidate = build_candidates([event_fixture])[0]

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        publisher,
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    assert result.picks[0]["source"] == candidate.source
    assert result.picks[0]["cuota"] == candidate.price
    with pytest.raises(TypeError):
        result.picks[0]["source"] = "changed"


def test_structured_pipeline_dry_run_calls_publisher_but_reports_no_persistence(
    event_fixture,
):
    publisher = FakePublisher()

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        publisher,
        dry_run=True,
        reference_at=REFERENCE_AT,
    )

    assert result.pick_count == 1
    assert result.persisted is False
    assert len(publisher.calls) == 1
    assert publisher.calls[0][1] is True


@pytest.mark.parametrize(
    "reference_at",
    [
        datetime(2026, 8, 20, 16, 5),
        "2026-08-20T16:05:00Z",
    ],
)
def test_structured_pipeline_invalid_audit_reference_fails_closed(
    event_fixture,
    reference_at,
):
    publisher = FakePublisher()

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        publisher,
        dry_run=False,
        reference_at=reference_at,
    )

    assert result == PipelineResult(1, 0, False, ())
    assert publisher.calls == []


def test_structured_pipeline_rejects_an_observation_from_the_future(event_fixture):
    publisher = FakePublisher()
    before_observation = (
        event_fixture.observed_at.astimezone(timezone.utc) - timedelta(minutes=1)
    )

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        publisher,
        dry_run=False,
        reference_at=before_observation,
    )

    assert result == PipelineResult(1, 0, False, ())
    assert publisher.calls == []


def test_structured_pipeline_rejects_oversized_source_audit_before_publish(
    event_fixture,
):
    publisher = FakePublisher()
    hostile_event = replace(event_fixture, source="x" * 101)

    result = run_structured_pipeline(
        [hostile_event],
        _rank_first,
        publisher,
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    assert result == PipelineResult(1, 0, False, ())
    assert publisher.calls == []


def test_structured_pipeline_hostile_publication_response_never_claims_persistence(
    event_fixture,
):
    class HostilePublication:
        @property
        def dry_run(self):
            raise RuntimeError("hostile response")

    class HostilePublisher(FakePublisher):
        def publish(self, rows, *, dry_run):
            self.calls.append((rows, dry_run))
            return HostilePublication()

    publisher = HostilePublisher()

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        publisher,
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    assert result.pick_count == 1
    assert result.persisted is False
    assert len(publisher.calls) == 1

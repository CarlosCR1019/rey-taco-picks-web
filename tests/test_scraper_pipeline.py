from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
import pickle
from types import SimpleNamespace

import pytest

from backend.pick_publisher import (
    AuditedBatchPublisher,
    PERSISTED_PICK_COLUMNS,
    SupabaseBatchRepository,
)
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
        return SimpleNamespace(
            run_id=None if dry_run else "run-1",
            batch_id=None if dry_run else "batch-1",
            created=False if dry_run else self.created,
            dry_run=dry_run,
        )


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
    assert row["source_starts_at"] == (
        candidate.starts_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
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


def test_structured_pipeline_rejects_an_event_that_has_already_started(event_fixture):
    publisher = FakePublisher()
    rank_calls = []

    result = run_structured_pipeline(
        [event_fixture],
        lambda candidates: rank_calls.append(candidates),
        publisher,
        dry_run=False,
        reference_at=event_fixture.starts_at,
    )

    assert result == PipelineResult(1, 0, False, ())
    assert rank_calls == []
    assert publisher.calls == []


def test_structured_pipeline_discards_stale_candidates_but_keeps_future_slate(
    event_fixture,
):
    stale_event = replace(
        event_fixture,
        source_event_id="stale-event",
        starts_at=REFERENCE_AT,
    )
    publisher = FakePublisher()
    ranked_catalogs = []

    def rank_future(candidates):
        ranked_catalogs.append(candidates)
        return _rank_first(candidates)

    result = run_structured_pipeline(
        [stale_event, event_fixture],
        rank_future,
        publisher,
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    assert result.event_count == 2
    assert result.pick_count == 1
    assert len(ranked_catalogs) == 1
    assert {candidate.source_event_id for candidate in ranked_catalogs[0]} == {"event-1"}


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


def test_structured_pipeline_hostile_reference_truthiness_fails_closed(
    event_fixture,
):
    class HostileReference:
        def __bool__(self):
            raise RuntimeError("truthiness must not be evaluated")

    publisher = FakePublisher()

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        publisher,
        dry_run=False,
        reference_at=HostileReference(),
    )

    assert result == PipelineResult(1, 0, False, ())
    assert publisher.calls == []


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(
            run_id="run-1", batch_id=None, created=True, dry_run=False
        ),
        SimpleNamespace(
            run_id=None, batch_id="batch-1", created=True, dry_run=False
        ),
        SimpleNamespace(
            run_id="run-1", batch_id="batch-1", created="true", dry_run=False
        ),
        SimpleNamespace(
            run_id="run-1", batch_id="batch-1", created=True, dry_run="false"
        ),
        SimpleNamespace(
            run_id="run-1", batch_id="batch-1", created=True, dry_run=True
        ),
    ],
)
def test_structured_pipeline_malformed_publication_never_claims_persistence(
    event_fixture,
    response,
):
    class ResponsePublisher(FakePublisher):
        def publish(self, rows, *, dry_run):
            self.calls.append((rows, dry_run))
            return response

    publisher = ResponsePublisher()

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        publisher,
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    assert result.pick_count == 1
    assert result.persisted is False


def test_structured_pipeline_accepts_an_idempotent_replay_with_both_ids(
    event_fixture,
):
    publisher = FakePublisher(created=False)

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        publisher,
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    assert result.persisted is True


def test_structured_pipeline_result_is_immutable_pickleable_and_asdict_safe(
    event_fixture,
):
    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        FakePublisher(),
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    restored = pickle.loads(pickle.dumps(result))
    assert restored == result
    json.dumps(asdict(result))
    with pytest.raises(TypeError):
        result.picks[0]["source"] = "changed"


def test_pipeline_result_rejects_an_explicit_pick_count_mismatch():
    with pytest.raises(ValueError, match="invalid pipeline result"):
        PipelineResult(1, 1, False, (), ())


class _RpcRequest:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return SimpleNamespace(data=self.data)


class _FakeSupabaseClient:
    def __init__(self):
        self.calls = []

    def rpc(self, function_name, arguments):
        self.calls.append((function_name, arguments))
        stored = []
        for index, requested in enumerate(arguments["requested_picks"], start=1):
            row = {column: requested.get(column) for column in PERSISTED_PICK_COLUMNS}
            row["id"] = index
            if row["visibility"] == "public":
                row["razonamiento"] = None
            stored.append(row)
        return _RpcRequest(
            {
                "run_id": "run-real",
                "batch_id": "batch-real",
                "created": True,
                "delivery_status": {},
                "picks": stored,
            }
        )


def test_structured_pipeline_real_adapter_reaches_rpc_with_only_db_columns(
    event_fixture,
    tmp_path,
):
    client = _FakeSupabaseClient()
    adapter = AuditedBatchPublisher(
        SupabaseBatchRepository(client, clock=lambda: REFERENCE_AT),
        run_key="run-key-1",
        public_path=tmp_path / "picks.json",
        clock=lambda: REFERENCE_AT,
    )

    result = run_structured_pipeline(
        [event_fixture],
        _rank_first,
        adapter,
        dry_run=False,
        reference_at=REFERENCE_AT,
    )

    assert result.persisted is True
    assert len(client.calls) == 1
    function_name, arguments = client.calls[0]
    assert function_name == "publish_pick_batch"
    requested = arguments["requested_picks"]
    assert len(requested) == 1
    assert set(requested[0]) <= PERSISTED_PICK_COLUMNS
    assert {
        "starts_at",
        "observed_at",
        "market_key",
        "selection_key",
        "line",
        "bookmaker_key",
        "home_team",
        "away_team",
    }.isdisjoint(requested[0])

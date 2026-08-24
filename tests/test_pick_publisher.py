import json
from datetime import datetime, timezone

import pytest

import backend.pick_publisher as pick_publisher
from backend.daily_portfolio import physical_event_key
from backend.pick_publisher import (
    AuditedBatchPublisher,
    DailyPortfolioPublisher,
    DAILY_STAGE_PICK_COLUMNS,
    PERSISTED_PICK_COLUMNS,
    SupabaseBatchRepository,
    publish_batch,
    revalidate_persisted_picks,
    source_hash_for,
)


class FakeRepository:
    def __init__(self, response=None, error=None, public_path=None, resume_response=None):
        self.response = response
        self.error = error
        self.public_path = public_path
        self.resume_response = resume_response
        self.calls = []
        self.resume_calls = []
        self.delivery_calls = []

    def publish(self, run_key, source_hash, picks):
        self.calls.append((run_key, source_hash, picks))
        if self.public_path is not None:
            assert not self.public_path.exists()
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return publish_response(persisted_picks(picks))

    def record_delivery(self, run_id, destination, success, error=""):
        self.delivery_calls.append((run_id, destination, success, error))

    def resume(self, run_key):
        self.resume_calls.append(run_key)
        if self.error is not None:
            raise self.error
        return self.resume_response


def picks():
    return [
        {
            "pick": "Gratis",
            "partido": "Pumas vs Atlas",
            "cuota": 1.8,
            "visibility": "public",
            "es_parlay": False,
            "source": "the-odds-api",
            "source_event_id": "event-public",
            "source_market_key": "h2h|full_time|",
            "source_selection_key": "home",
            "source_observed_at": "2026-08-20T20:00:00+00:00",
            "source_starts_at": "2099-08-21T01:00:00Z",
        },
        {
            "pick": "Solo VIP",
            "partido": "América vs Cruz Azul",
            "cuota": 2.1,
            "visibility": "premium",
            "es_parlay": False,
            "source": "the-odds-api",
            "source_event_id": "event-premium",
            "source_market_key": "h2h|full_time|",
            "source_selection_key": "away",
            "source_observed_at": "2026-08-20T20:00:00Z",
            "source_starts_at": "2099-08-21T03:00:00+00:00",
        },
    ]


def daily_stage_picks():
    return [
        {**row, "physical_event_key": physical_event_key(row)}
        for row in picks()
    ]


def persisted_picks(rows=None):
    rows = picks() if rows is None else rows
    persisted = []
    for index, row in enumerate(rows, start=1):
        stored = {column: row.get(column) for column in PERSISTED_PICK_COLUMNS}
        stored["id"] = index
        if stored["visibility"] == "public":
            stored["razonamiento"] = None
        persisted.append(stored)
    return persisted


def six_persisted_picks(public_indices=(0, 1)):
    rows = []
    for index in range(6):
        rows.append(
            {
                "pick": f"Pick {index}",
                "cuota": 1.80 + index / 100,
                "visibility": (
                    "public" if index in public_indices else "premium"
                ),
                "es_parlay": False,
                "source": "playdoit",
                "source_event_id": f"event-{index}",
                "source_market_key": "h2h|full_time|",
                "source_selection_key": "home",
                "source_observed_at": "2026-08-20T20:00:00Z",
                "source_starts_at": f"2099-08-2{index + 1}T01:00:00Z",
            }
        )
    return persisted_picks(rows)


def publish_response(rows, *, created=True, delivery_status=None):
    return {
        "run_id": "run-1",
        "batch_id": "batch-1",
        "created": created,
        "delivery_status": (
            {"free": {"success": True}}
            if delivery_status is None
            else delivery_status
        ),
        "picks": rows,
    }


def daily_release_response(
    rows,
    delivery_rows,
    *,
    created=True,
    delivery_status=None,
    revision=2,
    feed_eligible=False,
):
    return {
        **publish_response(
            rows,
            created=created,
            delivery_status={} if delivery_status is None else delivery_status,
        ),
        "portfolio_date": "2026-08-23",
        "revision": revision,
        "feed_eligible": feed_eligible,
        "delivery_picks": delivery_rows,
    }


def test_publish_writes_only_public_pick_after_repository_acceptance(tmp_path):
    destination = tmp_path / "public" / "picks.json"
    repository = FakeRepository(public_path=destination)

    result = publish_batch(repository, picks(), "run-1", destination)

    expected_public = persisted_picks()[0]
    expected_public.pop("razonamiento")
    assert json.loads(destination.read_text(encoding="utf-8")) == [expected_public]
    assert repository.calls[0][0] == "run-1"
    assert result.run_id == "run-1"
    assert result.batch_id == "batch-1"
    assert result.created is True
    assert result.delivery_status == {"free": {"success": True}}
    assert [dict(row) for row in result.picks] == persisted_picks()
    assert result.dry_run is False


def test_publish_can_persist_without_writing_public_projection(tmp_path):
    destination = tmp_path / "public" / "picks.json"
    repository = FakeRepository(public_path=destination)

    result = publish_batch(
        repository,
        picks(),
        "run-1",
        destination,
        write_public=False,
    )

    assert result.run_id == "run-1"
    assert repository.calls[0][0] == "run-1"
    assert not destination.exists()


def test_publish_rejects_non_boolean_write_public_before_repository(tmp_path):
    destination = tmp_path / "picks.json"
    repository = FakeRepository()

    with pytest.raises(ValueError, match="write_public"):
        publish_batch(
            repository,
            picks(),
            "run-1",
            destination,
            write_public="false",  # type: ignore[arg-type]
        )

    assert repository.calls == []
    assert not destination.exists()


def test_dry_run_never_calls_repository_or_writes_file(tmp_path):
    destination = tmp_path / "picks.json"
    repository = FakeRepository()

    result = publish_batch(repository, picks(), "run-1", destination, dry_run=True)

    assert repository.calls == []
    assert not destination.exists()
    assert result.run_id is None
    assert result.batch_id is None
    assert result.created is False
    assert result.delivery_status == {}
    assert result.picks == ()
    assert result.dry_run is True


def test_publish_rejects_a_non_boolean_dry_run_without_side_effects(tmp_path):
    destination = tmp_path / "picks.json"
    repository = FakeRepository()

    with pytest.raises(ValueError, match="dry_run"):
        publish_batch(
            repository,
            picks(),
            "run-1",
            destination,
            dry_run="false",  # type: ignore[arg-type]
        )

    assert repository.calls == []
    assert not destination.exists()


@pytest.mark.parametrize("invalid_picks, invalid_run_key", [([], "run-1"), (picks(), "  ")])
def test_dry_run_rejects_invalid_inputs_without_side_effects(
    invalid_picks, invalid_run_key, tmp_path
):
    destination = tmp_path / "picks.json"
    repository = FakeRepository()

    with pytest.raises(ValueError):
        publish_batch(
            repository,
            invalid_picks,
            invalid_run_key,
            destination,
            dry_run=True,
        )

    assert repository.calls == []
    assert not destination.exists()


def test_repository_error_preserves_existing_public_file(tmp_path):
    destination = tmp_path / "picks.json"
    destination.write_text('[{"pick":"existing"}]', encoding="utf-8")
    repository = FakeRepository(error=RuntimeError("database unavailable"))

    with pytest.raises(RuntimeError, match="database unavailable"):
        publish_batch(repository, picks(), "run-1", destination)

    assert destination.read_text(encoding="utf-8") == '[{"pick":"existing"}]'


@pytest.mark.parametrize("existing_content", ['[{"pick":"stale"}]', None])
def test_replay_rewrites_stale_or_missing_public_file_with_current_projection(
    existing_content, tmp_path
):
    destination = tmp_path / "picks.json"
    if existing_content is not None:
        destination.write_text(existing_content, encoding="utf-8")
    stored = persisted_picks()
    repository = FakeRepository(response=publish_response(
        stored,
        created=False,
        delivery_status={"vip": {"success": True}},
    ))

    result = publish_batch(repository, picks(), "run-1", destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == [
        {key: value for key, value in stored[0].items() if key != "razonamiento"}
    ]
    assert result.created is False
    assert result.delivery_status == {"vip": {"success": True}}


def test_replay_uses_persisted_rows_instead_of_new_requested_payload(tmp_path):
    destination = tmp_path / "picks.json"
    stored = persisted_picks()
    requested = picks()
    requested[0]["pick"] = "NEW PUBLIC MUST NOT ESCAPE"
    requested[1]["pick"] = "NEW VIP MUST NOT ESCAPE"
    repository = FakeRepository(response=publish_response(stored, created=False))

    result = publish_batch(repository, requested, "same-run", destination)

    public_rows = json.loads(destination.read_text(encoding="utf-8"))
    assert [row["pick"] for row in public_rows] == ["Gratis"]
    assert "NEW" not in destination.read_text(encoding="utf-8")
    assert [dict(row) for row in result.picks] == stored


def test_persisted_result_is_defensively_immutable(tmp_path):
    stored = persisted_picks()
    response = publish_response(stored)
    result = publish_batch(
        FakeRepository(response=response),
        picks(),
        "run-1",
        tmp_path / "picks.json",
    )

    stored[0]["pick"] = "mutated after publication"

    assert result.picks[0]["pick"] == "Gratis"
    with pytest.raises(TypeError):
        result.picks[0]["pick"] = "mutation"  # type: ignore[index]


def test_local_replacement_failure_preserves_destination_and_removes_temp_file(
    tmp_path, monkeypatch
):
    destination = tmp_path / "picks.json"
    destination.write_text('[{"pick":"existing"}]', encoding="utf-8")
    monkeypatch.setattr(
        pick_publisher.os,
        "replace",
        lambda source, target: (_ for _ in ()).throw(OSError("disk error")),
    )

    with pytest.raises(RuntimeError, match="failed to write public picks file"):
        publish_batch(FakeRepository(), picks(), "run-1", destination)

    assert destination.read_text(encoding="utf-8") == '[{"pick":"existing"}]'
    assert list(tmp_path.glob(".picks.json.*.tmp")) == []


def test_source_hash_is_order_independent_and_content_sensitive():
    first = [{"pick": "Gratis", "visibility": "public", "cuota": 1.8}]
    reordered = [{"cuota": 1.8, "visibility": "public", "pick": "Gratis"}]

    assert source_hash_for(first) == source_hash_for(reordered)
    assert source_hash_for(first) != source_hash_for([{**first[0], "cuota": 1.9}])


class FakeRpc:
    def __init__(self, data):
        self.data = data
        self.execute_calls = 0

    def execute(self):
        self.execute_calls += 1
        return type("Response", (), {"data": self.data})()


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def rpc(self, function_name, arguments):
        self.calls.append((function_name, arguments))
        return FakeRpc(self.responses.pop(0))


@pytest.mark.parametrize("response_data", [
    publish_response(persisted_picks(), delivery_status={}),
    [publish_response(persisted_picks(), created=False, delivery_status={"vip": {}})],
])
def test_supabase_repository_uses_rpc_arguments_and_normalizes_response(response_data):
    client = FakeClient([response_data, None])
    repository = SupabaseBatchRepository(client)
    payload = picks()

    result = repository.publish("run-1", "hash-1", payload)
    repository.record_delivery("run-1", "free", True, "")

    assert result["run_id"] == "run-1"
    assert result["batch_id"] == "batch-1"
    assert client.calls == [
        ("publish_pick_batch", {
            "requested_run_key": "run-1",
            "requested_source_hash": "hash-1",
            "requested_picks": payload,
        }),
        ("record_scraper_delivery", {
            "requested_run_id": "run-1",
            "requested_destination": "free",
            "requested_success": True,
            "requested_error": "",
        }),
    ]


def test_supabase_repository_resume_uses_exact_rpc_argument_and_freezes_rows():
    stored = persisted_picks()
    client = FakeClient([
        publish_response(stored, created=False, delivery_status={"admin": {"success": True}})
    ])
    repository = SupabaseBatchRepository(client)

    result = repository.resume("run-1")
    stored[0]["pick"] = "hostile mutation"

    assert result is not None
    assert result["created"] is False
    assert result["picks"][0]["pick"] == "Gratis"
    assert client.calls == [
        ("resume_pick_batch", {"requested_run_key": "run-1"})
    ]


def test_supabase_repository_resume_accepts_database_null():
    repository = SupabaseBatchRepository(FakeClient([None]))

    assert repository.resume("run-1") is None


@pytest.mark.parametrize(
    "response_data",
    [
        {},
        [],
        publish_response(persisted_picks(), created=True),
        {**publish_response(persisted_picks(), created=False), "picks": []},
    ],
)
def test_supabase_repository_resume_rejects_malformed_or_created_response(
    response_data,
):
    repository = SupabaseBatchRepository(FakeClient([response_data]))

    with pytest.raises(RuntimeError, match="resume_pick_batch"):
        repository.resume("run-1")


def test_audited_publisher_resume_rewrites_public_file_from_persisted_rows(tmp_path):
    destination = tmp_path / "public" / "picks.json"
    destination.parent.mkdir(parents=True)
    destination.write_text('[{"pick":"stale"}]', encoding="utf-8")
    stored = persisted_picks()
    repository = FakeRepository(
        resume_response=publish_response(stored, created=False, delivery_status={})
    )
    publisher = AuditedBatchPublisher(repository, "run-1", destination)

    result = publisher.resume(dry_run=False)

    assert result is not None
    assert result.created is False
    assert [dict(row) for row in result.picks] == stored
    assert json.loads(destination.read_text(encoding="utf-8")) == [
        {key: value for key, value in stored[0].items() if key != "razonamiento"}
    ]


def test_audited_publisher_resume_can_skip_public_projection(tmp_path):
    destination = tmp_path / "public" / "picks.json"
    stored = persisted_picks()
    repository = FakeRepository(
        resume_response=publish_response(stored, created=False, delivery_status={})
    )

    result = AuditedBatchPublisher(repository, "run-1", destination).resume(
        dry_run=False,
        write_public=False,
    )

    assert result is not None
    assert [dict(row) for row in result.picks] == stored
    assert not destination.exists()


def test_audited_publisher_resume_dry_run_never_queries_or_writes(tmp_path):
    destination = tmp_path / "picks.json"
    repository = FakeRepository(
        resume_response=publish_response(persisted_picks(), created=False)
    )

    result = AuditedBatchPublisher(repository, "run-1", destination).resume(
        dry_run=True
    )

    assert result is None
    assert repository.resume_calls == []
    assert not destination.exists()


def test_resume_rejects_a_persisted_2020_event_before_writing_public_file(tmp_path):
    destination = tmp_path / "picks.json"
    stored = persisted_picks()
    stored[0]["source_starts_at"] = "2020-01-02T00:00:00Z"
    repository = FakeRepository(
        resume_response=publish_response(stored, created=False)
    )
    publisher = AuditedBatchPublisher(
        repository,
        "run-1",
        destination,
        clock=lambda: datetime(2026, 8, 21, tzinfo=timezone.utc),
    )

    with pytest.raises(RuntimeError, match="resume_pick_batch"):
        publisher.resume(dry_run=False)

    assert not destination.exists()


def test_fresh_publish_rechecks_clock_after_repository_returns(tmp_path):
    destination = tmp_path / "picks.json"
    expired = False

    class ExpiringRepository(FakeRepository):
        def publish(self, run_key, source_hash, requested):
            nonlocal expired
            response = super().publish(run_key, source_hash, requested)
            expired = True
            return response

    repository = ExpiringRepository()
    with pytest.raises(RuntimeError, match="source audit"):
        AuditedBatchPublisher(
            repository,
            "run-1",
            destination,
            clock=lambda: datetime(
                2099,
                8,
                22 if expired else 20,
                tzinfo=timezone.utc,
            ),
        ).publish(picks(), dry_run=False)

    assert repository.calls
    assert not destination.exists()


@pytest.mark.parametrize(
    "starts_at",
    [
        None,
        "",
        "not-a-datetime",
        "2026-08-21 03:00:00Z",
        "2026-08-21T03:00:00.1234567Z",
        "2026-08-21T03:00:00-06:00",
        "2026-08-20T20:00:00Z",
    ],
)
def test_resume_rejects_missing_malformed_offset_or_non_future_start(
    starts_at, tmp_path
):
    stored = persisted_picks()
    stored[0]["source_starts_at"] = starts_at
    repository = FakeRepository(
        resume_response=publish_response(stored, created=False)
    )

    with pytest.raises(RuntimeError, match="resume_pick_batch"):
        AuditedBatchPublisher(
            repository,
            "run-1",
            tmp_path / "picks.json",
            clock=lambda: datetime(2026, 8, 21, tzinfo=timezone.utc),
        ).resume(dry_run=False)


@pytest.mark.parametrize("response_data", [
    None,
    {},
    [],
    [{"run_id": "run-1"}],
    {"batch_id": "batch-1"},
    {"run_id": "run-1", "batch_id": "batch-1", "delivery_status": {}},
    {"run_id": "run-1", "batch_id": "batch-1", "created": "false", "delivery_status": {}},
    {"run_id": "run-1", "batch_id": "batch-1", "created": "true", "delivery_status": {}},
    {"run_id": "run-1", "batch_id": "batch-1", "created": 0, "delivery_status": {}},
    {"run_id": "run-1", "batch_id": "batch-1", "created": None, "delivery_status": {}},
    {"run_id": "run-1", "batch_id": "batch-1", "created": True, "delivery_status": {}, "picks": {}},
    {"run_id": "run-1", "batch_id": "batch-1", "created": True, "delivery_status": {}, "picks": []},
    publish_response([{**persisted_picks()[0], "unexpected": "hostile"}]),
    publish_response([{**persisted_picks()[0], "id": True}]),
    publish_response([{**persisted_picks()[0], "source_event_id": ""}]),
    publish_response([{**persisted_picks()[0], "source_observed_at": "2026-08-20T14:00:00-06:00"}]),
    publish_response([{**persisted_picks()[0], "visibility": "internal"}]),
    publish_response([{**persisted_picks()[0], "razonamiento": "public secret"}]),
])
def test_supabase_repository_rejects_invalid_publish_response(response_data):
    repository = SupabaseBatchRepository(FakeClient([response_data]))

    with pytest.raises(RuntimeError, match="publish_pick_batch"):
        repository.publish("run-1", "hash-1", picks())


def test_persisted_public_policy_accepts_two_free_picks_in_six_row_batch():
    rows = six_persisted_picks()

    validated = revalidate_persisted_picks(rows)

    assert len(validated) == 6
    assert sum(row["visibility"] == "public" for row in validated) == 2


@pytest.mark.parametrize("public_indices", [(0,), (0, 1, 2)])
def test_persisted_public_policy_rejects_wrong_free_count_for_six(
    public_indices,
):
    with pytest.raises(RuntimeError, match="public policy"):
        revalidate_persisted_picks(six_persisted_picks(public_indices))


def test_persisted_public_policy_rejects_more_than_six_rows():
    rows = six_persisted_picks()
    seventh = dict(rows[-1])
    seventh["id"] = 7
    seventh["source_event_id"] = "event-7"
    seventh["source_starts_at"] = "2099-08-28T01:00:00Z"
    rows.append(seventh)

    with pytest.raises(RuntimeError, match="public policy"):
        revalidate_persisted_picks(rows)


def test_persisted_public_policy_rejects_duplicate_free_match():
    rows = six_persisted_picks()
    rows[1]["source_event_id"] = rows[0]["source_event_id"]

    with pytest.raises(RuntimeError, match="public policy"):
        revalidate_persisted_picks(rows)


@pytest.mark.parametrize("bad_picks, run_key", [([], "run-1"), (picks(), "")])
def test_publish_rejects_empty_picks_or_run_key_before_repository(bad_picks, run_key, tmp_path):
    repository = FakeRepository()

    with pytest.raises(ValueError):
        publish_batch(repository, bad_picks, run_key, tmp_path / "picks.json")

    assert repository.calls == []


def test_supabase_repository_stages_exact_daily_rpc_arguments():
    client = FakeClient(
        [{
            "scan_id": "scan-1",
            "portfolio_date": "2026-08-23",
            "revision": 4,
            "created": True,
        }]
    )
    repository = SupabaseBatchRepository(client)
    payload = picks()

    result = repository.stage_daily(
        "scan-run-1", "2026-08-23", "hash-1", payload
    )

    assert result == {
        "scan_id": "scan-1",
        "portfolio_date": "2026-08-23",
        "revision": 4,
        "created": True,
    }
    assert client.calls == [(
        "stage_daily_pick_portfolio",
        {
            "requested_run_key": "scan-run-1",
            "requested_portfolio_date": "2026-08-23",
            "requested_source_hash": "hash-1",
            "requested_picks": payload,
        },
    )]


def test_daily_publisher_stages_projected_rows_without_public_file(tmp_path):
    client = FakeClient(
        [{
            "scan_id": "scan-1",
            "portfolio_date": "2026-08-23",
            "revision": 1,
            "created": True,
        }]
    )
    publisher = DailyPortfolioPublisher(
        repository=SupabaseBatchRepository(client),
        run_key="scan-run-1",
        public_path=tmp_path / "picks.json",
    )

    result = publisher.stage(daily_stage_picks(), portfolio_date="2026-08-23")

    assert result.revision == 1
    assert result.portfolio_date == "2026-08-23"
    assert result.created is True
    assert not (tmp_path / "picks.json").exists()
    sent_rows = client.calls[0][1]["requested_picks"]
    assert all(set(row) <= DAILY_STAGE_PICK_COLUMNS for row in sent_rows)
    assert [row["physical_event_key"] for row in sent_rows] == [
        physical_event_key(row) for row in picks()
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.pop("physical_event_key"),
        lambda row: row.pop("es_parlay"),
        lambda row: row.__setitem__("es_parlay", "false"),
    ],
)
def test_daily_publisher_rejects_incomplete_stage_identity(
    tmp_path, mutation
):
    rows = daily_stage_picks()
    mutation(rows[0])
    publisher = DailyPortfolioPublisher(
        repository=FakeRepository(),
        run_key="scan-invalid",
        public_path=tmp_path / "picks.json",
    )

    with pytest.raises(ValueError):
        publisher.stage(rows, portfolio_date="2026-08-23")


def test_daily_release_writes_full_public_projection_and_exposes_only_delta(tmp_path):
    full_rows = persisted_picks(
        [
            picks()[0],
            picks()[1],
            {
                **picks()[1],
                "pick": "Nueva VIP",
                "source_event_id": "event-new",
                "source_selection_key": "home",
            },
        ]
    )
    delta = [full_rows[2]]
    client = FakeClient(
        [daily_release_response(full_rows, delta, revision=2, feed_eligible=False)]
    )
    destination = tmp_path / "public" / "picks.json"
    publisher = DailyPortfolioPublisher(
        repository=SupabaseBatchRepository(client),
        run_key="release-run-2",
        public_path=destination,
        clock=lambda: datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
    )

    result = publisher.release(portfolio_date="2026-08-23")

    assert result is not None
    assert [dict(row) for row in result.picks] == full_rows
    assert [dict(row) for row in result.delivery_picks] == delta
    assert result.revision == 2
    assert result.feed_eligible is False
    public_row = dict(full_rows[0])
    public_row.pop("razonamiento")
    assert json.loads(destination.read_text(encoding="utf-8")) == [public_row]
    assert client.calls == [(
        "release_daily_pick_portfolio",
        {
            "requested_run_key": "release-run-2",
            "requested_portfolio_date": "2026-08-23",
        },
    )]


def test_daily_resume_uses_exact_run_and_preserves_release_delta(tmp_path):
    full_rows = persisted_picks()
    response = daily_release_response(
        full_rows,
        [full_rows[1]],
        created=False,
        revision=3,
    )
    client = FakeClient([response])
    publisher = DailyPortfolioPublisher(
        repository=SupabaseBatchRepository(client),
        run_key="release-run-3",
        public_path=tmp_path / "picks.json",
    )

    result = publisher.resume()

    assert result is not None
    assert [dict(row) for row in result.delivery_picks] == [full_rows[1]]
    assert client.calls == [(
        "resume_daily_pick_release",
        {"requested_run_key": "release-run-3"},
    )]


def test_daily_release_rejects_delta_outside_full_portfolio(tmp_path):
    full_rows = persisted_picks()
    foreign = persisted_picks(
        [{
            **picks()[1],
            "source_event_id": "foreign-event",
            "source_selection_key": "foreign-selection",
        }]
    )
    client = FakeClient([daily_release_response(full_rows, foreign)])
    publisher = DailyPortfolioPublisher(
        repository=SupabaseBatchRepository(client),
        run_key="release-run-invalid",
        public_path=tmp_path / "picks.json",
    )

    with pytest.raises(RuntimeError, match="delivery picks"):
        publisher.release(portfolio_date="2026-08-23")

    assert not (tmp_path / "picks.json").exists()


def test_daily_release_allows_started_immutable_rows_but_requires_fresh_delta(
    tmp_path,
):
    full_rows = persisted_picks()
    full_rows[0]["source_starts_at"] = "2026-08-22T01:00:00Z"
    response = daily_release_response(full_rows, [full_rows[1]], revision=2)
    publisher = DailyPortfolioPublisher(
        repository=SupabaseBatchRepository(FakeClient([response])),
        run_key="release-after-early-pick",
        public_path=tmp_path / "picks.json",
        clock=lambda: datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
    )

    result = publisher.release(portfolio_date="2026-08-23")

    assert result is not None
    assert [row["id"] for row in result.delivery_picks] == [2]


def test_daily_release_rejects_started_delta_even_when_full_portfolio_is_valid(
    tmp_path,
):
    full_rows = persisted_picks()
    full_rows[1]["source_starts_at"] = "2026-08-22T03:00:00Z"
    response = daily_release_response(full_rows, [full_rows[1]], revision=2)
    publisher = DailyPortfolioPublisher(
        repository=SupabaseBatchRepository(FakeClient([response])),
        run_key="release-stale-delta",
        public_path=tmp_path / "picks.json",
        clock=lambda: datetime(2026, 8, 23, 12, tzinfo=timezone.utc),
    )

    with pytest.raises(RuntimeError, match="source audit"):
        publisher.release(portfolio_date="2026-08-23")


@pytest.mark.parametrize(
    "response",
    [
        None,
        {},
        {"scan_id": "", "portfolio_date": "2026-08-23", "revision": 1, "created": True},
        {"scan_id": "scan", "portfolio_date": "2026-8-23", "revision": 1, "created": True},
        {"scan_id": "scan", "portfolio_date": "2026-08-23", "revision": 0, "created": True},
        {"scan_id": "scan", "portfolio_date": "2026-08-23", "revision": 1, "created": 1},
    ],
)
def test_daily_stage_rejects_malformed_responses(response):
    repository = SupabaseBatchRepository(FakeClient([response]))

    with pytest.raises(RuntimeError, match="stage_daily_pick_portfolio"):
        repository.stage_daily("run", "2026-08-23", "hash", picks())

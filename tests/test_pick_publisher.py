import json

import pytest

import backend.pick_publisher as pick_publisher
from backend.pick_publisher import (
    SupabaseBatchRepository,
    publish_batch,
    source_hash_for,
)


class FakeRepository:
    def __init__(self, response=None, error=None, public_path=None):
        self.response = response or {
            "run_id": "run-1",
            "batch_id": "batch-1",
            "created": True,
            "delivery_status": {"free": {"success": True}},
        }
        self.error = error
        self.public_path = public_path
        self.calls = []
        self.delivery_calls = []

    def publish(self, run_key, source_hash, picks):
        self.calls.append((run_key, source_hash, picks))
        if self.public_path is not None:
            assert not self.public_path.exists()
        if self.error is not None:
            raise self.error
        return self.response

    def record_delivery(self, run_id, destination, success, error=""):
        self.delivery_calls.append((run_id, destination, success, error))


def picks():
    return [
        {"pick": "Gratis", "visibility": "public", "es_parlay": False},
        {"pick": "Solo VIP", "visibility": "premium", "es_parlay": False},
    ]


def test_publish_writes_only_public_pick_after_repository_acceptance(tmp_path):
    destination = tmp_path / "public" / "picks.json"
    repository = FakeRepository(public_path=destination)

    result = publish_batch(repository, picks(), "run-1", destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == [picks()[0]]
    assert repository.calls[0][0] == "run-1"
    assert result.run_id == "run-1"
    assert result.batch_id == "batch-1"
    assert result.created is True
    assert result.delivery_status == {"free": {"success": True}}
    assert result.dry_run is False


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
    repository = FakeRepository(response={
        "run_id": "run-1",
        "batch_id": "batch-1",
        "created": False,
        "delivery_status": {"vip": {"success": True}},
    })

    result = publish_batch(repository, picks(), "run-1", destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == [picks()[0]]
    assert result.created is False
    assert result.delivery_status == {"vip": {"success": True}}


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
    {"run_id": "run-1", "batch_id": "batch-1", "created": True, "delivery_status": {}},
    [{"run_id": "run-1", "batch_id": "batch-1", "created": False, "delivery_status": {"vip": {}}}],
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
])
def test_supabase_repository_rejects_invalid_publish_response(response_data):
    repository = SupabaseBatchRepository(FakeClient([response_data]))

    with pytest.raises(RuntimeError, match="publish_pick_batch"):
        repository.publish("run-1", "hash-1", picks())


@pytest.mark.parametrize("bad_picks, run_key", [([], "run-1"), (picks(), "")])
def test_publish_rejects_empty_picks_or_run_key_before_repository(bad_picks, run_key, tmp_path):
    repository = FakeRepository()

    with pytest.raises(ValueError):
        publish_batch(repository, bad_picks, run_key, tmp_path / "picks.json")

    assert repository.calls == []

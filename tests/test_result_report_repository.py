from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest

from backend.result_report_repository import Claim, SupabaseResultReportRepository


BATCH_ID = "12345678-1234-4234-8234-123456789abc"
DIGEST = "a" * 64


@dataclass
class FakeResponse:
    data: object


class FakeRpc:
    def __init__(self, data: object) -> None:
        self.data = data

    def execute(self) -> FakeResponse:
        return FakeResponse(self.data)


class FakeClient:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, object]]] = []

    def rpc(self, name: str, arguments: dict[str, object]) -> FakeRpc:
        self.calls.append((name, arguments))
        if not self.responses:
            raise AssertionError("unexpected RPC call")
        return FakeRpc(self.responses.pop(0))


def repository(client: FakeClient) -> SupabaseResultReportRepository:
    calls: list[tuple[str, str]] = []

    def factory(url: str, key: str) -> FakeClient:
        calls.append((url, key))
        return client

    result = SupabaseResultReportRepository(
        url="https://project.supabase.co",
        service_role_key="service-secret",
        client_factory=factory,
    )
    assert calls == [("https://project.supabase.co", "service-secret")]
    return result


def six_picks() -> list[dict[str, object]]:
    return [{"id": index} for index in range(1, 7)]


def test_batches_accept_only_exact_six_pick_envelopes():
    client = FakeClient([{"picks": six_picks()}])

    result = repository(client).batches()

    assert result == (tuple(six_picks()),)
    assert client.calls == [("get_result_report_batches", {})]


@pytest.mark.parametrize(
    "payload",
    [None, {}, [{"picks": six_picks(), "extra": True}], [{"picks": six_picks()[:5]}]],
)
def test_batches_reject_malformed_remote_payloads(payload):
    with pytest.raises(RuntimeError, match="invalid|six"):
        repository(FakeClient(payload)).batches()


@pytest.mark.parametrize(
    ("remote_state", "expected"),
    [
        ("complete", Claim("complete", None)),
        ("ambiguous", Claim("ambiguous", None)),
    ],
)
def test_prior_success_and_in_progress_claims_do_not_expose_an_attempt(
    remote_state, expected
):
    repo = repository(
        FakeClient({"state": remote_state, "attempt_id": None})
    )

    assert repo.claim(
        batch_id=BATCH_ID,
        portfolio_date="2026-08-24",
        report_kind="evening",
        destination="free",
        report_digest=DIGEST,
    ) == expected


def test_new_or_failed_claim_returns_the_fresh_canonical_attempt():
    client = FakeClient()

    def rpc(name: str, arguments: dict[str, object]) -> FakeRpc:
        client.calls.append((name, arguments))
        return FakeRpc(
            {"state": "claimed", "attempt_id": arguments["requested_attempt_id"]}
        )

    client.rpc = rpc  # type: ignore[method-assign]
    claim = repository(client).claim(
        batch_id=BATCH_ID,
        portfolio_date="2026-08-24",
        report_kind="final",
        destination="instagram",
        report_digest=DIGEST,
    )

    assert claim.state == "claimed"
    assert claim.attempt_id is not None
    assert str(UUID(claim.attempt_id)) == claim.attempt_id
    name, arguments = client.calls[0]
    assert name == "claim_result_report_delivery"
    assert arguments["requested_attempt_id"] == claim.attempt_id


def test_complete_persists_only_the_matching_claim_and_bounded_strings():
    client = FakeClient({"completed": True})
    repo = repository(client)
    attempt_id = "87654321-4321-4321-8321-cba987654321"

    repo.complete(
        batch_id=BATCH_ID,
        report_kind="final",
        destination="facebook",
        report_digest=DIGEST,
        attempt_id=attempt_id,
        success=True,
        receipt="facebook:123",
    )

    name, arguments = client.calls[0]
    assert name == "complete_result_report_delivery"
    assert arguments["requested_attempt_id"] == attempt_id
    assert arguments["requested_success"] is True
    assert arguments["requested_receipt"] == "facebook:123"
    assert arguments["requested_error"] == ""


@pytest.mark.parametrize(
    "kwargs",
    [
        {"batch_id": "bad"},
        {"portfolio_date": "24/08/2026"},
        {"report_kind": "daily"},
        {"destination": "unknown"},
        {"report_digest": "bad"},
    ],
)
def test_claim_rejects_invalid_local_inputs_before_rpc(kwargs):
    client = FakeClient()
    values = {
        "batch_id": BATCH_ID,
        "portfolio_date": "2026-08-24",
        "report_kind": "evening",
        "destination": "vip",
        "report_digest": DIGEST,
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        repository(client).claim(**values)  # type: ignore[arg-type]
    assert client.calls == []


def test_rpc_failures_are_sanitized():
    class FailingClient(FakeClient):
        def rpc(self, name: str, arguments: dict[str, object]) -> FakeRpc:
            raise RuntimeError("secret remote response")

    with pytest.raises(RuntimeError, match="result report batches failed") as caught:
        repository(FailingClient()).batches()

    assert "secret remote response" not in str(caught.value)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re

import pytest

from backend.vertical_content import VerticalCard
from backend.vertical_repository import SupabaseVerticalRepository, VerticalClaim


BATCH_ID = "22222222-2222-4222-8222-222222222222"
ATTEMPT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class FakeResponse:
    def __init__(self, data: object) -> None:
        self.data = data


class FakeRpc:
    def __init__(self, client: "FakeSupabase", name: str) -> None:
        self.client = client
        self.name = name

    def execute(self) -> FakeResponse:
        if self.client.execute_exception is not None:
            raise self.client.execute_exception
        return FakeResponse(self.client.responses[self.name])


class FakeSupabase:
    def __init__(self) -> None:
        self.responses: dict[str, object] = {}
        self.rpc_calls: list[tuple[str, dict[str, object]]] = []
        self.rpc_exception: Exception | None = None
        self.execute_exception: Exception | None = None

    def rpc(self, name: str, arguments: dict[str, object]) -> FakeRpc:
        if self.rpc_exception is not None:
            raise self.rpc_exception
        self.rpc_calls.append((name, arguments))
        return FakeRpc(self, name)


def repository(client: FakeSupabase) -> SupabaseVerticalRepository:
    calls: list[tuple[str, str]] = []

    def factory(url: str, key: str) -> FakeSupabase:
        calls.append((url, key))
        return client

    result = SupabaseVerticalRepository(
        url="https://project.supabase.co",
        service_role_key="service-secret",
        client_factory=factory,
    )
    assert calls == [("https://project.supabase.co", "service-secret")]
    return result


def package(**overrides: object) -> VerticalCard:
    values: dict[str, object] = {
        "kind": "public_pick_story",
        "batch_id": BATCH_ID,
        "portfolio_date": "2026-08-24",
        "headline": "PICK PÚBLICO DEL DÍA",
        "subtitle": "Hoy",
        "rows": (),
        "cta": "Consulta",
        "digest": "a" * 64,
        "template_version": 1,
    }
    values.update(overrides)
    return VerticalCard(**values)  # type: ignore[arg-type]


def claimed_client() -> FakeSupabase:
    client = FakeSupabase()
    client.responses["claim_vertical_media_delivery"] = []
    return client


def set_claim_response(client: FakeSupabase, state: str, attempt_id: object) -> None:
    client.responses["claim_vertical_media_delivery"] = [
        {"state": state, "attempt_id": attempt_id}
    ]


def test_constructor_reuses_https_and_service_role_validation() -> None:
    with pytest.raises(ValueError, match="HTTPS origin"):
        SupabaseVerticalRepository(
            url="http://project.supabase.co",
            service_role_key="service-secret",
            client_factory=lambda *_: FakeSupabase(),
        )
    with pytest.raises(ValueError, match="anonymous"):
        SupabaseVerticalRepository(
            url="https://project.supabase.co",
            service_role_key="anon",
            client_factory=lambda *_: FakeSupabase(),
        )


def test_claim_uses_exact_content_destination_digest_and_attempt() -> None:
    client = claimed_client()
    repo = repository(client)
    original_rpc = client.rpc

    def rpc(name: str, arguments: dict[str, object]) -> FakeRpc:
        if name == "claim_vertical_media_delivery":
            set_claim_response(client, "claimed", arguments["requested_attempt_id"])
        return original_rpc(name, arguments)

    client.rpc = rpc  # type: ignore[method-assign]
    before = datetime.now(timezone.utc)
    claim = repo.claim(
        batch_id=BATCH_ID,
        portfolio_date="2026-08-24",
        content_kind="public_pick_story",
        destination="instagram_story",
        digest="a" * 64,
        template_version=1,
    )
    after = datetime.now(timezone.utc)

    assert claim == VerticalClaim("claimed", claim.attempt_id)
    assert claim.attempt_id is not None
    assert ATTEMPT_ID_PATTERN.fullmatch(claim.attempt_id)
    assert len(client.rpc_calls) == 1
    name, arguments = client.rpc_calls[0]
    assert name == "claim_vertical_media_delivery"
    assert set(arguments) == {
        "requested_batch_id",
        "requested_portfolio_date",
        "requested_content_kind",
        "requested_destination",
        "requested_content_digest",
        "requested_template_version",
        "requested_attempt_id",
        "requested_lease_expires_at",
    }
    assert arguments | {
        "requested_attempt_id": claim.attempt_id,
        "requested_lease_expires_at": arguments["requested_lease_expires_at"],
    } == {
        "requested_batch_id": BATCH_ID,
        "requested_portfolio_date": "2026-08-24",
        "requested_content_kind": "public_pick_story",
        "requested_destination": "instagram_story",
        "requested_content_digest": "a" * 64,
        "requested_template_version": 1,
        "requested_attempt_id": claim.attempt_id,
        "requested_lease_expires_at": arguments["requested_lease_expires_at"],
    }
    lease = datetime.fromisoformat(str(arguments["requested_lease_expires_at"]))
    assert before + timedelta(minutes=7) < lease < after + timedelta(minutes=9)


@pytest.mark.parametrize("state", ["complete", "ambiguous"])
def test_claim_accepts_only_exact_terminal_shape(state: str) -> None:
    client = claimed_client()
    set_claim_response(client, state, None)
    claim = repository(client).claim(
        batch_id=BATCH_ID,
        portfolio_date="2026-08-24",
        content_kind="daily_results_reel",
        destination="facebook_reel",
        digest="f" * 64,
        template_version=2,
    )
    assert claim == VerticalClaim(state, None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("batch_id", "ABCDEFAB-2222-4222-8222-222222222222"),
        ("batch_id", "not-a-uuid"),
        ("portfolio_date", "2026-8-24"),
        ("portfolio_date", "2026-02-30"),
        ("content_kind", "unknown_story"),
        ("destination", "facebook_story"),
        ("digest", "A" * 64),
        ("digest", "a" * 63),
        ("template_version", 0),
        ("template_version", True),
    ],
)
def test_claim_rejects_noncanonical_or_nonallowlisted_input_before_rpc(
    field: str, value: object
) -> None:
    client = claimed_client()
    arguments: dict[str, object] = {
        "batch_id": BATCH_ID,
        "portfolio_date": "2026-08-24",
        "content_kind": "public_pick_story",
        "destination": "instagram_story",
        "digest": "a" * 64,
        "template_version": 1,
    }
    arguments[field] = value
    with pytest.raises(ValueError):
        repository(client).claim(**arguments)  # type: ignore[arg-type]
    assert client.rpc_calls == []


@pytest.mark.parametrize(
    "response",
    [
        [],
        [{"state": "claimed"}],
        [{"state": "claimed", "attempt_id": "wrong"}],
        [{"state": "complete", "attempt_id": BATCH_ID}],
        [{"state": "unknown", "attempt_id": None}],
        [{"state": "ambiguous", "attempt_id": None, "extra": False}],
        [
            {"state": "complete", "attempt_id": None},
            {"state": "complete", "attempt_id": None},
        ],
    ],
)
def test_claim_rejects_every_nonexact_rpc_shape(response: object) -> None:
    client = claimed_client()
    client.responses["claim_vertical_media_delivery"] = response
    with pytest.raises(
        RuntimeError, match=r"vertical (?:RPC|claim) returned invalid data"
    ):
        repository(client).claim(
            batch_id=BATCH_ID,
            portfolio_date="2026-08-24",
            content_kind="public_pick_story",
            destination="instagram_story",
            digest="a" * 64,
            template_version=1,
        )


@pytest.mark.parametrize("stage", ["rpc", "execute"])
def test_claim_sanitizes_sdk_exceptions(stage: str) -> None:
    client = claimed_client()
    setattr(client, f"{stage}_exception", RuntimeError("service-secret response body"))
    with pytest.raises(RuntimeError, match=r"^vertical claim failed$") as raised:
        repository(client).claim(
            batch_id=BATCH_ID,
            portfolio_date="2026-08-24",
            content_kind="public_pick_story",
            destination="instagram_story",
            digest="a" * 64,
            template_version=1,
        )
    assert raised.value.__cause__ is None


def test_complete_uses_exact_rpc_shape_for_safe_success() -> None:
    client = FakeSupabase()
    client.responses["complete_vertical_media_delivery"] = [{"completed": True}]
    repo = repository(client)
    repo.complete(
        package=package(),
        destination="instagram_story",
        attempt_id="33333333-3333-4333-8333-333333333333",
        success=True,
        receipt="ig-media_123:ok",
    )
    assert client.rpc_calls == [
        (
            "complete_vertical_media_delivery",
            {
                "requested_batch_id": BATCH_ID,
                "requested_content_kind": "public_pick_story",
                "requested_destination": "instagram_story",
                "requested_content_digest": "a" * 64,
                "requested_template_version": 1,
                "requested_attempt_id": "33333333-3333-4333-8333-333333333333",
                "requested_success": True,
                "requested_receipt": "ig-media_123:ok",
                "requested_error": "",
            },
        )
    ]


def test_complete_uses_exact_rpc_shape_for_allowlisted_failure() -> None:
    client = FakeSupabase()
    client.responses["complete_vertical_media_delivery"] = {"completed": True}
    repo = repository(client)
    repo.complete(
        package=package(),
        destination="instagram_story",
        attempt_id="33333333-3333-4333-8333-333333333333",
        success=False,
        error="media_invalid",
    )
    assert client.rpc_calls[0][1]["requested_receipt"] == ""
    assert client.rpc_calls[0][1]["requested_error"] == "media_invalid"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"destination": "facebook_story"},
        {"attempt_id": "ABCDEFAB-2222-4222-8222-222222222222"},
        {"success": 1},
        {"success": True, "receipt": ""},
        {"success": True, "receipt": "safe", "error": "delivery_failed"},
        {"success": True, "receipt": "has space"},
        {"success": False, "receipt": "unexpected", "error": "delivery_failed"},
        {"success": False, "error": "raw remote response"},
    ],
)
def test_complete_rejects_unsafe_outcomes_before_rpc(kwargs: dict[str, object]) -> None:
    client = FakeSupabase()
    defaults: dict[str, object] = {
        "package": package(),
        "destination": "instagram_story",
        "attempt_id": "33333333-3333-4333-8333-333333333333",
        "success": True,
        "receipt": "receipt_123",
        "error": "",
    }
    defaults.update(kwargs)
    with pytest.raises(ValueError):
        repository(client).complete(**defaults)  # type: ignore[arg-type]
    assert client.rpc_calls == []


@pytest.mark.parametrize(
    "bad_package",
    [
        package(batch_id="ABCDEFAB-2222-4222-8222-222222222222"),
        package(portfolio_date="2026-8-24"),
        package(kind="unknown_story"),
        package(digest="A" * 64),
        package(template_version=0),
    ],
)
def test_complete_revalidates_immutable_package_identity(
    bad_package: VerticalCard,
) -> None:
    client = FakeSupabase()
    with pytest.raises(ValueError):
        repository(client).complete(
            package=bad_package,
            destination="instagram_story",
            attempt_id="33333333-3333-4333-8333-333333333333",
            success=True,
            receipt="receipt_123",
        )
    assert client.rpc_calls == []


@pytest.mark.parametrize(
    "response", [{"completed": False}, [{"completed": False}], [{"completed": 1}]]
)
def test_complete_requires_exact_persisted_confirmation(response: object) -> None:
    client = FakeSupabase()
    client.responses["complete_vertical_media_delivery"] = response
    with pytest.raises(RuntimeError, match="vertical completion was not persisted"):
        repository(client).complete(
            package=package(),
            destination="instagram_story",
            attempt_id="33333333-3333-4333-8333-333333333333",
            success=True,
            receipt="receipt_123",
        )


@pytest.mark.parametrize("response", [None, []])
def test_complete_rejects_nonexact_rpc_shape(response: object) -> None:
    client = FakeSupabase()
    client.responses["complete_vertical_media_delivery"] = response
    with pytest.raises(RuntimeError, match="vertical RPC returned invalid data"):
        repository(client).complete(
            package=package(),
            destination="instagram_story",
            attempt_id="33333333-3333-4333-8333-333333333333",
            success=True,
            receipt="receipt_123",
        )


@pytest.mark.parametrize("stage", ["rpc", "execute"])
def test_complete_sanitizes_sdk_exceptions(stage: str) -> None:
    client = FakeSupabase()
    client.responses["complete_vertical_media_delivery"] = [{"completed": True}]
    setattr(client, f"{stage}_exception", RuntimeError("service-secret response body"))
    with pytest.raises(RuntimeError, match=r"^vertical completion failed$") as raised:
        repository(client).complete(
            package=package(),
            destination="instagram_story",
            attempt_id="33333333-3333-4333-8333-333333333333",
            success=True,
            receipt="receipt_123",
        )
    assert raised.value.__cause__ is None

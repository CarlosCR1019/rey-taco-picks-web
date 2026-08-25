from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
import re

from PIL import Image
import pytest

from backend.vertical_content import VerticalCard
from backend.vertical_repository import (
    SupabaseVerticalRepository,
    TemporaryAsset,
    VerticalClaim,
)


BATCH_ID = "22222222-2222-4222-8222-222222222222"
ATTEMPT_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
STORY_OBJECT_KEY = f"stories/2026-08-24/public_pick_story-{'a' * 64}.jpg"
STORY_URL = (
    "https://project.supabase.co/storage/v1/object/public/social-vertical/"
    f"{STORY_OBJECT_KEY}"
)


@dataclass(frozen=True)
class FakeUploadResponse:
    path: str
    full_path: str
    fullPath: str


class FakeBucket:
    def __init__(self) -> None:
        self.upload_calls: list[dict[str, object]] = []
        self.remove_calls: list[list[str]] = []
        self.upload_exception: Exception | None = None
        self.public_url_exception: Exception | None = None
        self.remove_exception: Exception | None = None
        full_path = f"social-vertical/{STORY_OBJECT_KEY}"
        self.upload_response: object = FakeUploadResponse(
            STORY_OBJECT_KEY, full_path, full_path
        )
        self.public_url: object = STORY_URL
        self.remove_response: object = [{"name": STORY_OBJECT_KEY}]

    def upload(
        self,
        *,
        path: str,
        file: bytes,
        file_options: dict[str, str],
    ) -> object:
        if self.upload_exception is not None:
            raise self.upload_exception
        self.upload_calls.append(
            {"path": path, "file": file, "file_options": file_options}
        )
        return self.upload_response

    def get_public_url(self, path: str) -> object:
        if self.public_url_exception is not None:
            raise self.public_url_exception
        return self.public_url

    def remove(self, paths: list[str]) -> object:
        if self.remove_exception is not None:
            raise self.remove_exception
        self.remove_calls.append(paths)
        return self.remove_response


class FakeStorage:
    def __init__(self) -> None:
        self.bucket = FakeBucket()
        self.from_calls: list[str] = []

    def from_(self, bucket_name: str) -> FakeBucket:
        self.from_calls.append(bucket_name)
        return self.bucket


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
        self.storage = FakeStorage()

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


def story_jpeg(
    *, size: tuple[int, int] = (1080, 1920), mode: str = "RGB"
) -> bytes:
    output = BytesIO()
    Image.new(mode, size).save(output, format="JPEG")
    return output.getvalue()


def test_upload_story_uses_digest_key_and_exact_public_url() -> None:
    client = FakeSupabase()
    repo = repository(client)
    card = package()
    jpeg = story_jpeg()

    asset = repo.upload_story(card=card, jpeg=jpeg)

    assert asset.object_key == STORY_OBJECT_KEY
    assert asset.url == STORY_URL
    assert asset.mime_type == "image/jpeg"
    assert client.storage.from_calls == ["social-vertical"]
    assert client.storage.bucket.upload_calls == [
        {
            "path": STORY_OBJECT_KEY,
            "file": jpeg,
            "file_options": {
                "content-type": "image/jpeg",
                "upsert": "true",
            },
        }
    ]


def test_delete_requires_the_same_bucket_and_exact_object_key() -> None:
    client = FakeSupabase()
    repo = repository(client)
    asset = repo.upload_story(card=package(), jpeg=story_jpeg())
    client.storage.from_calls.clear()

    repo.delete_temporary(asset)

    assert client.storage.from_calls == ["social-vertical"]
    assert client.storage.bucket.remove_calls == [[asset.object_key]]


@pytest.mark.parametrize(
    ("jpeg", "message"),
    [
        (b"not-a-jpeg", "JPEG"),
        (story_jpeg(size=(1080, 1919)), "1080x1920"),
        (story_jpeg(mode="CMYK"), "RGB"),
        (b"\xff\xd8" + b"x" * (5 * 1024 * 1024), "5 MiB"),
    ],
    ids=("not-jpeg", "wrong-size", "cmyk", "oversized"),
)
def test_upload_story_rejects_invalid_jpeg_before_storage(
    jpeg: bytes, message: str
) -> None:
    client = FakeSupabase()

    with pytest.raises(ValueError, match=message):
        repository(client).upload_story(card=package(), jpeg=jpeg)

    assert client.storage.from_calls == []


@pytest.mark.parametrize(
    "jpeg",
    [bytearray(b"jpeg"), memoryview(b"jpeg"), "jpeg"],
    ids=("bytearray", "memoryview", "string"),
)
def test_upload_story_accepts_only_immutable_bytes(jpeg: object) -> None:
    client = FakeSupabase()

    with pytest.raises(ValueError, match="immutable bytes"):
        repository(client).upload_story(
            card=package(),
            jpeg=jpeg,  # type: ignore[arg-type]
        )

    assert client.storage.from_calls == []


def test_upload_story_revalidates_card_identity_before_storage() -> None:
    client = FakeSupabase()

    with pytest.raises(ValueError, match="digest"):
        repository(client).upload_story(
            card=package(digest="A" * 64),
            jpeg=story_jpeg(),
        )

    assert client.storage.from_calls == []


def test_upload_story_rejects_unexpected_upload_response() -> None:
    client = FakeSupabase()
    client.storage.bucket.upload_response = {"path": STORY_OBJECT_KEY}

    with pytest.raises(RuntimeError, match="upload response"):
        repository(client).upload_story(card=package(), jpeg=story_jpeg())


@pytest.mark.parametrize(
    "public_url",
    [
        STORY_URL.replace("https://", "http://"),
        STORY_URL.replace("project.supabase.co", "attacker.example"),
        STORY_URL.replace("social-vertical", "other-bucket"),
        STORY_URL + "?token=unexpected",
    ],
)
def test_upload_story_requires_exact_public_url(public_url: object) -> None:
    client = FakeSupabase()
    client.storage.bucket.public_url = public_url

    with pytest.raises(RuntimeError, match="public URL"):
        repository(client).upload_story(card=package(), jpeg=story_jpeg())


@pytest.mark.parametrize("stage", ["upload", "public_url"])
def test_upload_story_sanitizes_storage_exceptions(stage: str) -> None:
    client = FakeSupabase()
    setattr(
        client.storage.bucket,
        f"{stage}_exception",
        RuntimeError("raw provider body service-secret"),
    )

    with pytest.raises(RuntimeError) as captured:
        repository(client).upload_story(card=package(), jpeg=story_jpeg())

    assert str(captured.value) in {
        "temporary story upload failed",
        "temporary story public URL failed",
    }
    assert "service-secret" not in str(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    "asset",
    [
        object(),
        TemporaryAsset("private/file.jpg", STORY_URL, "image/jpeg"),
    ],
)
def test_delete_rejects_non_temporary_assets_before_storage(asset: object) -> None:
    client = FakeSupabase()

    with pytest.raises(ValueError, match="key is invalid"):
        repository(client).delete_temporary(asset)  # type: ignore[arg-type]

    assert client.storage.from_calls == []


@pytest.mark.parametrize(
    "response",
    [None, [], [{"name": "stories/other.jpg"}], [{"name": STORY_OBJECT_KEY}] * 2],
)
def test_delete_requires_exact_remove_confirmation(response: object) -> None:
    client = FakeSupabase()
    client.storage.bucket.remove_response = response
    asset = TemporaryAsset(STORY_OBJECT_KEY, STORY_URL, "image/jpeg")

    with pytest.raises(RuntimeError, match="cleanup response"):
        repository(client).delete_temporary(asset)


def test_delete_sanitizes_storage_exception() -> None:
    client = FakeSupabase()
    client.storage.bucket.remove_exception = RuntimeError(
        "raw provider body service-secret"
    )
    asset = TemporaryAsset(STORY_OBJECT_KEY, STORY_URL, "image/jpeg")

    with pytest.raises(RuntimeError, match=r"^temporary asset cleanup failed$") as raised:
        repository(client).delete_temporary(asset)

    assert "service-secret" not in str(raised.value)
    assert raised.value.__cause__ is None


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

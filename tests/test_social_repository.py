from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import MappingProxyType
from typing import Literal

from PIL import Image
import pytest

from backend.social_repository import MetaSocialBatch, SupabaseSocialRepository
from backend.social_content import demo_social_content


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
RUN_ID = "11111111-1111-4111-8111-111111111111"
BATCH_ID = "22222222-2222-4222-8222-222222222222"
ATTEMPT_ID = "33333333-3333-4333-8333-333333333333"
OBJECT_KEY = f"daily/{BATCH_ID}/321.jpg"
PUBLIC_URL = (
    "https://project.supabase.co/storage/v1/object/public/"
    f"social-media/{OBJECT_KEY}"
)


def public_pick(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 321,
        "categoria": "Fútbol",
        "partido": "Equipo Norte vs Equipo Sur",
        "pick": "Más de 1.5 goles",
        "cuota": "1.85",
        "confianza": "alta",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "Liga de prueba",
        "mercado": "Total de goles",
        "riesgo": "Riesgo medio",
        "fecha_generacion": "2026-08-21T11:00:00+00:00",
        "fecha_evento": "2026-08-22",
        "horario": "18:00 CDMX",
        "tiene_valor": True,
        "visibility": "public",
        "source": "sportsbook",
        "source_event_id": "event-321",
        "source_market_key": "totals:1.5",
        "source_selection_key": "over:1.5",
        "source_observed_at": "2026-08-21T11:00:00+00:00",
        "source_starts_at": "2026-08-22T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def social_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": RUN_ID,
        "batch_id": BATCH_ID,
        "delivery_status": {
            "admin": {"success": True, "error": ""},
            "facebook": {
                "success": False,
                "receipt": "",
                "error": "delivery_failed",
            },
        },
        "public_pick": public_pick(),
    }
    payload.update(overrides)
    return payload


class FakeResponse:
    def __init__(self, data: object) -> None:
        self.data = data


class FakeRpc:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.execute_count = 0

    def execute(self) -> FakeResponse:
        self.execute_count += 1
        return self.response


@dataclass
class FakeUploadResponse:
    path: str
    full_path: str
    fullPath: str


class FakeBucket:
    def __init__(self, *, public_url: object = PUBLIC_URL) -> None:
        self.public_url = public_url
        self.upload_calls: list[dict[str, object]] = []
        self.public_url_calls: list[str] = []
        self.upload_response: object = FakeUploadResponse(
            path=OBJECT_KEY,
            full_path=f"social-media/{OBJECT_KEY}",
            fullPath=f"social-media/{OBJECT_KEY}",
        )
        self.upload_exception: Exception | None = None
        self.public_url_exception: Exception | None = None

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
        self.public_url_calls.append(path)
        return self.public_url


class FakeStorage:
    def __init__(self, bucket: FakeBucket) -> None:
        self.bucket = bucket
        self.from_calls: list[str] = []

    def from_(self, bucket_name: str) -> FakeBucket:
        self.from_calls.append(bucket_name)
        return self.bucket


class FakeSupabase:
    def __init__(
        self,
        *,
        rpc_data: object = None,
        bucket: FakeBucket | None = None,
    ) -> None:
        self.rpc_data = rpc_data
        self.rpc_calls: list[tuple[str, dict[str, object]]] = []
        self.rpc_handles: list[FakeRpc] = []
        self.storage = FakeStorage(bucket or FakeBucket())

    def rpc(self, name: str, arguments: dict[str, object]) -> FakeRpc:
        self.rpc_calls.append((name, arguments))
        handle = FakeRpc(FakeResponse(self.rpc_data))
        self.rpc_handles.append(handle)
        return handle


def repository(
    client: FakeSupabase,
    *,
    url: str = "https://project.supabase.co",
    service_key: str = "service-secret",
) -> SupabaseSocialRepository:
    factory_calls: list[tuple[str, str]] = []

    def client_factory(supabase_url: str, supabase_key: str) -> FakeSupabase:
        factory_calls.append((supabase_url, supabase_key))
        return client

    result = SupabaseSocialRepository(
        supabase_url=url,
        service_role_key=service_key,
        client_factory=client_factory,
    )
    assert factory_calls == [(url, service_key)]
    return result


def jpeg_bytes(
    *,
    size: tuple[int, int] = (1080, 1080),
    mode: str = "RGB",
) -> bytes:
    image = Image.new(mode, size, "#102040")
    output = BytesIO()
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


def jpeg_with_declared_dimensions(*, width: int, height: int) -> bytes:
    payload = bytearray(jpeg_bytes(size=(1, 1)))
    sof_offset = payload.find(b"\xff\xc0")
    assert sof_offset >= 0
    payload[sof_offset + 5 : sof_offset + 7] = height.to_bytes(2, "big")
    payload[sof_offset + 7 : sof_offset + 9] = width.to_bytes(2, "big")
    return bytes(payload)


def valid_batch(client: FakeSupabase | None = None) -> MetaSocialBatch:
    active_client = client or FakeSupabase(rpc_data=social_payload())
    result = repository(active_client).get_batch(
        run_key="github-run:123",
        reference_at=NOW,
    )
    assert result is not None
    return result


def test_constructor_requires_explicit_https_url_and_service_role_key() -> None:
    calls: list[tuple[str, str]] = []

    def factory(url: str, key: str) -> FakeSupabase:
        calls.append((url, key))
        return FakeSupabase()

    with pytest.raises(ValueError, match="supabase_url"):
        SupabaseSocialRepository(
            supabase_url="http://project.supabase.co",
            service_role_key="service-secret",
            client_factory=factory,
        )
    with pytest.raises(ValueError, match="service_role_key"):
        SupabaseSocialRepository(
            supabase_url="https://project.supabase.co",
            service_role_key=" ",
            client_factory=factory,
        )
    with pytest.raises(ValueError, match="service_role_key"):
        SupabaseSocialRepository(
            supabase_url="https://project.supabase.co",
            service_role_key="sb_publishable_not-a-service-key",
            client_factory=factory,
        )
    assert calls == []


def test_constructor_rejects_every_ascii_control_anywhere_in_origin() -> None:
    controls = tuple(chr(codepoint) for codepoint in (*range(0x20), 0x7F))
    placements = (
        lambda control: f"{control}https://project.supabase.co",
        lambda control: f"ht{control}tps://project.supabase.co",
        lambda control: f"https://pro{control}ject.supabase.co",
        lambda control: f"https://project.supabase.co{control}",
    )
    factory_calls: list[tuple[str, str]] = []

    def factory(url: str, key: str) -> FakeSupabase:
        factory_calls.append((url, key))
        return FakeSupabase()

    for control in controls:
        for place in placements:
            with pytest.raises(ValueError, match="supabase_url"):
                SupabaseSocialRepository(
                    supabase_url=place(control),
                    service_role_key="service-secret",
                    client_factory=factory,
                )

    assert factory_calls == []


@pytest.mark.parametrize("run_key", ["", " ", "\t\n", None, 123])
def test_get_batch_rejects_blank_or_non_string_run_key_before_rpc(
    run_key: object,
) -> None:
    client = FakeSupabase(rpc_data=social_payload())
    repo = repository(client)

    with pytest.raises(ValueError, match="run_key"):
        repo.get_batch(run_key=run_key, reference_at=NOW)  # type: ignore[arg-type]

    assert client.rpc_calls == []


def test_get_batch_calls_exact_rpc_and_normalizes_one_public_batch() -> None:
    payload = social_payload()
    client = FakeSupabase(rpc_data=payload)

    batch = repository(client).get_batch(
        run_key="github-run:123",
        reference_at=NOW,
    )

    assert client.rpc_calls == [
        (
            "get_meta_social_batch",
            {"requested_run_key": "github-run:123"},
        )
    ]
    assert client.rpc_handles[0].execute_count == 1
    assert batch is not None
    assert batch.run_id == RUN_ID
    assert batch.batch_id == BATCH_ID
    assert isinstance(batch.delivery_status, MappingProxyType)
    assert batch.delivery_status["facebook"] == {
        "success": False,
        "receipt": "",
        "error": "delivery_failed",
    }
    assert batch.content.pick_id == "321"
    assert batch.content.object_key(batch_id=batch.batch_id) == OBJECT_KEY


def test_get_batch_sql_null_returns_none_without_storage_access() -> None:
    client = FakeSupabase(rpc_data=None)

    result = repository(client).get_batch(
        run_key="github-run:missing",
        reference_at=NOW,
    )

    assert result is None
    assert client.storage.from_calls == []


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ({"run_id": "not-a-uuid"}, "run_id"),
        ({"batch_id": "22222222-2222-4222-8222-222222222222 ",}, "batch_id"),
        ({"delivery_status": []}, "delivery_status"),
        ({"public_pick": []}, "public_pick"),
        ({"unexpected": "secret"}, "exact"),
    ],
)
def test_get_batch_fails_closed_on_malformed_or_extra_response_fields(
    replacement: dict[str, object],
    message: str,
) -> None:
    payload = social_payload()
    if "unexpected" in replacement:
        payload.update(replacement)
    else:
        payload.update(replacement)

    with pytest.raises((ValueError, RuntimeError), match=message):
        repository(FakeSupabase(rpc_data=payload)).get_batch(
            run_key="github-run:123",
            reference_at=NOW,
        )


@pytest.mark.parametrize("mutation", ["missing", "sensitive"])
def test_get_batch_rejects_non_exact_or_sensitive_public_pick(
    mutation: str,
) -> None:
    pick = public_pick()
    if mutation == "missing":
        del pick["source"]
    else:
        pick["razonamiento"] = "premium reasoning must never cross"

    with pytest.raises(ValueError, match="exact public pick fields"):
        repository(
            FakeSupabase(rpc_data=social_payload(public_pick=pick))
        ).get_batch(run_key="github-run:123", reference_at=NOW)


def test_get_batch_returns_a_defensive_delivery_ledger_copy() -> None:
    payload = social_payload()
    source_ledger = payload["delivery_status"]
    assert isinstance(source_ledger, dict)

    batch = repository(FakeSupabase(rpc_data=payload)).get_batch(
        run_key="github-run:123",
        reference_at=NOW,
    )
    assert batch is not None
    source_ledger["facebook"] = {"success": True, "receipt": "mutated"}

    assert batch.delivery_status["facebook"] == {
        "success": False,
        "receipt": "",
        "error": "delivery_failed",
    }
    with pytest.raises(TypeError):
        batch.delivery_status["instagram"] = {}  # type: ignore[index]


def test_upload_jpeg_uses_exact_bucket_key_options_and_public_url() -> None:
    client = FakeSupabase(rpc_data=social_payload())
    repo = repository(client)
    batch = valid_batch()
    image = jpeg_bytes()

    url = repo.upload_jpeg(batch=batch, jpeg=image)

    assert url == PUBLIC_URL
    assert client.storage.from_calls == ["social-media"]
    assert client.storage.bucket.upload_calls == [
        {
            "path": OBJECT_KEY,
            "file": image,
            "file_options": {
                "content-type": "image/jpeg",
                "upsert": "true",
            },
        }
    ]
    assert client.storage.bucket.public_url_calls == [OBJECT_KEY]


def test_upload_jpeg_rejects_demo_content_before_storage() -> None:
    client = FakeSupabase()
    batch = MetaSocialBatch(
        run_id=RUN_ID,
        batch_id=BATCH_ID,
        delivery_status=MappingProxyType({}),
        content=demo_social_content(reference_at=NOW),
    )

    with pytest.raises(ValueError, match="public"):
        repository(client).upload_jpeg(batch=batch, jpeg=jpeg_bytes())

    assert client.storage.from_calls == []


@pytest.mark.parametrize(
    ("image", "message"),
    [
        (b"not-a-jpeg", "JPEG"),
        (jpeg_bytes(size=(1079, 1080)), "1080x1080"),
        (jpeg_bytes(mode="CMYK"), "RGB"),
        (b"\xff\xd8" + b"x" * (5 * 1024 * 1024), "5 MiB"),
    ],
    ids=("not-jpeg", "wrong-size", "cmyk", "oversized"),
)
def test_upload_jpeg_rejects_invalid_bytes_before_storage(
    image: bytes,
    message: str,
) -> None:
    client = FakeSupabase()

    with pytest.raises(ValueError, match=message):
        repository(client).upload_jpeg(batch=valid_batch(), jpeg=image)

    assert client.storage.from_calls == []


@pytest.mark.parametrize(
    "image",
    [bytearray(b"jpeg"), memoryview(b"jpeg"), "jpeg"],
    ids=("bytearray", "memoryview", "string"),
)
def test_upload_jpeg_accepts_only_immutable_bytes(image: object) -> None:
    client = FakeSupabase()

    with pytest.raises(ValueError, match="bytes"):
        repository(client).upload_jpeg(
            batch=valid_batch(),
            jpeg=image,  # type: ignore[arg-type]
        )

    assert client.storage.from_calls == []


@pytest.mark.parametrize(
    ("width", "height"),
    [(10_000, 10_000), (65_535, 65_535)],
    ids=("decompression-warning", "decompression-error"),
)
def test_upload_jpeg_normalizes_malicious_declared_dimensions_without_upload(
    width: int,
    height: int,
) -> None:
    payload = jpeg_with_declared_dimensions(width=width, height=height)
    assert len(payload) < 1_024
    client = FakeSupabase()

    with pytest.raises(ValueError) as captured:
        repository(client).upload_jpeg(batch=valid_batch(), jpeg=payload)

    assert str(captured.value) == "jpeg must contain valid JPEG bytes"
    assert client.storage.from_calls == []


@pytest.mark.parametrize(
    "public_url",
    [
        PUBLIC_URL.replace("https://", "http://"),
        PUBLIC_URL.replace("project.supabase.co", "attacker.example"),
        PUBLIC_URL.replace("/social-media/", "/other-bucket/"),
        PUBLIC_URL.replace("/321.jpg", "/999.jpg"),
        PUBLIC_URL.replace("/storage/v1/", "/storage%2Fv1/"),
        PUBLIC_URL.replace("/storage/v1/", "/storage%2fv1/"),
        PUBLIC_URL.replace("/daily/", "/%64aily/"),
        PUBLIC_URL.replace("/321.jpg", "/%33%32%31.jpg"),
        PUBLIC_URL + "?token=unexpected",
        {"publicURL": PUBLIC_URL},
    ],
)
def test_upload_jpeg_rejects_non_exact_or_non_https_public_url(
    public_url: object,
) -> None:
    bucket = FakeBucket(public_url=public_url)
    client = FakeSupabase(bucket=bucket)

    with pytest.raises(RuntimeError, match="public URL"):
        repository(client).upload_jpeg(batch=valid_batch(), jpeg=jpeg_bytes())


def test_upload_jpeg_rejects_every_ascii_control_anywhere_in_public_url() -> None:
    controls = tuple(chr(codepoint) for codepoint in (*range(0x20), 0x7F))
    placements = (
        lambda control: f"{control}{PUBLIC_URL}",
        lambda control: PUBLIC_URL.replace(
            "project.supabase.co",
            f"pro{control}ject.supabase.co",
        ),
        lambda control: PUBLIC_URL.replace(
            "/storage/v1/",
            f"/storage/{control}v1/",
        ),
    )

    for control in controls:
        for place in placements:
            tainted_url = place(control)
            with pytest.raises(RuntimeError, match="public URL"):
                repository(
                    FakeSupabase(bucket=FakeBucket(public_url=tainted_url))
                ).upload_jpeg(batch=valid_batch(), jpeg=jpeg_bytes())


@pytest.mark.parametrize(
    "whitespace",
    [" ", "\u00a0", "\u2003", "\u3000"],
    ids=("ascii-space", "no-break-space", "em-space", "ideographic-space"),
)
@pytest.mark.parametrize("placement", ["leading", "trailing"])
def test_upload_jpeg_rejects_outer_whitespace_in_public_url(
    whitespace: str,
    placement: str,
) -> None:
    assert whitespace.isspace()
    tainted_url = (
        f"{whitespace}{PUBLIC_URL}"
        if placement == "leading"
        else f"{PUBLIC_URL}{whitespace}"
    )

    with pytest.raises(RuntimeError, match="public URL"):
        repository(
            FakeSupabase(bucket=FakeBucket(public_url=tainted_url))
        ).upload_jpeg(batch=valid_batch(), jpeg=jpeg_bytes())


def test_upload_jpeg_fails_closed_on_unexpected_upload_response() -> None:
    bucket = FakeBucket()
    bucket.upload_response = {"path": OBJECT_KEY}

    with pytest.raises(RuntimeError, match="upload response"):
        repository(FakeSupabase(bucket=bucket)).upload_jpeg(
            batch=valid_batch(),
            jpeg=jpeg_bytes(),
        )


@pytest.mark.parametrize("stage", ["upload", "public-url"])
def test_upload_jpeg_sanitizes_storage_exceptions(stage: str) -> None:
    secret = "service-secret"
    bucket = FakeBucket()
    if stage == "upload":
        bucket.upload_exception = RuntimeError(f"raw provider body {secret}")
        expected = "social JPEG upload failed"
    else:
        bucket.public_url_exception = RuntimeError(f"raw provider body {secret}")
        expected = "social JPEG public URL failed"

    with pytest.raises(RuntimeError) as captured:
        repository(FakeSupabase(bucket=bucket), service_key=secret).upload_jpeg(
            batch=valid_batch(),
            jpeg=jpeg_bytes(),
        )

    assert str(captured.value) == expected
    assert secret not in str(captured.value)


@dataclass(frozen=True)
class Delivery:
    destination: Literal["facebook", "instagram"]
    status: str
    receipt: str = ""


@pytest.mark.parametrize("claimed", [True, False])
def test_claim_destination_calls_exact_rpc_and_requires_boolean_response(
    claimed: bool,
) -> None:
    client = FakeSupabase(rpc_data=claimed)
    lease = datetime.now(timezone.utc) + timedelta(minutes=5)

    result = repository(client).claim_destination(
        run_id=RUN_ID,
        destination="instagram",
        attempt_id=ATTEMPT_ID,
        lease_expires_at=lease,
    )

    assert result is claimed
    assert client.rpc_calls == [
        (
            "claim_meta_social_destination",
            {
                "requested_run_id": RUN_ID,
                "requested_destination": "instagram",
                "requested_attempt_id": ATTEMPT_ID,
                "requested_lease_expires_at": lease.isoformat(),
            },
        )
    ]
    assert client.rpc_handles[0].execute_count == 1


@pytest.mark.parametrize("rpc_data", [None, [], {}, 0, 1, "true"])
def test_claim_destination_rejects_non_boolean_sdk_response(rpc_data: object) -> None:
    client = FakeSupabase(rpc_data=rpc_data)

    with pytest.raises(RuntimeError, match="claim.*invalid response"):
        repository(client).claim_destination(
            run_id=RUN_ID,
            destination="facebook",
            attempt_id=ATTEMPT_ID,
            lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )


@pytest.mark.parametrize(
    ("run_id", "destination", "attempt_id", "lease", "message"),
    [
        ("bad-run", "facebook", ATTEMPT_ID, "valid", "run_id"),
        (RUN_ID, "twitter", ATTEMPT_ID, "valid", "destination"),
        (RUN_ID, "facebook", "bad-attempt", "valid", "attempt_id"),
        (RUN_ID, "facebook", ATTEMPT_ID, "naive", "UTC"),
        (RUN_ID, "facebook", ATTEMPT_ID, "past", "future"),
        (RUN_ID, "facebook", ATTEMPT_ID, "long", "10 minutes"),
    ],
)
def test_claim_destination_validates_canonical_ids_and_bounded_utc_lease(
    run_id: str,
    destination: str,
    attempt_id: str,
    lease: str,
    message: str,
) -> None:
    now = datetime.now(timezone.utc)
    lease_value = {
        "valid": now + timedelta(minutes=5),
        "naive": now.replace(tzinfo=None) + timedelta(minutes=5),
        "past": now - timedelta(seconds=1),
        "long": now + timedelta(minutes=11),
    }[lease]
    client = FakeSupabase(rpc_data=True)

    with pytest.raises(ValueError, match=message):
        repository(client).claim_destination(
            run_id=run_id,
            destination=destination,  # type: ignore[arg-type]
            attempt_id=attempt_id,
            lease_expires_at=lease_value,
        )

    assert client.rpc_calls == []


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            Delivery("facebook", "success", "photo_123:abc"),
            {
                "requested_run_id": RUN_ID,
                "requested_destination": "facebook",
                "requested_success": True,
                "requested_receipt": "photo_123:abc",
                "requested_error": "",
                "requested_attempt_id": ATTEMPT_ID,
            },
        ),
        (
            Delivery("instagram", "delivery_failed"),
            {
                "requested_run_id": RUN_ID,
                "requested_destination": "instagram",
                "requested_success": False,
                "requested_receipt": "",
                "requested_error": "delivery_failed",
                "requested_attempt_id": ATTEMPT_ID,
            },
        ),
        (
            Delivery("instagram", "token_invalid"),
            {
                "requested_run_id": RUN_ID,
                "requested_destination": "instagram",
                "requested_success": False,
                "requested_receipt": "",
                "requested_error": "token_invalid",
                "requested_attempt_id": ATTEMPT_ID,
            },
        ),
        (
            Delivery("facebook", "not_configured"),
            {
                "requested_run_id": RUN_ID,
                "requested_destination": "facebook",
                "requested_success": False,
                "requested_receipt": "",
                "requested_error": "not_configured",
                "requested_attempt_id": ATTEMPT_ID,
            },
        ),
    ],
)
@pytest.mark.parametrize("void_data", [None, []], ids=("legacy-none", "sdk-empty-list"))
def test_record_delivery_calls_exact_six_argument_social_rpc(
    result: Delivery,
    expected: dict[str, object],
    void_data: object,
) -> None:
    client = FakeSupabase(rpc_data=void_data)

    repository(client).record_delivery(
        run_id=RUN_ID,
        result=result,
        attempt_id=ATTEMPT_ID,
    )

    assert client.rpc_calls == [("record_meta_social_delivery", expected)]
    assert client.rpc_handles[0].execute_count == 1


def test_record_delivery_persists_destinations_independently() -> None:
    client = FakeSupabase(rpc_data=[])
    repo = repository(client)

    repo.record_delivery(
        run_id=RUN_ID,
        result=Delivery("facebook", "success", "fb_123"),
        attempt_id=ATTEMPT_ID,
    )
    repo.record_delivery(
        run_id=RUN_ID,
        result=Delivery("instagram", "delivery_failed"),
        attempt_id="44444444-4444-4444-8444-444444444444",
    )

    assert [call[1]["requested_destination"] for call in client.rpc_calls] == [
        "facebook",
        "instagram",
    ]
    assert [call[1]["requested_success"] for call in client.rpc_calls] == [
        True,
        False,
    ]


@pytest.mark.parametrize("rpc_data", ["", {}, [None], False, 0])
def test_record_delivery_fails_closed_on_unexpected_void_rpc_data(
    rpc_data: object,
) -> None:
    client = FakeSupabase(rpc_data=rpc_data)

    with pytest.raises(RuntimeError, match="invalid response"):
        repository(client).record_delivery(
            run_id=RUN_ID,
            result=Delivery("facebook", "success", "fb_123"),
            attempt_id=ATTEMPT_ID,
        )


class ExplodingSupabase(FakeSupabase):
    def rpc(self, name: str, arguments: dict[str, object]) -> FakeRpc:
        raise RuntimeError("raw provider body service-secret")


@pytest.mark.parametrize("operation", ["get", "claim", "record"])
def test_rpc_exceptions_are_sanitized_without_raw_payloads(operation: str) -> None:
    repo = repository(ExplodingSupabase(), service_key="service-secret")

    with pytest.raises(RuntimeError) as captured:
        if operation == "get":
            repo.get_batch(run_key="github-run:123", reference_at=NOW)
        elif operation == "claim":
            repo.claim_destination(
                run_id=RUN_ID,
                destination="facebook",
                attempt_id=ATTEMPT_ID,
                lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
        else:
            repo.record_delivery(
                run_id=RUN_ID,
                result=Delivery("instagram", "delivery_failed"),
                attempt_id=ATTEMPT_ID,
            )

    assert "service-secret" not in str(captured.value)
    assert "raw provider body" not in str(captured.value)


@pytest.mark.parametrize(
    ("run_id", "result", "attempt_id", "message"),
    [
        ("bad-run", Delivery("facebook", "delivery_failed"), ATTEMPT_ID, "run_id"),
        (RUN_ID, Delivery("facebook", "skipped"), ATTEMPT_ID, "status"),
        (RUN_ID, Delivery("facebook", "raw provider body"), ATTEMPT_ID, "status"),
        (RUN_ID, Delivery("facebook", "success", ""), ATTEMPT_ID, "receipt"),
        (RUN_ID, Delivery("facebook", "success", "unsafe receipt!"), ATTEMPT_ID, "receipt"),
        (
            RUN_ID,
            Delivery("instagram", "delivery_failed", "unexpected"),
            ATTEMPT_ID,
            "receipt",
        ),
        (RUN_ID, Delivery("twitter", "delivery_failed"), ATTEMPT_ID, "destination"),  # type: ignore[arg-type]
        (RUN_ID, Delivery("facebook", "delivery_failed"), "bad-attempt", "attempt_id"),
    ],
)
def test_record_delivery_rejects_invalid_or_free_form_results_before_rpc(
    run_id: str,
    result: Delivery,
    attempt_id: str,
    message: str,
) -> None:
    client = FakeSupabase()

    with pytest.raises(ValueError, match=message):
        repository(client).record_delivery(
            run_id=run_id,
            result=result,
            attempt_id=attempt_id,
        )

    assert client.rpc_calls == []

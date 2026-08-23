"""Fail-closed Supabase boundary for one exact social publishing run."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import json
import math
import re
from types import MappingProxyType
from typing import Literal, Protocol, cast
from urllib.parse import unquote, urlsplit
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from supabase import create_client

from backend.social_content import SocialContent, content_from_public_pick


_BATCH_FIELDS = frozenset(
    {"run_id", "batch_id", "delivery_status", "public_pick"}
)
_SAFE_RECEIPT = re.compile(r"^[A-Za-z0-9_:-]{1,200}$")
_ASCII_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PERSISTED_FAILURES = frozenset(
    {"not_configured", "token_invalid", "delivery_failed"}
)


class _SupabaseResponse(Protocol):
    data: object


class _SupabaseRpc(Protocol):
    def execute(self) -> _SupabaseResponse: ...


class _StorageBucket(Protocol):
    def upload(
        self,
        *,
        path: str,
        file: bytes,
        file_options: dict[str, str],
    ) -> object: ...

    def get_public_url(self, path: str) -> object: ...


class _Storage(Protocol):
    def from_(self, bucket_name: str) -> _StorageBucket: ...


class _SupabaseClient(Protocol):
    storage: _Storage

    def rpc(
        self,
        function_name: str,
        arguments: dict[str, object],
    ) -> _SupabaseRpc: ...


class MetaDelivery(Protocol):
    @property
    def destination(self) -> Literal["facebook", "instagram"]: ...

    @property
    def status(self) -> str: ...

    @property
    def receipt(self) -> str: ...


@dataclass(frozen=True, slots=True)
class MetaSocialBatch:
    run_id: str
    batch_id: str
    delivery_status: Mapping[str, object]
    content: SocialContent


class SocialRepository(Protocol):
    def get_batch(
        self,
        *,
        run_key: str,
        reference_at: datetime,
    ) -> MetaSocialBatch | None:
        """Return the exact eligible batch or ``None``."""

    def upload_jpeg(self, *, batch: MetaSocialBatch, jpeg: bytes) -> str:
        """Upload the validated deterministic public JPEG and return its URL."""

    def record_delivery(self, *, run_id: str, result: MetaDelivery) -> None:
        """Persist one sanitized destination result immediately."""


class SupabaseSocialRepository:
    """Service-role adapter for the audited social RPC and public JPEG bucket."""

    BUCKET = "social-media"
    MAX_BYTES = 5 * 1024 * 1024

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        client_factory: Callable[[str, str], object] | None = None,
    ) -> None:
        self._supabase_url = _validated_supabase_url(supabase_url)
        _validate_service_role_key(service_role_key)
        if client_factory is not None and not callable(client_factory):
            raise ValueError("client_factory must be callable")
        active_factory = client_factory or create_client
        try:
            self._client = cast(
                _SupabaseClient,
                active_factory(self._supabase_url, service_role_key),
            )
        except Exception:
            raise RuntimeError("could not create social repository client") from None

    def get_batch(
        self,
        *,
        run_key: str,
        reference_at: datetime,
    ) -> MetaSocialBatch | None:
        if not isinstance(run_key, str) or not run_key.strip():
            raise ValueError("run_key must be a nonblank string")
        if run_key != run_key.strip():
            raise ValueError("run_key must not have surrounding whitespace")
        try:
            response = self._client.rpc(
                "get_meta_social_batch",
                {"requested_run_key": run_key},
            ).execute()
            data = response.data
        except Exception:
            raise RuntimeError("get_meta_social_batch failed") from None
        if data is None:
            return None
        return _normalize_batch(data, reference_at=reference_at)

    def upload_jpeg(self, *, batch: MetaSocialBatch, jpeg: bytes) -> str:
        if not isinstance(batch, MetaSocialBatch):
            raise ValueError("batch must be MetaSocialBatch")
        _canonical_uuid(batch.run_id, field="run_id")
        if batch.content.is_demo is not False:
            raise ValueError("batch content must be a current public pick")
        _validate_jpeg(jpeg, max_bytes=self.MAX_BYTES)
        object_key = batch.content.object_key(batch_id=batch.batch_id)
        try:
            bucket = self._client.storage.from_(self.BUCKET)
            response = bucket.upload(
                path=object_key,
                file=jpeg,
                file_options={
                    "content-type": "image/jpeg",
                    "upsert": "true",
                },
            )
        except Exception:
            raise RuntimeError("social JPEG upload failed") from None
        _validate_upload_response(
            response,
            bucket=self.BUCKET,
            object_key=object_key,
        )
        try:
            public_url = bucket.get_public_url(object_key)
        except Exception:
            raise RuntimeError("social JPEG public URL failed") from None
        return _validated_public_url(
            public_url,
            supabase_url=self._supabase_url,
            bucket=self.BUCKET,
            object_key=object_key,
        )

    def record_delivery(self, *, run_id: str, result: MetaDelivery) -> None:
        normalized_run_id = _canonical_uuid(run_id, field="run_id")
        arguments = _delivery_arguments(
            run_id=normalized_run_id,
            result=result,
        )
        try:
            response = self._client.rpc(
                "record_meta_social_delivery",
                arguments,
            ).execute()
            data = response.data
        except Exception:
            raise RuntimeError("record_meta_social_delivery failed") from None
        if data is not None:
            raise RuntimeError("record_meta_social_delivery returned an invalid response")


def _validated_supabase_url(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or _ASCII_CONTROL.search(value) is not None
        or value != value.strip()
    ):
        raise ValueError("supabase_url must be an HTTPS origin")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("supabase_url must be an HTTPS origin") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (port is not None and port != 443)
    ):
        raise ValueError("supabase_url must be an HTTPS origin")
    return value.rstrip("/")


def _decode_jwt_role(value: str) -> object:
    parts = value.split(".")
    if len(parts) != 3:
        return None
    try:
        encoded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise ValueError("service_role_key must be a valid service-role key") from None
    if not isinstance(payload, dict):
        raise ValueError("service_role_key must be a valid service-role key")
    return payload.get("role")


def _validate_service_role_key(value: object) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("service_role_key must be a nonblank string")
    folded = value.casefold()
    if folded.startswith("sb_publishable_") or folded in {"anon", "anonymous"}:
        raise ValueError("service_role_key must not be an anonymous key")
    role = _decode_jwt_role(value)
    if role is not None and role != "service_role":
        raise ValueError("service_role_key must have the service_role claim")


def _canonical_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str) or value != value.strip() or value != value.lower():
        raise ValueError(f"{field} must be a canonical UUID")
    try:
        normalized = str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"{field} must be a canonical UUID") from None
    if normalized != value:
        raise ValueError(f"{field} must be a canonical UUID")
    return normalized


def _freeze_json(value: object, *, field: str) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeError(f"{field} must be a JSON mapping")
            result[key] = _freeze_json(item, field=field)
        return MappingProxyType(result)
    if isinstance(value, list):
        return tuple(_freeze_json(item, field=field) for item in value)
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise RuntimeError(f"{field} must contain only JSON values")


def _normalize_batch(
    data: object,
    *,
    reference_at: datetime,
) -> MetaSocialBatch:
    if not isinstance(data, Mapping) or set(data.keys()) != _BATCH_FIELDS:
        raise RuntimeError("social batch response must contain the exact fields")
    run_id = _canonical_uuid(data["run_id"], field="run_id")
    batch_id = _canonical_uuid(data["batch_id"], field="batch_id")
    ledger = data["delivery_status"]
    if not isinstance(ledger, Mapping):
        raise RuntimeError("delivery_status must be a mapping")
    frozen_ledger = _freeze_json(ledger, field="delivery_status")
    if not isinstance(frozen_ledger, Mapping):
        raise RuntimeError("delivery_status must be a mapping")
    pick = data["public_pick"]
    if not isinstance(pick, Mapping):
        raise RuntimeError("public_pick must be a mapping")
    content = content_from_public_pick(pick, reference_at=reference_at)
    return MetaSocialBatch(
        run_id=run_id,
        batch_id=batch_id,
        delivery_status=frozen_ledger,
        content=content,
    )


def _validate_jpeg(value: object, *, max_bytes: int) -> None:
    if not isinstance(value, bytes):
        raise ValueError("jpeg must be immutable bytes")
    if len(value) > max_bytes:
        raise ValueError("jpeg must not exceed 5 MiB")
    if len(value) < 4 or not value.startswith(b"\xff\xd8") or not value.endswith(b"\xff\xd9"):
        raise ValueError("jpeg must contain JPEG bytes")
    try:
        with Image.open(BytesIO(value)) as image:
            if image.format != "JPEG":
                raise ValueError("jpeg must use JPEG format")
            if image.mode != "RGB":
                raise ValueError("jpeg must use RGB mode")
            if image.size != (1080, 1080):
                raise ValueError("jpeg must be exactly 1080x1080")
            image.load()
    except (OSError, UnidentifiedImageError):
        raise ValueError("jpeg must contain valid JPEG bytes") from None


def _validate_upload_response(
    response: object,
    *,
    bucket: str,
    object_key: str,
) -> None:
    expected_full_path = f"{bucket}/{object_key}"
    valid = (
        getattr(response, "path", None) == object_key
        and getattr(response, "full_path", None) == expected_full_path
        and getattr(response, "fullPath", None) == expected_full_path
    )
    if not valid:
        raise RuntimeError("social JPEG upload response was invalid")


def _validated_public_url(
    value: object,
    *,
    supabase_url: str,
    bucket: str,
    object_key: str,
) -> str:
    if (
        not isinstance(value, str)
        or _ASCII_CONTROL.search(value) is not None
        or value != value.strip()
    ):
        raise RuntimeError("social JPEG public URL was invalid")
    try:
        parsed = urlsplit(value)
        expected_origin = urlsplit(supabase_url)
        parsed_port = parsed.port
        expected_port = expected_origin.port
    except ValueError:
        raise RuntimeError("social JPEG public URL was invalid") from None
    expected_path = f"/storage/v1/object/public/{bucket}/{object_key}"
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_origin.hostname
        or parsed_port != expected_port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or unquote(parsed.path) != expected_path
    ):
        raise RuntimeError("social JPEG public URL was invalid")
    return value


def _delivery_arguments(
    *,
    run_id: str,
    result: MetaDelivery,
) -> dict[str, object]:
    try:
        destination = result.destination
        status = result.status
        receipt = result.receipt
    except AttributeError:
        raise ValueError("result must be a Meta delivery") from None
    if destination not in {"facebook", "instagram"}:
        raise ValueError("destination must be facebook or instagram")
    if not isinstance(status, str) or status not in _PERSISTED_FAILURES | {"success"}:
        raise ValueError("status is not eligible for persistence")
    if not isinstance(receipt, str):
        raise ValueError("receipt must be a string")
    if status == "success":
        if _SAFE_RECEIPT.fullmatch(receipt) is None:
            raise ValueError("receipt must be a safe remote identifier")
        success = True
        error = ""
    else:
        if receipt != "":
            raise ValueError("receipt must be empty for a failed delivery")
        success = False
        error = status
    return {
        "requested_run_id": run_id,
        "requested_destination": destination,
        "requested_success": success,
        "requested_receipt": receipt,
        "requested_error": error,
    }

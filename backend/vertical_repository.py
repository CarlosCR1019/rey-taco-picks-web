"""Fail-closed Supabase ledger boundary for vertical media delivery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import re
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4
import warnings

from PIL import Image, UnidentifiedImageError
from supabase import create_client

from backend.social_repository import (
    _validate_upload_response,
    _validate_service_role_key,
    _validated_public_url,
    _validated_supabase_url,
)
from backend.vertical_content import ReelPackage, VerticalCard


_CONTENT_KINDS = frozenset(
    {
        "public_pick_story",
        "vip_teaser_story",
        "final_results_story",
        "verified_result_story",
        "ticket_evidence_story",
        "reel_cta_story",
        "daily_results_reel",
    }
)
_DESTINATIONS = frozenset({"instagram_story", "instagram_reel", "facebook_reel"})
_FAILURES = frozenset(
    {"not_configured", "token_invalid", "delivery_failed", "media_invalid"}
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAFE_RECEIPT = re.compile(r"^[A-Za-z0-9_:-]{1,256}$")
_STORY_KINDS = _CONTENT_KINDS - {"daily_results_reel"}
_STORY_OBJECT_KEY = re.compile(
    r"^stories/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})/"
    rf"(?P<kind>{'|'.join(sorted(_STORY_KINDS))})-"
    r"(?P<digest>[0-9a-f]{64})[.]jpg$"
)
_REEL_OBJECT_KEY = re.compile(
    r"^reels/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})/"
    r"daily_results_reel-(?P<digest>[0-9a-f]{64})[.]mp4$"
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

    def remove(self, paths: list[str]) -> object: ...


class _Storage(Protocol):
    def from_(self, bucket_name: str) -> _StorageBucket: ...


class _SupabaseClient(Protocol):
    storage: _Storage

    def rpc(
        self,
        function_name: str,
        arguments: dict[str, object],
    ) -> _SupabaseRpc: ...


@dataclass(frozen=True, slots=True)
class VerticalClaim:
    state: Literal["claimed", "complete", "ambiguous"]
    attempt_id: str | None


@dataclass(frozen=True, slots=True)
class TemporaryAsset:
    object_key: str
    url: str
    mime_type: Literal["image/jpeg", "video/mp4"]


class SupabaseVerticalRepository:
    """Service-role adapter for atomic vertical delivery claims."""

    BUCKET = "social-vertical"
    MAX_STORY_BYTES = 5 * 1024 * 1024

    def __init__(
        self,
        *,
        url: str,
        service_role_key: str,
        client_factory: Callable[[str, str], object] | None = None,
    ) -> None:
        self._url = _validated_supabase_url(url)
        _validate_service_role_key(service_role_key)
        if client_factory is not None and not callable(client_factory):
            raise ValueError("client_factory must be callable")
        factory = client_factory or create_client
        try:
            self._client = cast(_SupabaseClient, factory(self._url, service_role_key))
        except Exception:
            raise RuntimeError("could not create vertical repository client") from None

    def upload_story(self, *, card: VerticalCard, jpeg: bytes) -> TemporaryAsset:
        if not isinstance(card, VerticalCard):
            raise ValueError("story upload requires one VerticalCard")
        _validated_package(card)
        _validate_story_jpeg(jpeg, max_bytes=self.MAX_STORY_BYTES)
        object_key = (
            f"stories/{card.portfolio_date}/{card.kind}-{card.digest}.jpg"
        )
        try:
            bucket = self._client.storage.from_(self.BUCKET)
            response = bucket.upload(
                path=object_key,
                file=jpeg,
                file_options={"content-type": "image/jpeg", "upsert": "true"},
            )
        except Exception:
            raise RuntimeError("temporary story upload failed") from None
        try:
            _validate_upload_response(
                response,
                bucket=self.BUCKET,
                object_key=object_key,
            )
        except Exception:
            _best_effort_remove(bucket, object_key)
            raise
        try:
            raw_url = bucket.get_public_url(object_key)
        except Exception:
            _best_effort_remove(bucket, object_key)
            raise RuntimeError("temporary story public URL failed") from None
        try:
            url = _validated_public_url(
                raw_url,
                supabase_url=self._url,
                bucket=self.BUCKET,
                object_key=object_key,
            )
        except Exception:
            _best_effort_remove(bucket, object_key)
            raise
        return TemporaryAsset(object_key, url, "image/jpeg")

    def delete_temporary(self, asset: TemporaryAsset) -> None:
        object_key = _validated_temporary_asset(
            asset,
            supabase_url=self._url,
            bucket=self.BUCKET,
        )
        try:
            result = self._client.storage.from_(self.BUCKET).remove(
                [object_key]
            )
        except Exception:
            raise RuntimeError("temporary asset cleanup failed") from None
        _validate_remove_response(result, object_key)

    def claim(
        self,
        *,
        batch_id: str,
        portfolio_date: str,
        content_kind: str,
        destination: str,
        digest: str,
        template_version: int,
    ) -> VerticalClaim:
        normalized_batch = _canonical_uuid(batch_id, field="batch_id")
        normalized_date = _canonical_date(portfolio_date)
        normalized_kind = _content_kind(content_kind)
        normalized_destination = _destination(destination)
        normalized_digest = _digest(digest)
        normalized_version = _template_version(template_version)
        attempt_id = str(uuid4())
        lease = datetime.now(timezone.utc) + timedelta(minutes=8)
        arguments: dict[str, object] = {
            "requested_batch_id": normalized_batch,
            "requested_portfolio_date": normalized_date,
            "requested_content_kind": normalized_kind,
            "requested_destination": normalized_destination,
            "requested_content_digest": normalized_digest,
            "requested_template_version": normalized_version,
            "requested_attempt_id": attempt_id,
            "requested_lease_expires_at": lease.isoformat(),
        }
        try:
            raw = (
                self._client.rpc("claim_vertical_media_delivery", arguments)
                .execute()
                .data
            )
        except Exception:
            raise RuntimeError("vertical claim failed") from None
        value = _one_exact(raw, {"state", "attempt_id"})
        if value == {"state": "claimed", "attempt_id": attempt_id}:
            return VerticalClaim("claimed", attempt_id)
        state = value["state"]
        if state in {"complete", "ambiguous"} and value["attempt_id"] is None:
            return VerticalClaim(cast(Literal["complete", "ambiguous"], state), None)
        raise RuntimeError("vertical claim returned invalid data")

    def complete(
        self,
        *,
        package: VerticalCard | ReelPackage,
        destination: str,
        attempt_id: str,
        success: bool,
        receipt: str = "",
        error: str = "",
    ) -> None:
        arguments = _validated_completion(
            package, destination, attempt_id, success, receipt, error
        )
        for index in range(2):
            try:
                raw = (
                    self._client.rpc("complete_vertical_media_delivery", arguments)
                    .execute()
                    .data
                )
            except Exception:
                if index == 0:
                    continue
                raise RuntimeError("vertical completion failed") from None
            try:
                value = _one_exact(raw, {"completed"})
            except RuntimeError:
                if index == 0:
                    continue
                raise
            if value.get("completed") is True:
                return
            if index == 1:
                raise RuntimeError("vertical completion was not persisted")
        raise RuntimeError("vertical completion failed")

    def begin_remote_delivery(
        self,
        *,
        package: VerticalCard | ReelPackage,
        destination: str,
        attempt_id: str,
    ) -> None:
        arguments = _validated_remote_transition(
            package,
            destination,
            attempt_id,
        )
        for index in range(2):
            try:
                raw = (
                    self._client.rpc("begin_vertical_remote_delivery", arguments)
                    .execute()
                    .data
                )
            except Exception:
                if index == 0:
                    continue
                raise RuntimeError("vertical remote transition failed") from None
            try:
                value = _one_exact(raw, {"started"})
            except RuntimeError:
                if index == 0:
                    continue
                raise
            if value.get("started") is True:
                return
            if index == 1:
                raise RuntimeError("vertical remote transition was not persisted")
        raise RuntimeError("vertical remote transition failed")


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


def _validate_story_jpeg(value: object, *, max_bytes: int) -> None:
    if not isinstance(value, bytes):
        raise ValueError("story jpeg must be immutable bytes")
    if len(value) > max_bytes:
        raise ValueError("story jpeg must not exceed 5 MiB")
    if len(value) < 4 or not value.startswith(b"\xff\xd8") or not value.endswith(
        b"\xff\xd9"
    ):
        raise ValueError("story jpeg must contain JPEG bytes")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(value)) as image:
                if image.format != "JPEG":
                    raise ValueError("story jpeg must use JPEG format")
                if image.mode != "RGB":
                    raise ValueError("story jpeg must use RGB mode")
                if image.size != (1080, 1920):
                    raise ValueError("story jpeg must be exactly 1080x1920")
                image.load()
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ValueError("story jpeg must contain valid JPEG bytes") from None


def _validate_remove_response(value: object, object_key: str) -> None:
    valid = (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], dict)
        and value[0].get("name") == object_key
    )
    if not valid:
        raise RuntimeError("temporary asset cleanup response was invalid")


def _best_effort_remove(bucket: _StorageBucket, object_key: str) -> None:
    try:
        response = bucket.remove([object_key])
        _validate_remove_response(response, object_key)
    except Exception:
        return


def _validated_temporary_asset(
    asset: object,
    *,
    supabase_url: str,
    bucket: str,
) -> str:
    if not isinstance(asset, TemporaryAsset):
        raise ValueError("temporary asset is invalid")
    object_key = asset.object_key
    expected_mime: str | None = None
    match: re.Match[str] | None = None
    if isinstance(object_key, str):
        match = _STORY_OBJECT_KEY.fullmatch(object_key)
        if match is not None:
            expected_mime = "image/jpeg"
        else:
            match = _REEL_OBJECT_KEY.fullmatch(object_key)
            if match is not None:
                expected_mime = "video/mp4"
    if match is None or asset.mime_type != expected_mime:
        raise ValueError("temporary asset key or MIME type is invalid")
    try:
        _canonical_date(match.group("date"))
        _validated_public_url(
            asset.url,
            supabase_url=supabase_url,
            bucket=bucket,
            object_key=object_key,
        )
    except (RuntimeError, ValueError):
        raise ValueError("temporary asset URL or date is invalid") from None
    return object_key


def _canonical_date(value: object) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("portfolio_date must be a canonical date")
    try:
        normalized = date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("portfolio_date must be a canonical date") from None
    if normalized != value:
        raise ValueError("portfolio_date must be a canonical date")
    return normalized


def _content_kind(value: object) -> str:
    if not isinstance(value, str) or value not in _CONTENT_KINDS:
        raise ValueError("vertical content kind is invalid")
    return value


def _destination(value: object) -> str:
    if not isinstance(value, str) or value not in _DESTINATIONS:
        raise ValueError("vertical destination is invalid")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("vertical digest is invalid")
    return value


def _template_version(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("vertical template version is invalid")
    return value


def _validated_package(
    package: VerticalCard | ReelPackage,
) -> tuple[str, str, str, str, int]:
    if not isinstance(package, (VerticalCard, ReelPackage)):
        raise ValueError("vertical package is invalid")
    return (
        _canonical_uuid(package.batch_id, field="batch_id"),
        _canonical_date(package.portfolio_date),
        _content_kind(package.kind),
        _digest(package.digest),
        _template_version(package.template_version),
    )


def _validated_completion(
    package: VerticalCard | ReelPackage,
    destination: str,
    attempt_id: str,
    success: bool,
    receipt: str,
    error: str,
) -> dict[str, object]:
    batch_id, _, kind, digest, template_version = _validated_package(package)
    normalized_destination = _destination(destination)
    normalized_attempt = _canonical_uuid(attempt_id, field="attempt_id")
    if type(success) is not bool:
        raise ValueError("vertical completion identity is invalid")
    if not isinstance(receipt, str) or not isinstance(error, str):
        raise ValueError("vertical completion outcome is invalid")
    if success:
        if error or _SAFE_RECEIPT.fullmatch(receipt) is None:
            raise ValueError("vertical success requires one safe receipt")
    elif receipt or error not in _FAILURES:
        raise ValueError("vertical failure requires one allowed error")
    return {
        "requested_batch_id": batch_id,
        "requested_content_kind": kind,
        "requested_destination": normalized_destination,
        "requested_content_digest": digest,
        "requested_template_version": template_version,
        "requested_attempt_id": normalized_attempt,
        "requested_success": success,
        "requested_receipt": receipt if success else "",
        "requested_error": "" if success else error,
    }


def _validated_remote_transition(
    package: VerticalCard | ReelPackage,
    destination: str,
    attempt_id: str,
) -> dict[str, object]:
    batch_id, _, kind, digest, template_version = _validated_package(package)
    return {
        "requested_batch_id": batch_id,
        "requested_content_kind": kind,
        "requested_destination": _destination(destination),
        "requested_content_digest": digest,
        "requested_template_version": template_version,
        "requested_attempt_id": _canonical_uuid(
            attempt_id,
            field="attempt_id",
        ),
    }


def _one_exact(value: object, keys: set[str]) -> dict[str, object]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict) or set(value) != keys:
        raise RuntimeError("vertical RPC returned invalid data")
    return dict(value)

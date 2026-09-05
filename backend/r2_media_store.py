"""Fail-closed Cloudflare R2 adapter for approved media objects."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
import hashlib
import os
from pathlib import PurePosixPath
import re
from typing import Any, Callable
from urllib.parse import urlsplit

from backend.media_store import MediaObject


_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_EXTENSIONS = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "mp4": "video/mp4"}
_CONTENT_KINDS = {
    "public_pick_story",
    "vip_teaser_story",
    "final_results_story",
    "verified_result_story",
    "ticket_evidence_story",
    "reel_cta_story",
    "daily_results_reel",
}
_DERIVED = re.compile(
    r"^derived/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})/"
    r"(?P<kind>[a-z0-9_-]+)/(?P<digest>[0-9a-f]{64})\."
    r"(?P<extension>jpg|jpeg|mp4)$"
)
_EVIDENCE = re.compile(
    r"^evidence/(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})/"
    r"(?P<digest>[0-9a-f]{64})\.(?P<extension>jpg|jpeg|mp4)$"
)
_TEMPORARY = re.compile(r"^tmp/[a-z0-9][a-z0-9._/-]{0,200}$")
_ALLOWED_CONTENT_TYPES = frozenset(_EXTENSIONS.values())
_MAX_BYTES = {"image/jpeg": 5 * 1024 * 1024, "video/mp4": 50 * 1024 * 1024}


def _validate_date(value: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("media date is invalid")
    try:
        normalized = date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("media date is invalid") from None
    if normalized != value:
        raise ValueError("media date is invalid")
    return normalized


def _validate_digest(value: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("media digest is invalid")
    return value


def _validate_extension(value: str) -> str:
    if not isinstance(value, str) or value not in _EXTENSIONS:
        raise ValueError("media extension is invalid")
    return value


def derived_object_key(
    portfolio_date: str,
    content_kind: str,
    digest: str,
    extension: str,
) -> str:
    normalized_date = _validate_date(portfolio_date)
    if not isinstance(content_kind, str) or content_kind not in _CONTENT_KINDS:
        raise ValueError("media content kind is invalid")
    normalized_digest = _validate_digest(digest)
    normalized_extension = _validate_extension(extension)
    return f"derived/{normalized_date}/{content_kind}/{normalized_digest}.{normalized_extension}"


def evidence_object_key(received_date: str, digest: str, extension: str) -> str:
    normalized_date = _validate_date(received_date)
    normalized_digest = _validate_digest(digest)
    normalized_extension = _validate_extension(extension)
    return f"evidence/{normalized_date}/{normalized_digest}.{normalized_extension}"


def _validated_object_key(value: object) -> tuple[str, re.Match[str] | None, bool]:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("object key is invalid")
    match = _DERIVED.fullmatch(value) or _EVIDENCE.fullmatch(value)
    if match is not None:
        _validate_date(match.group("date"))
        if "kind" in match.groupdict():
            kind = match.group("kind")
            if kind not in _CONTENT_KINDS:
                raise ValueError("object key is invalid")
        _validate_digest(match.group("digest"))
        _validate_extension(match.group("extension"))
        return value, match, value.startswith("derived/")
    if _TEMPORARY.fullmatch(value) is not None:
        return value, None, False
    raise ValueError("object key is invalid")


def _validate_payload(
    object_key: object,
    payload: object,
    content_type: object,
) -> tuple[str, bytes, str, str, bool]:
    normalized_key, match, derived = _validated_object_key(object_key)
    if not isinstance(payload, bytes):
        raise ValueError("media payload must be immutable bytes")
    if not isinstance(content_type, str) or content_type not in _ALLOWED_CONTENT_TYPES:
        raise ValueError("media content type is invalid")
    if len(payload) == 0 or len(payload) > _MAX_BYTES[content_type]:
        raise ValueError("media payload size is invalid")
    if match is not None:
        expected_type = _EXTENSIONS[match.group("extension")]
        if expected_type != content_type:
            raise ValueError("media extension and content type do not match")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != match.group("digest"):
            raise ValueError("object digest does not match key")
    else:
        digest = hashlib.sha256(payload).hexdigest()
    return normalized_key, payload, content_type, digest, derived


def _safe_metadata(metadata: Mapping[str, str] | None) -> dict[str, str]:
    if metadata is None:
        return {}
    if not isinstance(metadata, Mapping):
        raise ValueError("media metadata is invalid")
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key
            or len(key) > 64
            or len(value) > 256
            or any(ord(char) < 32 or ord(char) == 127 for char in key + value)
        ):
            raise ValueError("media metadata is invalid")
        normalized[key] = value
    return normalized


class R2MediaStore:
    """S3-compatible object store with no bucket-management side effects."""

    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        *,
        client: Any,
        public_base_url: str = "",
    ) -> None:
        for value, name in (
            (account_id, "account id"),
            (access_key_id, "access key id"),
            (secret_access_key, "secret access key"),
            (bucket, "bucket"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"R2 {name} is invalid")
        if client is None:
            raise ValueError("R2 client is invalid")
        self._bucket = bucket.strip()
        self._client = client
        self._public_base_url = public_base_url.strip()

    @classmethod
    def from_environment(
        cls,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> "R2MediaStore":
        names = (
            "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET",
        )
        values = {name: os.getenv(name, "").strip() for name in names}
        if any(not value for value in values.values()):
            raise RuntimeError("R2 configuration is incomplete")
        public_base_url = os.getenv("R2_PUBLIC_BASE_URL", "").strip()
        if public_base_url:
            parsed = urlsplit(public_base_url)
            if parsed.scheme != "https" or not parsed.netloc or parsed.path not in {"", "/"}:
                raise RuntimeError("R2 public base URL is invalid")
        endpoint = f"https://{values['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
        factory = client_factory
        if factory is None:
            try:
                import boto3
            except ImportError:
                raise RuntimeError("R2 client dependency unavailable") from None
            factory = boto3.client
        try:
            client = factory(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=values["R2_ACCESS_KEY_ID"],
                aws_secret_access_key=values["R2_SECRET_ACCESS_KEY"],
                region_name="auto",
            )
        except TypeError:
            client = factory(
                endpoint_url=endpoint,
                aws_access_key_id=values["R2_ACCESS_KEY_ID"],
                aws_secret_access_key=values["R2_SECRET_ACCESS_KEY"],
                region_name="auto",
            )
        except Exception:
            raise RuntimeError("R2 client could not be created") from None
        return cls(**values, client=client, public_base_url=public_base_url)

    def put(
        self,
        object_key: str,
        payload: bytes,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> MediaObject:
        normalized_key, normalized_payload, normalized_type, digest, derived = _validate_payload(
            object_key, payload, content_type
        )
        safe_metadata = _safe_metadata(metadata)
        public = derived and safe_metadata.get("visibility", "public") == "public"
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=normalized_key,
                Body=normalized_payload,
                ContentType=normalized_type,
                Metadata=safe_metadata,
            )
        except Exception:
            raise RuntimeError("R2 upload failed") from None
        return MediaObject(normalized_key, normalized_type, digest, len(normalized_payload), public)

    def get(self, object_key: str) -> bytes:
        normalized_key, _, _ = _validated_object_key(object_key)
        try:
            value = self._client.get_object(Bucket=self._bucket, Key=normalized_key)
            body = value["Body"]
            payload = body.read()
        except Exception:
            raise RuntimeError("R2 download failed") from None
        if not isinstance(payload, bytes):
            raise RuntimeError("R2 download returned invalid data")
        return payload

    def temporary_delivery_url(self, object_key: str, expires_in: int) -> str:
        normalized_key, _, _ = _validated_object_key(object_key)
        if type(expires_in) is not int or not 60 <= expires_in <= 900:
            raise ValueError("temporary URL TTL is invalid")
        try:
            value = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": normalized_key},
                ExpiresIn=expires_in,
            )
        except Exception:
            raise RuntimeError("R2 temporary URL failed") from None
        if not isinstance(value, str) or urlsplit(value).scheme != "https":
            raise RuntimeError("R2 temporary URL was invalid")
        return value

    def delete_temporary(self, object_key: str) -> None:
        if not isinstance(object_key, str) or _TEMPORARY.fullmatch(object_key) is None:
            raise ValueError("temporary object key is invalid")
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
        except Exception:
            raise RuntimeError("R2 temporary cleanup failed") from None

    def exists(self, object_key: str) -> bool:
        normalized_key, _, _ = _validated_object_key(object_key)
        try:
            self._client.head_object(Bucket=self._bucket, Key=normalized_key)
        except Exception as error:
            response = getattr(error, "response", None)
            code = response.get("Error", {}).get("Code") if isinstance(response, Mapping) else None
            if str(code) == "404":
                return False
            raise RuntimeError("R2 existence check failed") from None
        return True

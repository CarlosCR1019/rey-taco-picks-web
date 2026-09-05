"""Adapter over the existing Supabase social-vertical bucket."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from backend.media_store import MediaObject
from backend.r2_media_store import _TEMPORARY, _validate_payload, _validated_object_key
from backend.social_repository import _validate_service_role_key, _validated_supabase_url


class SupabaseMediaStore:
    BUCKET = "social-vertical"

    def __init__(self, *, client: Any, supabase_url: str, service_role_key: str) -> None:
        if client is None or not callable(getattr(getattr(client, "storage", None), "from_", None)):
            raise ValueError("Supabase media client is invalid")
        self._url = _validated_supabase_url(supabase_url)
        _validate_service_role_key(service_role_key)
        self._client = client

    def _bucket(self) -> Any:
        try:
            return self._client.storage.from_(self.BUCKET)
        except Exception:
            raise RuntimeError("Supabase media bucket is unavailable") from None

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
        safe_metadata = dict(metadata or {})
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in safe_metadata.items()
        ):
            raise ValueError("media metadata is invalid")
        try:
            response = self._bucket().upload(
                path=normalized_key,
                file=normalized_payload,
                file_options={"content-type": normalized_type, "upsert": "true"},
            )
        except Exception:
            raise RuntimeError("Supabase media upload failed") from None
        if (
            getattr(response, "path", None) != normalized_key
            or getattr(response, "full_path", None) != f"{self.BUCKET}/{normalized_key}"
        ):
            raise RuntimeError("Supabase media upload response was invalid")
        public = derived and safe_metadata.get("visibility", "public") == "public"
        return MediaObject(normalized_key, normalized_type, digest, len(normalized_payload), public)

    def get(self, object_key: str) -> bytes:
        normalized_key, _, _ = _validated_object_key(object_key)
        try:
            value = self._bucket().download(normalized_key)
        except Exception:
            raise RuntimeError("Supabase media download failed") from None
        if not isinstance(value, bytes):
            raise RuntimeError("Supabase media download returned invalid data")
        return value

    def temporary_delivery_url(self, object_key: str, expires_in: int) -> str:
        normalized_key, _, _ = _validated_object_key(object_key)
        if type(expires_in) is not int or not 60 <= expires_in <= 900:
            raise ValueError("temporary URL TTL is invalid")
        try:
            response = self._bucket().create_signed_url(normalized_key, expires_in)
            value = response.get("signedURL") if isinstance(response, Mapping) else None
        except Exception:
            raise RuntimeError("Supabase temporary URL failed") from None
        if not isinstance(value, str) or urlsplit(value).scheme != "https":
            raise RuntimeError("Supabase temporary URL was invalid")
        return value

    def delete_temporary(self, object_key: str) -> None:
        if not isinstance(object_key, str) or _TEMPORARY.fullmatch(object_key) is None:
            raise ValueError("temporary object key is invalid")
        try:
            response = self._bucket().remove([object_key])
        except Exception:
            raise RuntimeError("Supabase temporary cleanup failed") from None
        if not isinstance(response, list) or len(response) != 1 or response[0].get("name") != object_key:
            raise RuntimeError("Supabase temporary cleanup response was invalid")

    def exists(self, object_key: str) -> bool:
        normalized_key, _, _ = _validated_object_key(object_key)
        try:
            self._bucket().download(normalized_key)
        except FileNotFoundError:
            return False
        except Exception:
            raise RuntimeError("Supabase existence check failed") from None
        return True

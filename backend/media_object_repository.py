"""Validated Supabase ledger for approved media objects."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from backend.media_store import MediaObject
from backend.r2_media_store import _CONTENT_KINDS, _validated_object_key


def _date(value: object) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("portfolio_date is invalid")
    try:
        normalized = date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("portfolio_date is invalid") from None
    if normalized != value:
        raise ValueError("portfolio_date is invalid")
    return normalized


def _batch(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("source_batch_id is invalid")
    try:
        normalized = str(UUID(value))
    except ValueError:
        raise ValueError("source_batch_id is invalid") from None
    if normalized != value:
        raise ValueError("source_batch_id is invalid")
    return normalized


class MediaObjectRepository:
    def __init__(self, client: Any) -> None:
        if client is None or not callable(getattr(client, "table", None)):
            raise ValueError("media object client is invalid")
        self._client = client

    def register_approved(
        self,
        media_object: MediaObject,
        *,
        portfolio_date: str,
        content_kind: str,
        source_batch_id: str | None,
        storage_backend: str,
    ) -> str:
        if not isinstance(media_object, MediaObject):
            raise ValueError("media object is invalid")
        normalized_date = _date(portfolio_date)
        if content_kind not in _CONTENT_KINDS:
            raise ValueError("content kind is invalid")
        if storage_backend not in {"supabase", "r2"}:
            raise ValueError("storage backend is invalid")
        normalized_batch = _batch(source_batch_id)
        key, match, derived = _validated_object_key(media_object.object_key)
        if match is None or media_object.digest != match.group("digest"):
            raise ValueError("media object identity is invalid")
        if media_object.content_type not in {"image/jpeg", "video/mp4"}:
            raise ValueError("media object content type is invalid")
        if media_object.size_bytes <= 0 or media_object.size_bytes > 50 * 1024 * 1024:
            raise ValueError("media object size is invalid")
        visibility = "public" if media_object.public and derived else "private"
        payload: dict[str, object] = {
            "object_key": key,
            "digest": media_object.digest,
            "content_kind": content_kind,
            "content_type": media_object.content_type,
            "size_bytes": media_object.size_bytes,
            "portfolio_date": normalized_date,
            "source_batch_id": normalized_batch,
            "storage_backend": storage_backend,
            "visibility": visibility,
            "state": "approved",
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            data = (
                self._client.table("media_objects")
                .upsert(payload, on_conflict="object_key")
                .execute()
                .data
            )
        except Exception:
            raise RuntimeError("media object registration failed") from None
        row = data[0] if isinstance(data, list) and len(data) == 1 else None
        if not isinstance(row, Mapping):
            raise RuntimeError("media object registration returned invalid data")
        if row.get("object_key") != key:
            raise RuntimeError("media object registration returned invalid data")
        if row.get("digest") != media_object.digest or row.get("content_type") != media_object.content_type:
            raise RuntimeError("media object identity conflict")
        return key

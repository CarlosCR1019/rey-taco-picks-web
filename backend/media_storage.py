"""Feature flags and backend selection for media work."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.media_store import MediaStore


def media_storage_backend() -> str:
    value = os.getenv("MEDIA_STORAGE_BACKEND", "supabase").strip().lower()
    if value not in {"supabase", "r2"}:
        raise RuntimeError("unsupported media storage backend")
    return value


def remotion_enabled() -> bool:
    return os.getenv("REMOTION_ENABLED", "false").strip().lower() == "true"


def build_media_store(
    *,
    supabase_client: object,
    supabase_url: str,
    service_role_key: str,
) -> "MediaStore":
    if media_storage_backend() == "r2":
        from backend.r2_media_store import R2MediaStore

        return R2MediaStore.from_environment()
    from backend.supabase_media_store import SupabaseMediaStore

    return SupabaseMediaStore(
        client=supabase_client,
        supabase_url=supabase_url,
        service_role_key=service_role_key,
    )

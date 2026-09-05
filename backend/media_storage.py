"""Feature flags and backend selection for media work."""

from __future__ import annotations

import os


def media_storage_backend() -> str:
    value = os.getenv("MEDIA_STORAGE_BACKEND", "supabase").strip().lower()
    if value not in {"supabase", "r2"}:
        raise RuntimeError("unsupported media storage backend")
    return value


def remotion_enabled() -> bool:
    return os.getenv("REMOTION_ENABLED", "false").strip().lower() == "true"

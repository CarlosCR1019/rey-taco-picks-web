"""Small, dependency-free contract for derived media storage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class MediaObject:
    """Metadata returned after a validated object upload."""

    object_key: str
    content_type: str
    digest: str
    size_bytes: int
    public: bool


class MediaStore(Protocol):
    """Storage operations needed by the media delivery pipeline."""

    def put(
        self,
        object_key: str,
        payload: bytes,
        content_type: str,
        metadata: Mapping[str, str],
    ) -> MediaObject: ...

    def get(self, object_key: str) -> bytes: ...

    def temporary_delivery_url(self, object_key: str, expires_in: int) -> str: ...

    def delete_temporary(self, object_key: str) -> None: ...

    def exists(self, object_key: str) -> bool: ...

"""Idempotent persistence and safe public-file publication for pick batches."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping, Protocol, Sequence

from backend.publishing_policy import public_payload


class BatchRepository(Protocol):
    """The durable batch store used by the publisher."""

    def publish(
        self, run_key: str, source_hash: str, picks: Sequence[Mapping[str, object]]
    ) -> dict[str, object]: ...

    def record_delivery(
        self, run_id: str, destination: str, success: bool, error: str = ""
    ) -> None: ...


@dataclass(frozen=True)
class PublicationResult:
    run_id: str | None
    batch_id: str | None
    created: bool
    delivery_status: dict[str, object]
    dry_run: bool = False


class SupabaseBatchRepository:
    """Supabase RPC implementation of the batch repository boundary."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def publish(
        self, run_key: str, source_hash: str, picks: Sequence[Mapping[str, object]]
    ) -> dict[str, object]:
        response = self._client.rpc(
            "publish_pick_batch",
            {
                "requested_run_key": run_key,
                "requested_source_hash": source_hash,
                "requested_picks": picks,
            },
        ).execute()
        return _normalized_publish_response(getattr(response, "data", None))

    def record_delivery(
        self, run_id: str, destination: str, success: bool, error: str = ""
    ) -> None:
        self._client.rpc(
            "record_scraper_delivery",
            {
                "requested_run_id": run_id,
                "requested_destination": destination,
                "requested_success": success,
                "requested_error": error,
            },
        ).execute()


def source_hash_for(picks: Sequence[Mapping[str, object]]) -> str:
    """Return a stable digest for a batch irrespective of mapping key order."""
    encoded = json.dumps(
        picks, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def publish_batch(
    repository: BatchRepository,
    picks: Sequence[Mapping[str, object]],
    run_key: str,
    public_path: str | Path,
    *,
    dry_run: bool = False,
) -> PublicationResult:
    """Publish a database batch before atomically exposing its public selection."""
    if not picks:
        raise ValueError("picks must not be empty")
    if not isinstance(run_key, str) or not run_key.strip():
        raise ValueError("run_key must not be empty")
    if dry_run:
        return PublicationResult(None, None, False, {}, dry_run=True)

    response = repository.publish(run_key, source_hash_for(picks), picks)
    result = _publication_result(response)
    _write_public_payload(public_path, public_payload(picks))
    return result


def _normalized_publish_response(data: object) -> dict[str, object]:
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise RuntimeError("publish_pick_batch returned an invalid response: run_id and batch_id are required")

    run_id = data.get("run_id")
    batch_id = data.get("batch_id")
    if not isinstance(run_id, str) or not run_id.strip() or not isinstance(batch_id, str) or not batch_id.strip():
        raise RuntimeError("publish_pick_batch returned an invalid response: run_id and batch_id are required")

    delivery_status = data.get("delivery_status", {})
    if not isinstance(delivery_status, dict):
        raise RuntimeError("publish_pick_batch returned an invalid delivery_status")

    return {
        "run_id": run_id,
        "batch_id": batch_id,
        "created": bool(data.get("created", False)),
        "delivery_status": delivery_status,
    }


def _publication_result(response: Mapping[str, object]) -> PublicationResult:
    normalized = _normalized_publish_response(dict(response))
    return PublicationResult(
        run_id=normalized["run_id"],
        batch_id=normalized["batch_id"],
        created=normalized["created"],
        delivery_status=normalized["delivery_status"],
    )


def _write_public_payload(public_path: str | Path, payload: object) -> None:
    destination = Path(public_path)
    temp_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temp_path = Path(temporary.name)
            json.dump(payload, temporary, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp_path, destination)
    except OSError as error:
        raise RuntimeError("failed to write public picks file") from error
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

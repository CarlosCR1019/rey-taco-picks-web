"""Idempotent persistence and safe public-file publication for pick batches."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping, Protocol, Sequence, TypedDict

from backend.publishing_policy import public_payload


PERSISTED_PICK_COLUMNS = frozenset(
    {
        "categoria",
        "partido",
        "pick",
        "cuota",
        "confianza",
        "razonamiento",
        "marcador",
        "estado",
        "es_parlay",
        "liga",
        "mercado",
        "riesgo",
        "resultado_apuesta",
        "ganancia_simulada",
        "fecha_generacion",
        "fecha_evento",
        "horario",
        "odds_mercado",
        "tiene_valor",
        "visibility",
        "source",
        "source_event_id",
        "source_market_key",
        "source_selection_key",
        "source_observed_at",
    }
)


class PublishResponse(TypedDict):
    run_id: str
    batch_id: str
    created: bool
    delivery_status: dict[str, object]


class _SupabaseResponse(Protocol):
    data: object


class _SupabaseRpc(Protocol):
    def execute(self) -> _SupabaseResponse: ...


class _SupabaseClient(Protocol):
    def rpc(self, function_name: str, arguments: dict[str, object]) -> _SupabaseRpc: ...


class BatchRepository(Protocol):
    """The durable batch store used by the publisher."""

    def publish(
        self, run_key: str, source_hash: str, picks: Sequence[Mapping[str, object]]
    ) -> PublishResponse: ...

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


@dataclass(frozen=True)
class AuditedBatchPublisher:
    """Typed application adapter for the atomic audited batch publisher."""

    repository: BatchRepository
    run_key: str
    public_path: str | Path

    def publish(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        dry_run: bool,
    ) -> PublicationResult:
        projected = _project_persisted_rows(rows)
        return publish_batch(
            self.repository,
            projected,
            self.run_key,
            self.public_path,
            dry_run=dry_run,
        )


class SupabaseBatchRepository:
    """Supabase RPC implementation of the batch repository boundary."""

    def __init__(self, client: _SupabaseClient) -> None:
        self._client = client

    def publish(
        self, run_key: str, source_hash: str, picks: Sequence[Mapping[str, object]]
    ) -> PublishResponse:
        response = self._client.rpc(
            "publish_pick_batch",
            {
                "requested_run_key": run_key,
                "requested_source_hash": source_hash,
                "requested_picks": picks,
            },
        ).execute()
        return _normalized_publish_response(response.data)

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


def _project_persisted_rows(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise ValueError("picks must be a sequence")
    projected = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("each pick must be a mapping")
        projected.append(
            {key: value for key, value in row.items() if key in PERSISTED_PICK_COLUMNS}
        )
    return tuple(projected)


def publish_batch(
    repository: BatchRepository,
    picks: Sequence[Mapping[str, object]],
    run_key: str,
    public_path: str | Path,
    *,
    dry_run: bool = False,
) -> PublicationResult:
    """Publish a database batch before atomically exposing its public selection."""
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean")
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


def _normalized_publish_response(data: object) -> PublishResponse:
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    response = _string_keyed_dict(data)
    if response is None:
        raise RuntimeError("publish_pick_batch returned an invalid response: run_id and batch_id are required")

    run_id = response.get("run_id")
    batch_id = response.get("batch_id")
    if not isinstance(run_id, str) or not run_id.strip() or not isinstance(batch_id, str) or not batch_id.strip():
        raise RuntimeError("publish_pick_batch returned an invalid response: run_id and batch_id are required")

    created = response.get("created")
    if not isinstance(created, bool):
        raise RuntimeError("publish_pick_batch returned an invalid response: created must be a boolean")

    delivery_status = _string_keyed_dict(response.get("delivery_status"))
    if delivery_status is None:
        raise RuntimeError("publish_pick_batch returned an invalid delivery_status")

    return {
        "run_id": run_id,
        "batch_id": batch_id,
        "created": created,
        "delivery_status": delivery_status,
    }


def _string_keyed_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        normalized[key] = item
    return normalized


def _publication_result(response: PublishResponse) -> PublicationResult:
    return PublicationResult(
        run_id=response["run_id"],
        batch_id=response["batch_id"],
        created=response["created"],
        delivery_status=response["delivery_status"],
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

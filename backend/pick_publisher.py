"""Idempotent persistence and safe public-file publication for pick batches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Callable, Mapping, Protocol, Sequence, TypedDict

from backend.publishing_policy import expected_public_pick_count, public_payload


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
        "source_starts_at",
    }
)
DAILY_STAGE_PICK_COLUMNS = PERSISTED_PICK_COLUMNS | {"physical_event_key"}
RETURNED_PICK_COLUMNS = PERSISTED_PICK_COLUMNS | {"id"}
_UTC_SOURCE_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:[.][0-9]{1,6})?(?:Z|[+]00:00)$"
)
_PHYSICAL_EVENT_KEY = re.compile(r"^physical:v1:[0-9a-f]{64}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class PersistedPick(Mapping[str, object]):
    """Immutable defensive copy of one row returned by the database."""

    _items: tuple[tuple[str, object], ...]

    def __getitem__(self, key: str) -> object:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self):
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)


class PublishResponse(TypedDict):
    run_id: str
    batch_id: str
    created: bool
    delivery_status: dict[str, object]
    picks: tuple[PersistedPick, ...]


class DailyStageResponse(TypedDict):
    scan_id: str
    portfolio_date: str
    revision: int
    created: bool


class DailyPublishResponse(PublishResponse):
    portfolio_date: str
    revision: int
    feed_eligible: bool
    delivery_picks: tuple[PersistedPick, ...]


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

    def resume(self, run_key: str) -> PublishResponse | None: ...

    def stage_daily(
        self,
        run_key: str,
        portfolio_date: str,
        source_hash: str,
        picks: Sequence[Mapping[str, object]],
    ) -> DailyStageResponse: ...

    def release_daily(
        self, run_key: str, portfolio_date: str
    ) -> DailyPublishResponse | None: ...

    def resume_daily(self, run_key: str) -> DailyPublishResponse | None: ...

    def record_residential_events(
        self, events: Sequence[Mapping[str, object]]
    ) -> int: ...

    def record_delivery(
        self, run_id: str, destination: str, success: bool, error: str = ""
    ) -> None: ...


@dataclass(frozen=True)
class PublicationResult:
    run_id: str | None
    batch_id: str | None
    created: bool
    delivery_status: dict[str, object]
    picks: tuple[PersistedPick, ...] = ()
    delivery_picks: tuple[PersistedPick, ...] = ()
    portfolio_date: str | None = None
    revision: int | None = None
    feed_eligible: bool = True
    dry_run: bool = False


@dataclass(frozen=True)
class DailyStageResult:
    scan_id: str
    portfolio_date: str
    revision: int
    created: bool


@dataclass(frozen=True)
class AuditedBatchPublisher:
    """Typed application adapter for the atomic audited batch publisher."""

    repository: BatchRepository
    run_key: str
    public_path: str | Path
    clock: Callable[[], datetime] = _utc_now

    def publish(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        dry_run: bool,
        write_public: bool = True,
    ) -> PublicationResult:
        projected = _project_persisted_rows(rows)
        return publish_batch(
            self.repository,
            projected,
            self.run_key,
            self.public_path,
            dry_run=dry_run,
            write_public=write_public,
            clock=self.clock,
        )

    def resume(
        self,
        *,
        dry_run: bool,
        write_public: bool = True,
    ) -> PublicationResult | None:
        """Restore the active persisted batch without accepting new pick rows."""
        if type(dry_run) is not bool:
            raise ValueError("dry_run must be a boolean")
        if type(write_public) is not bool:
            raise ValueError("write_public must be a boolean")
        if not isinstance(self.run_key, str) or not self.run_key.strip():
            raise ValueError("run_key must not be empty")
        if dry_run:
            return None

        response = self.repository.resume(self.run_key)
        if response is None:
            return None
        normalized = _normalized_resume_response(
            response,
            reference_at=self.clock(),
        )
        if normalized is None:
            return None
        result = _publication_result(normalized)
        if write_public:
            _write_public_payload(
                self.public_path,
                _safe_public_payload(result.picks),
            )
        return result


@dataclass(frozen=True)
class DailyPortfolioPublisher:
    """Stage and release one revisioned Mexico-day portfolio."""

    repository: BatchRepository
    run_key: str
    public_path: str | Path
    clock: Callable[[], datetime] = _utc_now

    def stage(
        self,
        rows: Sequence[Mapping[str, object]],
        *,
        portfolio_date: str,
    ) -> DailyStageResult:
        projected = _project_daily_stage_rows(rows)
        if not projected or len(projected) > 6:
            raise ValueError("daily picks must contain between one and six rows")
        normalized_date = _portfolio_date(portfolio_date)
        response = self.repository.stage_daily(
            self.run_key,
            normalized_date,
            source_hash_for(projected),
            projected,
        )
        normalized = _normalized_daily_stage_response(response)
        if normalized["portfolio_date"] != normalized_date:
            raise RuntimeError(
                "stage_daily_pick_portfolio returned an invalid response"
            )
        return DailyStageResult(**normalized)

    def release(
        self,
        *,
        portfolio_date: str,
        write_public: bool = True,
    ) -> PublicationResult | None:
        if type(write_public) is not bool:
            raise ValueError("write_public must be a boolean")
        normalized_date = _portfolio_date(portfolio_date)
        response = self.repository.release_daily(self.run_key, normalized_date)
        if response is None:
            return None
        normalized = _normalized_daily_publish_response(
            response,
            reference_at=self.clock(),
        )
        if normalized["portfolio_date"] != normalized_date:
            raise RuntimeError(
                "release_daily_pick_portfolio returned an invalid response"
            )
        result = _daily_publication_result(normalized)
        if write_public:
            _write_public_payload(
                self.public_path,
                _safe_public_payload(result.picks),
            )
        return result

    def resume(self, *, write_public: bool = True) -> PublicationResult | None:
        if type(write_public) is not bool:
            raise ValueError("write_public must be a boolean")
        response = self.repository.resume_daily(self.run_key)
        if response is None:
            return None
        normalized = _normalized_daily_publish_response(
            response,
            reference_at=self.clock(),
        )
        if normalized["created"] is not False:
            raise RuntimeError(
                "resume_daily_pick_release returned an invalid response"
            )
        result = _daily_publication_result(normalized)
        if write_public:
            _write_public_payload(
                self.public_path,
                _safe_public_payload(result.picks),
            )
        return result


class SupabaseBatchRepository:
    """Supabase RPC implementation of the batch repository boundary."""

    def __init__(
        self,
        client: _SupabaseClient,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._client = client
        self._clock = clock

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
        return _normalized_publish_response(
            response.data,
            reference_at=self._clock(),
        )

    def resume(self, run_key: str) -> PublishResponse | None:
        response = self._client.rpc(
            "resume_pick_batch",
            {"requested_run_key": run_key},
        ).execute()
        return _normalized_resume_response(
            response.data,
            reference_at=self._clock(),
        )

    def stage_daily(
        self,
        run_key: str,
        portfolio_date: str,
        source_hash: str,
        picks: Sequence[Mapping[str, object]],
    ) -> DailyStageResponse:
        response = self._client.rpc(
            "stage_daily_pick_portfolio",
            {
                "requested_run_key": run_key,
                "requested_portfolio_date": portfolio_date,
                "requested_source_hash": source_hash,
                "requested_picks": picks,
            },
        ).execute()
        return _normalized_daily_stage_response(response.data)

    def release_daily(
        self, run_key: str, portfolio_date: str
    ) -> DailyPublishResponse | None:
        response = self._client.rpc(
            "release_daily_pick_portfolio",
            {
                "requested_run_key": run_key,
                "requested_portfolio_date": portfolio_date,
            },
        ).execute()
        if response.data is None:
            return None
        return _normalized_daily_publish_response(
            response.data,
            reference_at=self._clock(),
        )

    def resume_daily(self, run_key: str) -> DailyPublishResponse | None:
        response = self._client.rpc(
            "resume_daily_pick_release",
            {"requested_run_key": run_key},
        ).execute()
        if response.data is None:
            return None
        normalized = _normalized_daily_publish_response(
            response.data,
            reference_at=self._clock(),
        )
        if normalized["created"] is not False:
            raise RuntimeError(
                "resume_daily_pick_release returned an invalid response"
            )
        return normalized

    def record_residential_events(
        self, events: Sequence[Mapping[str, object]]
    ) -> int:
        if (
            isinstance(events, (str, bytes))
            or not isinstance(events, Sequence)
            or not 1 <= len(events) <= 5000
            or any(not isinstance(event, Mapping) for event in events)
        ):
            raise ValueError("residential events must contain one to 5000 rows")
        payload = [dict(event) for event in events]
        response = self._client.rpc(
            "record_residential_event_watch",
            {"requested_events": payload},
        ).execute()
        data = getattr(response, "data", None)
        if type(data) is not int or data != len(payload):
            raise RuntimeError("residential event watch returned an invalid response")
        return data

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


def _project_daily_stage_rows(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    projected = _project_rows(rows, DAILY_STAGE_PICK_COLUMNS)
    for row in projected:
        event_key = row.get("physical_event_key")
        if (
            not isinstance(event_key, str)
            or _PHYSICAL_EVENT_KEY.fullmatch(event_key) is None
        ):
            raise ValueError("physical_event_key must be a canonical identity")
        if type(row.get("es_parlay")) is not bool:
            raise ValueError("es_parlay must be an explicit boolean")
    return projected


def _project_rows(
    rows: Sequence[Mapping[str, object]], columns: frozenset[str]
) -> tuple[dict[str, object], ...]:
    if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence):
        raise ValueError("picks must be a sequence")
    projected = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("each pick must be a mapping")
        projected.append({key: value for key, value in row.items() if key in columns})
    return tuple(projected)


def publish_batch(
    repository: BatchRepository,
    picks: Sequence[Mapping[str, object]],
    run_key: str,
    public_path: str | Path,
    *,
    dry_run: bool = False,
    write_public: bool = True,
    reference_at: datetime | None = None,
    clock: Callable[[], datetime] | None = None,
) -> PublicationResult:
    """Publish a database batch before atomically exposing its public selection."""
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean")
    if type(write_public) is not bool:
        raise ValueError("write_public must be a boolean")
    if not picks:
        raise ValueError("picks must not be empty")
    if not isinstance(run_key, str) or not run_key.strip():
        raise ValueError("run_key must not be empty")
    if reference_at is not None and clock is not None:
        raise ValueError("provide reference_at or clock, not both")
    if dry_run:
        return PublicationResult(None, None, False, {}, picks=(), dry_run=True)

    response = repository.publish(run_key, source_hash_for(picks), picks)
    result = _publication_result(
        _normalized_publish_response(
            response,
            reference_at=clock() if clock is not None else reference_at,
        )
    )
    if write_public:
        _write_public_payload(
            public_path,
            _safe_public_payload(result.picks),
        )
    return result


def _normalized_publish_response(
    data: object,
    *,
    reference_at: datetime | None = None,
    require_future: bool = True,
) -> PublishResponse:
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

    persisted_picks = _validated_persisted_picks(
        response.get("picks"),
        reference_at=reference_at,
        require_future=require_future,
    )

    return {
        "run_id": run_id,
        "batch_id": batch_id,
        "created": created,
        "delivery_status": delivery_status,
        "picks": persisted_picks,
    }


def _normalized_resume_response(
    data: object,
    *,
    reference_at: datetime | None = None,
) -> PublishResponse | None:
    if data is None:
        return None
    try:
        response = _normalized_publish_response(data, reference_at=reference_at)
    except RuntimeError:
        raise RuntimeError("resume_pick_batch returned an invalid response") from None
    if response["created"] is not False:
        raise RuntimeError("resume_pick_batch returned an invalid response")
    return response


def _normalized_daily_stage_response(data: object) -> DailyStageResponse:
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    response = _string_keyed_dict(data)
    if response is None:
        raise RuntimeError(
            "stage_daily_pick_portfolio returned an invalid response"
        )
    scan_id = response.get("scan_id")
    portfolio_date = response.get("portfolio_date")
    revision = response.get("revision")
    created = response.get("created")
    try:
        normalized_date = _portfolio_date(portfolio_date)
    except (TypeError, ValueError):
        normalized_date = ""
    if (
        not isinstance(scan_id, str)
        or not scan_id.strip()
        or normalized_date != portfolio_date
        or type(revision) is not int
        or revision <= 0
        or type(created) is not bool
    ):
        raise RuntimeError(
            "stage_daily_pick_portfolio returned an invalid response"
        )
    return {
        "scan_id": scan_id,
        "portfolio_date": normalized_date,
        "revision": revision,
        "created": created,
    }


def _normalized_daily_publish_response(
    data: object,
    *,
    reference_at: datetime | None = None,
) -> DailyPublishResponse:
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    raw = _string_keyed_dict(data)
    if raw is None:
        raise RuntimeError(
            "release_daily_pick_portfolio returned an invalid response"
        )
    base = _normalized_publish_response(
        raw,
        reference_at=reference_at,
        require_future=False,
    )
    try:
        portfolio_date = _portfolio_date(raw.get("portfolio_date"))
    except (TypeError, ValueError):
        raise RuntimeError(
            "release_daily_pick_portfolio returned an invalid response"
        ) from None
    revision = raw.get("revision")
    feed_eligible = raw.get("feed_eligible")
    if type(revision) is not int or revision <= 0 or type(feed_eligible) is not bool:
        raise RuntimeError(
            "release_daily_pick_portfolio returned an invalid response"
        )
    delivery_picks = _validated_persisted_picks(
        raw.get("delivery_picks"),
        reference_at=reference_at,
        enforce_public_policy=False,
    )
    full_by_id = {row["id"]: dict(row) for row in base["picks"]}
    if any(
        row["id"] not in full_by_id or dict(row) != full_by_id[row["id"]]
        for row in delivery_picks
    ):
        raise RuntimeError(
            "release_daily_pick_portfolio returned invalid delivery picks"
        )
    return {
        **base,
        "portfolio_date": portfolio_date,
        "revision": revision,
        "feed_eligible": feed_eligible,
        "delivery_picks": delivery_picks,
    }


def _validated_persisted_picks(
    value: object,
    *,
    reference_at: datetime | None = None,
    enforce_public_policy: bool = True,
    require_future: bool = True,
) -> tuple[PersistedPick, ...]:
    reference = _utc_reference(reference_at)
    if isinstance(value, tuple) and value and all(
        isinstance(row, PersistedPick) for row in value
    ):
        value = [dict(row) for row in value]
    if not isinstance(value, list) or not value:
        raise RuntimeError("publish_pick_batch returned invalid persisted picks")
    if len(value) > 6:
        raise RuntimeError("publish_pick_batch returned invalid public policy")

    normalized: list[PersistedPick] = []
    public_count = 0
    public_events: set[tuple[str, str]] = set()
    for raw_row in value:
        row = _string_keyed_dict(raw_row)
        if row is None or set(row) != RETURNED_PICK_COLUMNS:
            raise RuntimeError("publish_pick_batch returned invalid persisted picks")
        if not all(
            item is None or isinstance(item, (str, int, float, bool))
            for item in row.values()
        ):
            raise RuntimeError("publish_pick_batch returned invalid persisted picks")

        pick_id = row["id"]
        if type(pick_id) is not int or pick_id <= 0:
            raise RuntimeError("publish_pick_batch returned invalid persisted pick id")
        for field in (
            "source",
            "source_event_id",
            "source_market_key",
            "source_selection_key",
        ):
            field_value = row[field]
            if not isinstance(field_value, str) or not field_value.strip():
                raise RuntimeError("publish_pick_batch returned invalid source audit")

        observed = _utc_datetime(row["source_observed_at"])
        starts = _utc_datetime(row["source_starts_at"])
        if (
            observed is None
            or starts is None
            or observed > reference
            or starts <= observed
            or (require_future and starts <= reference)
        ):
            raise RuntimeError("publish_pick_batch returned invalid source audit")

        visibility = row["visibility"]
        if visibility not in ("public", "premium"):
            raise RuntimeError("publish_pick_batch returned invalid visibility")
        if visibility == "public":
            public_count += 1
            if row["es_parlay"] is not False or row["razonamiento"] is not None:
                raise RuntimeError("publish_pick_batch returned unsafe public pick")
            public_event = (
                str(row["source"]).strip().casefold(),
                str(row["source_event_id"]).strip(),
            )
            if public_event in public_events:
                raise RuntimeError(
                    "publish_pick_batch returned invalid public policy"
                )
            public_events.add(public_event)

        normalized.append(
            PersistedPick(tuple((key, row[key]) for key in sorted(row)))
        )

    if enforce_public_policy and public_count != expected_public_pick_count(len(normalized)):
        raise RuntimeError("publish_pick_batch returned invalid public policy")
    return tuple(normalized)


def revalidate_persisted_picks(
    picks: Sequence[Mapping[str, object]],
    *,
    reference_at: datetime | None = None,
) -> tuple[PersistedPick, ...]:
    """Revalidate exact persisted rows against one stable UTC reference."""
    return _validated_persisted_picks(
        [dict(row) for row in picks],
        reference_at=reference_at,
    )


def revalidate_delivery_picks(
    picks: Sequence[Mapping[str, object]],
    *,
    reference_at: datetime | None = None,
) -> tuple[PersistedPick, ...]:
    """Validate a non-empty release delta without imposing full-batch visibility."""

    return _validated_persisted_picks(
        [dict(row) for row in picks],
        reference_at=reference_at,
        enforce_public_policy=False,
    )


def revalidate_daily_portfolio(
    picks: Sequence[Mapping[str, object]],
    *,
    reference_at: datetime | None = None,
) -> tuple[PersistedPick, ...]:
    """Validate the full immutable daily portfolio, including started rows."""

    return _validated_persisted_picks(
        [dict(row) for row in picks],
        reference_at=reference_at,
        require_future=False,
    )


def _utc_reference(value: datetime | None) -> datetime:
    reference = datetime.now(timezone.utc) if value is None else value
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("reference_at must be timezone-aware")
    return reference.astimezone(timezone.utc)


def _portfolio_date(value: object) -> str:
    if not isinstance(value, str) or len(value) != 10:
        raise TypeError("portfolio_date must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("portfolio_date must be an ISO date") from None
    normalized = parsed.isoformat()
    if normalized != value:
        raise ValueError("portfolio_date must be an ISO date")
    return normalized


def _utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or _UTC_SOURCE_TIMESTAMP.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _safe_public_payload(
    picks: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    payload = public_payload([dict(row) for row in picks])
    for row in payload:
        row.pop("razonamiento", None)
    return payload


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
        delivery_status=dict(response["delivery_status"]),
        picks=response["picks"],
        delivery_picks=response["picks"],
    )


def _daily_publication_result(response: DailyPublishResponse) -> PublicationResult:
    return PublicationResult(
        run_id=response["run_id"],
        batch_id=response["batch_id"],
        created=response["created"],
        delivery_status=dict(response["delivery_status"]),
        picks=response["picks"],
        delivery_picks=response["delivery_picks"],
        portfolio_date=response["portfolio_date"],
        revision=response["revision"],
        feed_eligible=response["feed_eligible"],
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

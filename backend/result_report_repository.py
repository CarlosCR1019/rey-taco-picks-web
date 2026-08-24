"""Service-role-only Supabase boundary for idempotent result reports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import re
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from supabase import create_client


DIGEST = re.compile(r"^[0-9a-f]{64}$")
SAFE_RECEIPT = re.compile(r"^[A-Za-z0-9_:-]{1,256}$")
SAFE_ERROR = re.compile(r"^[a-z_]{1,64}$")
DESTINATIONS = frozenset({"admin", "vip", "free", "facebook", "instagram"})
REPORT_KINDS = frozenset({"evening", "final"})


class _Response(Protocol):
    data: object


class _Rpc(Protocol):
    def execute(self) -> _Response: ...


class _Client(Protocol):
    def rpc(self, name: str, arguments: dict[str, object]) -> _Rpc: ...


@dataclass(frozen=True, slots=True)
class Claim:
    state: Literal["claimed", "complete", "ambiguous"]
    attempt_id: str | None


class SupabaseResultReportRepository:
    def __init__(
        self,
        *,
        url: str,
        service_role_key: str,
        client_factory: Callable[[str, str], object] | None = None,
    ) -> None:
        if not isinstance(url, str) or not url.startswith("https://") or not url.strip():
            raise ValueError("Supabase result report URL is required")
        if not isinstance(service_role_key, str) or not service_role_key.strip():
            raise ValueError("Supabase result report service key is required")
        if client_factory is not None and not callable(client_factory):
            raise ValueError("client_factory must be callable")
        factory = client_factory or create_client
        try:
            self._client = cast(_Client, factory(url, service_role_key))
        except Exception:
            raise RuntimeError("could not create result report repository") from None

    def batches(self) -> tuple[tuple[dict[str, object], ...], ...]:
        try:
            raw = self._client.rpc("get_result_report_batches", {}).execute().data
        except Exception:
            raise RuntimeError("result report batches failed") from None
        if not isinstance(raw, list):
            raise RuntimeError("result report batches returned invalid data")
        batches: list[tuple[dict[str, object], ...]] = []
        for value in raw:
            if not isinstance(value, dict) or set(value) != {"picks"}:
                raise RuntimeError("result report batch returned invalid keys")
            picks = value["picks"]
            if not isinstance(picks, list) or len(picks) != 6:
                raise RuntimeError("result report batch requires six picks")
            if not all(isinstance(row, dict) for row in picks):
                raise RuntimeError("result report pick returned invalid data")
            batches.append(tuple(dict(row) for row in picks))
        return tuple(batches)

    def claim(
        self,
        *,
        batch_id: str,
        portfolio_date: str,
        report_kind: str,
        destination: str,
        report_digest: str,
    ) -> Claim:
        _canonical_uuid(batch_id, field="batch_id")
        _canonical_date(portfolio_date)
        if report_kind not in REPORT_KINDS:
            raise ValueError("invalid report kind")
        if destination not in DESTINATIONS:
            raise ValueError("invalid report destination")
        if not isinstance(report_digest, str) or DIGEST.fullmatch(report_digest) is None:
            raise ValueError("invalid report digest")
        attempt_id = str(uuid4())
        arguments = {
            "requested_batch_id": batch_id,
            "requested_portfolio_date": portfolio_date,
            "requested_report_kind": report_kind,
            "requested_destination": destination,
            "requested_report_digest": report_digest,
            "requested_attempt_id": attempt_id,
        }
        try:
            raw = self._client.rpc(
                "claim_result_report_delivery",
                arguments,
            ).execute().data
        except Exception:
            raise RuntimeError("result report claim failed") from None
        value = _one(raw)
        if set(value) != {"state", "attempt_id"}:
            raise RuntimeError("result report claim returned invalid keys")
        state = value["state"]
        returned_attempt = value["attempt_id"]
        if state == "claimed":
            if returned_attempt != attempt_id:
                raise RuntimeError("result report claim returned wrong attempt")
            return Claim("claimed", attempt_id)
        if state not in {"complete", "ambiguous"} or returned_attempt is not None:
            raise RuntimeError("result report claim returned invalid state")
        return Claim(state, None)

    def complete(
        self,
        *,
        batch_id: str,
        report_kind: str,
        destination: str,
        report_digest: str,
        attempt_id: str,
        success: bool,
        error: str = "",
        receipt: str = "",
    ) -> None:
        _canonical_uuid(batch_id, field="batch_id")
        _canonical_uuid(attempt_id, field="attempt_id")
        if report_kind not in REPORT_KINDS:
            raise ValueError("invalid report kind")
        if destination not in DESTINATIONS:
            raise ValueError("invalid report destination")
        if not isinstance(report_digest, str) or DIGEST.fullmatch(report_digest) is None:
            raise ValueError("invalid report digest")
        if type(success) is not bool:
            raise ValueError("success must be boolean")
        safe_error, safe_receipt = _completion_strings(
            success=success,
            error=error,
            receipt=receipt,
        )
        arguments = {
            "requested_batch_id": batch_id,
            "requested_report_kind": report_kind,
            "requested_destination": destination,
            "requested_report_digest": report_digest,
            "requested_attempt_id": attempt_id,
            "requested_success": success,
            "requested_error": safe_error,
            "requested_receipt": safe_receipt,
        }
        try:
            raw = self._client.rpc(
                "complete_result_report_delivery",
                arguments,
            ).execute().data
        except Exception:
            raise RuntimeError("result report completion failed") from None
        if _one(raw) != {"completed": True}:
            raise RuntimeError("result report completion was not persisted")


def _one(value: object) -> dict[str, object]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict):
        raise RuntimeError("result report RPC returned invalid data")
    return dict(value)


def _canonical_uuid(value: str, *, field: str) -> None:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"{field} must be a canonical UUID") from None


def _canonical_date(value: str) -> None:
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("portfolio_date must be an ISO date") from None


def _completion_strings(*, success: bool, error: str, receipt: str) -> tuple[str, str]:
    if not isinstance(error, str) or not isinstance(receipt, str):
        raise ValueError("result report completion strings must be text")
    if success:
        if error or SAFE_RECEIPT.fullmatch(receipt) is None:
            raise ValueError("successful report completion requires a safe receipt")
        return "", receipt
    if receipt or SAFE_ERROR.fullmatch(error) is None:
        raise ValueError("failed report completion requires a safe error")
    return error, ""

"""Fail-closed Supabase ledger boundary for vertical media delivery."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
from typing import Literal, Protocol, cast
from uuid import UUID, uuid4

from supabase import create_client

from backend.social_repository import (
    _validate_service_role_key,
    _validated_supabase_url,
)
from backend.vertical_content import ReelPackage, VerticalCard


_CONTENT_KINDS = frozenset(
    {
        "public_pick_story",
        "vip_teaser_story",
        "final_results_story",
        "verified_result_story",
        "ticket_evidence_story",
        "reel_cta_story",
        "daily_results_reel",
    }
)
_DESTINATIONS = frozenset({"instagram_story", "instagram_reel", "facebook_reel"})
_FAILURES = frozenset(
    {"not_configured", "token_invalid", "delivery_failed", "media_invalid"}
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SAFE_RECEIPT = re.compile(r"^[A-Za-z0-9_:-]{1,256}$")


class _SupabaseResponse(Protocol):
    data: object


class _SupabaseRpc(Protocol):
    def execute(self) -> _SupabaseResponse: ...


class _SupabaseClient(Protocol):
    def rpc(
        self,
        function_name: str,
        arguments: dict[str, object],
    ) -> _SupabaseRpc: ...


@dataclass(frozen=True, slots=True)
class VerticalClaim:
    state: Literal["claimed", "complete", "ambiguous"]
    attempt_id: str | None


class SupabaseVerticalRepository:
    """Service-role adapter for atomic vertical delivery claims."""

    BUCKET = "social-vertical"

    def __init__(
        self,
        *,
        url: str,
        service_role_key: str,
        client_factory: Callable[[str, str], object] | None = None,
    ) -> None:
        self._url = _validated_supabase_url(url)
        _validate_service_role_key(service_role_key)
        if client_factory is not None and not callable(client_factory):
            raise ValueError("client_factory must be callable")
        factory = client_factory or create_client
        try:
            self._client = cast(_SupabaseClient, factory(self._url, service_role_key))
        except Exception:
            raise RuntimeError("could not create vertical repository client") from None

    def claim(
        self,
        *,
        batch_id: str,
        portfolio_date: str,
        content_kind: str,
        destination: str,
        digest: str,
        template_version: int,
    ) -> VerticalClaim:
        normalized_batch = _canonical_uuid(batch_id, field="batch_id")
        normalized_date = _canonical_date(portfolio_date)
        normalized_kind = _content_kind(content_kind)
        normalized_destination = _destination(destination)
        normalized_digest = _digest(digest)
        normalized_version = _template_version(template_version)
        attempt_id = str(uuid4())
        lease = datetime.now(timezone.utc) + timedelta(minutes=8)
        arguments: dict[str, object] = {
            "requested_batch_id": normalized_batch,
            "requested_portfolio_date": normalized_date,
            "requested_content_kind": normalized_kind,
            "requested_destination": normalized_destination,
            "requested_content_digest": normalized_digest,
            "requested_template_version": normalized_version,
            "requested_attempt_id": attempt_id,
            "requested_lease_expires_at": lease.isoformat(),
        }
        try:
            raw = (
                self._client.rpc("claim_vertical_media_delivery", arguments)
                .execute()
                .data
            )
        except Exception:
            raise RuntimeError("vertical claim failed") from None
        value = _one_exact(raw, {"state", "attempt_id"})
        if value == {"state": "claimed", "attempt_id": attempt_id}:
            return VerticalClaim("claimed", attempt_id)
        state = value["state"]
        if state in {"complete", "ambiguous"} and value["attempt_id"] is None:
            return VerticalClaim(cast(Literal["complete", "ambiguous"], state), None)
        raise RuntimeError("vertical claim returned invalid data")

    def complete(
        self,
        *,
        package: VerticalCard | ReelPackage,
        destination: str,
        attempt_id: str,
        success: bool,
        receipt: str = "",
        error: str = "",
    ) -> None:
        arguments = _validated_completion(
            package, destination, attempt_id, success, receipt, error
        )
        try:
            raw = (
                self._client.rpc("complete_vertical_media_delivery", arguments)
                .execute()
                .data
            )
        except Exception:
            raise RuntimeError("vertical completion failed") from None
        value = _one_exact(raw, {"completed"})
        if value.get("completed") is not True:
            raise RuntimeError("vertical completion was not persisted")


def _canonical_uuid(value: object, *, field: str) -> str:
    if not isinstance(value, str) or value != value.strip() or value != value.lower():
        raise ValueError(f"{field} must be a canonical UUID")
    try:
        normalized = str(UUID(value))
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"{field} must be a canonical UUID") from None
    if normalized != value:
        raise ValueError(f"{field} must be a canonical UUID")
    return normalized


def _canonical_date(value: object) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise ValueError("portfolio_date must be a canonical date")
    try:
        normalized = date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError("portfolio_date must be a canonical date") from None
    if normalized != value:
        raise ValueError("portfolio_date must be a canonical date")
    return normalized


def _content_kind(value: object) -> str:
    if not isinstance(value, str) or value not in _CONTENT_KINDS:
        raise ValueError("vertical content kind is invalid")
    return value


def _destination(value: object) -> str:
    if not isinstance(value, str) or value not in _DESTINATIONS:
        raise ValueError("vertical destination is invalid")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("vertical digest is invalid")
    return value


def _template_version(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("vertical template version is invalid")
    return value


def _validated_package(
    package: VerticalCard | ReelPackage,
) -> tuple[str, str, str, str, int]:
    if not isinstance(package, (VerticalCard, ReelPackage)):
        raise ValueError("vertical package is invalid")
    return (
        _canonical_uuid(package.batch_id, field="batch_id"),
        _canonical_date(package.portfolio_date),
        _content_kind(package.kind),
        _digest(package.digest),
        _template_version(package.template_version),
    )


def _validated_completion(
    package: VerticalCard | ReelPackage,
    destination: str,
    attempt_id: str,
    success: bool,
    receipt: str,
    error: str,
) -> dict[str, object]:
    batch_id, _, kind, digest, template_version = _validated_package(package)
    normalized_destination = _destination(destination)
    normalized_attempt = _canonical_uuid(attempt_id, field="attempt_id")
    if type(success) is not bool:
        raise ValueError("vertical completion identity is invalid")
    if not isinstance(receipt, str) or not isinstance(error, str):
        raise ValueError("vertical completion outcome is invalid")
    if success:
        if error or _SAFE_RECEIPT.fullmatch(receipt) is None:
            raise ValueError("vertical success requires one safe receipt")
    elif receipt or error not in _FAILURES:
        raise ValueError("vertical failure requires one allowed error")
    return {
        "requested_batch_id": batch_id,
        "requested_content_kind": kind,
        "requested_destination": normalized_destination,
        "requested_content_digest": digest,
        "requested_template_version": template_version,
        "requested_attempt_id": normalized_attempt,
        "requested_success": success,
        "requested_receipt": receipt if success else "",
        "requested_error": "" if success else error,
    }


def _one_exact(value: object, keys: set[str]) -> dict[str, object]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict) or set(value) != keys:
        raise RuntimeError("vertical RPC returned invalid data")
    return dict(value)

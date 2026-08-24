"""Atomic, fail-closed ownership for residential collection windows."""

from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Callable, Mapping, Sequence
from datetime import date
import os
import re
from typing import Any


_SAFE_KEY = re.compile(r"^[A-Za-z0-9*|: _-]{1,200}$")
_SAFE_OWNER = re.compile(r"^[A-Za-z0-9|:._ -]{1,200}$")


class LeaseConfigurationError(RuntimeError):
    """Raised when the lease cannot be configured without guessing."""


class _BoundedArgumentParser(ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid arguments")


def _required_text(value: object, field: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\n" in value or "\r" in value:
        raise ValueError(f"{field} is invalid")
    return normalized


def collection_window_key(
    *,
    portfolio_date: object,
    event_name: object,
    schedule: object,
    run_id: object,
) -> str:
    normalized_date = _required_text(portfolio_date, "portfolio_date", maximum=10)
    try:
        if date.fromisoformat(normalized_date).isoformat() != normalized_date:
            raise ValueError
    except ValueError:
        raise ValueError("portfolio_date must be an ISO date") from None
    normalized_event = _required_text(event_name, "event_name", maximum=30)
    if normalized_event == "schedule":
        token = _required_text(schedule, "schedule", maximum=40)
        key = f"{normalized_date}|schedule|{token}"
    elif normalized_event == "workflow_dispatch":
        token = _required_text(run_id, "run_id", maximum=40)
        key = f"{normalized_date}|manual|{token}"
    else:
        raise ValueError("unsupported event_name")
    if _SAFE_KEY.fullmatch(key) is None:
        raise ValueError("collection window key is invalid")
    return key


class CollectionLeaseClient:
    def __init__(self, client: Any) -> None:
        if client is None or not callable(getattr(client, "rpc", None)):
            raise TypeError("client must provide rpc")
        self._client = client

    def claim(
        self,
        window_key: object,
        owner_run_key: object,
        *,
        lease_minutes: int = 30,
    ) -> bool:
        normalized_window = _required_text(window_key, "window_key")
        normalized_owner = _required_text(owner_run_key, "owner_run_key")
        if _SAFE_KEY.fullmatch(normalized_window) is None:
            raise ValueError("window_key is invalid")
        if _SAFE_OWNER.fullmatch(normalized_owner) is None:
            raise ValueError("owner_run_key is invalid")
        if type(lease_minutes) is not int or not 5 <= lease_minutes <= 60:
            raise ValueError("lease_minutes must be between 5 and 60")
        response = self._client.rpc(
            "claim_residential_collection_lease",
            {
                "requested_window_key": normalized_window,
                "requested_owner_run_key": normalized_owner,
                "requested_lease_minutes": lease_minutes,
            },
        ).execute()
        data = getattr(response, "data", None)
        if type(data) is not bool:
            raise RuntimeError("collection lease returned an invalid response")
        return data

    def release(self, window_key: object, owner_run_key: object) -> bool:
        normalized_window = _required_text(window_key, "window_key")
        normalized_owner = _required_text(owner_run_key, "owner_run_key")
        if _SAFE_KEY.fullmatch(normalized_window) is None:
            raise ValueError("window_key is invalid")
        if _SAFE_OWNER.fullmatch(normalized_owner) is None:
            raise ValueError("owner_run_key is invalid")
        response = self._client.rpc(
            "release_residential_collection_lease",
            {
                "requested_window_key": normalized_window,
                "requested_owner_run_key": normalized_owner,
            },
        ).execute()
        data = getattr(response, "data", None)
        if type(data) is not bool:
            raise RuntimeError("collection lease returned an invalid response")
        return data


def _settings(values: Mapping[str, str | None] | None) -> tuple[str, str, str]:
    source: Mapping[str, str | None] = os.environ if values is None else values
    configured = []
    for field in (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "COLLECTION_LEASE_OWNER_KEY",
    ):
        value = source.get(field)
        if not isinstance(value, str) or not value.strip():
            raise LeaseConfigurationError("collection lease configuration is incomplete")
        configured.append(value.strip())
    return tuple(configured)  # type: ignore[return-value]


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    values: Mapping[str, str | None] | None = None,
    client_factory: Callable[[str, str], Any] | None = None,
) -> int:
    parser = _BoundedArgumentParser(add_help=False)
    parser.add_argument("--window-key", required=True)
    parser.add_argument("--release", action="store_true")
    try:
        arguments = parser.parse_args(argv)
        supabase_url, service_role_key, owner_run_key = _settings(values)
        if client_factory is None:
            from supabase import create_client

            client_factory = create_client
        lease = CollectionLeaseClient(client_factory(supabase_url, service_role_key))
        if arguments.release:
            released = lease.release(arguments.window_key, owner_run_key)
            print(
                "collection_lease=released"
                if released
                else "collection_lease=not_owner"
            )
            return 0 if released else 3
        acquired = lease.claim(arguments.window_key, owner_run_key)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        print("collection_lease=invalid")
        return 2
    if acquired:
        print("collection_lease=acquired")
        return 0
    print("collection_lease=busy")
    return 3


if __name__ == "__main__":
    raise SystemExit(run_cli())

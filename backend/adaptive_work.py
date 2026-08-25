"""Lightweight Supabase decision boundary for residential adaptive ticks."""

from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class _BoundedArgumentParser(ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid arguments")


def _required_text(value: object, field: str, *, maximum: int = 2048) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or "\r" in value or "\n" in value:
        raise ValueError(f"{field} is invalid")
    return normalized


def _iso_date(value: object) -> str:
    normalized = _required_text(value, "portfolio_date", maximum=10)
    try:
        parsed = date.fromisoformat(normalized).isoformat()
    except ValueError:
        raise ValueError("portfolio_date must be an ISO date") from None
    if parsed != normalized:
        raise ValueError("portfolio_date must be an ISO date")
    return normalized


@dataclass(frozen=True, slots=True)
class AdaptiveWorkStatus:
    needs_collection: bool
    lineup_due: bool
    quote_due: bool
    recoverable_due: bool

    def __post_init__(self) -> None:
        if any(
            type(value) is not bool
            for value in (
                self.needs_collection,
                self.lineup_due,
                self.quote_due,
                self.recoverable_due,
            )
        ):
            raise TypeError("adaptive work flags must be boolean")
        if self.needs_collection != (
            self.lineup_due or self.quote_due or self.recoverable_due
        ):
            raise ValueError("adaptive work summary is inconsistent")


class AdaptiveWorkClient:
    def __init__(
        self,
        supabase_url: object,
        service_role_key: object,
        *,
        opener: Callable[..., object] | None = None,
        timeout: float = 10.0,
    ) -> None:
        base_url = _required_text(supabase_url, "supabase_url").rstrip("/")
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("supabase_url must be an HTTPS origin")
        self._url = (
            f"{base_url}/rest/v1/rpc/residential_adaptive_work_status"
        )
        self._service_role_key = _required_text(
            service_role_key, "service_role_key", maximum=8192
        )
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be numeric")
        if not 1 <= float(timeout) <= 30:
            raise ValueError("timeout must be between 1 and 30 seconds")
        self._timeout = float(timeout)
        self._opener = opener or urlopen

    def status(self, portfolio_date: object) -> AdaptiveWorkStatus:
        normalized_date = _iso_date(portfolio_date)
        request = Request(
            self._url,
            data=json.dumps(
                {"requested_portfolio_date": normalized_date},
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "apikey": self._service_role_key,
                "Authorization": f"Bearer {self._service_role_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self._opener(request, timeout=self._timeout) as response:
            status = getattr(response, "status", None)
            if not isinstance(status, int) or not 200 <= status < 300:
                raise RuntimeError("adaptive work provider returned an invalid response")
            raw = response.read(4097)
        if not isinstance(raw, bytes) or len(raw) > 4096:
            raise RuntimeError("adaptive work provider returned an invalid response")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RuntimeError("adaptive work provider returned an invalid response") from None
        if not isinstance(payload, Mapping):
            raise RuntimeError("adaptive work provider returned an invalid response")
        fields = (
            "needs_collection",
            "lineup_due",
            "quote_due",
            "recoverable_due",
        )
        if set(payload) != set(fields) or any(type(payload.get(field)) is not bool for field in fields):
            raise RuntimeError("adaptive work provider returned an invalid response")
        try:
            return AdaptiveWorkStatus(**{field: payload[field] for field in fields})
        except (TypeError, ValueError):
            raise RuntimeError("adaptive work provider returned an invalid response") from None


def _settings(values: Mapping[str, str | None] | None) -> tuple[str, str]:
    source: Mapping[str, str | None] = os.environ if values is None else values
    return (
        _required_text(source.get("SUPABASE_URL"), "SUPABASE_URL"),
        _required_text(
            source.get("SUPABASE_SERVICE_ROLE_KEY"),
            "SUPABASE_SERVICE_ROLE_KEY",
            maximum=8192,
        ),
    )


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    values: Mapping[str, str | None] | None = None,
    client_factory: Callable[[str, str], object] | None = None,
) -> int:
    parser = _BoundedArgumentParser(add_help=False)
    parser.add_argument("--scan-mode", required=True)
    parser.add_argument("--portfolio-date", required=True)
    try:
        arguments = parser.parse_args(argv)
        normalized_date = _iso_date(arguments.portfolio_date)
        if arguments.scan_mode == "full":
            print("adaptive_work=needed")
            return 0
        if arguments.scan_mode != "adaptive":
            raise ValueError("unsupported scan mode")
        supabase_url, service_role_key = _settings(values)
        factory = client_factory or AdaptiveWorkClient
        status = factory(supabase_url, service_role_key).status(normalized_date)
        if type(status.needs_collection) is not bool:
            raise RuntimeError("adaptive work provider returned an invalid response")
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        print("adaptive_work=invalid")
        return 2
    if status.needs_collection:
        print("adaptive_work=needed")
        return 0
    print("adaptive_work=idle")
    return 3


if __name__ == "__main__":
    raise SystemExit(run_cli())

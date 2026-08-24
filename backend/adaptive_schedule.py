"""Fail-closed scheduling decisions for self-hosted residential collectors."""

from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone


SUPPORTED_EVENTS = frozenset({"schedule", "workflow_dispatch"})


class _BoundedArgumentParser(ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid arguments")


def _aware_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _github_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("created_at must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("created_at must not be blank")
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError("created_at must be ISO-8601") from None
    return _aware_datetime(parsed, "created_at")


def scheduled_run_is_eligible(
    created_at: object,
    *,
    now: datetime,
    event_name: str,
    max_age_minutes: int = 20,
) -> bool:
    """Return whether one explicit GitHub run may start residential work."""

    reference = _aware_datetime(now, "now").astimezone(timezone.utc)
    if not isinstance(event_name, str) or event_name not in SUPPORTED_EVENTS:
        raise ValueError("unsupported GitHub event")
    if (
        type(max_age_minutes) is not int
        or not 1 <= max_age_minutes <= 60
    ):
        raise ValueError("max_age_minutes must be between 1 and 60")
    if event_name == "workflow_dispatch":
        return True

    created = _github_datetime(created_at).astimezone(timezone.utc)
    age = reference - created
    return timedelta(0) <= age <= timedelta(minutes=max_age_minutes)


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> int:
    parser = _BoundedArgumentParser(add_help=False)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--created-at")
    try:
        args = parser.parse_args(argv)
    except (SystemExit, ValueError):
        print("collection_window=invalid")
        return 2

    try:
        eligible = scheduled_run_is_eligible(
            args.created_at,
            now=(clock or (lambda: datetime.now(timezone.utc)))(),
            event_name=args.event_name,
        )
    except (TypeError, ValueError):
        print("collection_window=invalid")
        return 2

    if eligible:
        print("collection_window=eligible")
        return 0
    print("collection_window=stale")
    return 3


if __name__ == "__main__":
    raise SystemExit(run_cli())

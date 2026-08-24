"""Fail-closed scheduling decisions for self-hosted residential collectors."""

from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


SUPPORTED_EVENTS = frozenset({"schedule", "workflow_dispatch"})
SUPPORTED_SCHEDULES = frozenset({"7 * * * *", "37 * * * *", "0 16 * * *"})
MEXICO_CITY = ZoneInfo("America/Mexico_City")
FULL_SCAN_HOURS = frozenset({8, 12, 16, 20, 23})
RELEASE_HOURS = frozenset({16, 23})


@dataclass(frozen=True, slots=True)
class CollectionPlan:
    scan_mode: str
    release_eligible: bool

    def __post_init__(self) -> None:
        if self.scan_mode not in {"full", "adaptive", "cloud"}:
            raise ValueError("invalid scan mode")
        if type(self.release_eligible) is not bool:
            raise TypeError("release_eligible must be boolean")


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


def collection_plan(
    created_at: object,
    *,
    event_name: str,
    event_schedule: object,
) -> CollectionPlan:
    """Return the exact work class for one trusted GitHub trigger."""

    if event_name not in SUPPORTED_EVENTS:
        raise ValueError("unsupported GitHub event")
    if event_name == "workflow_dispatch":
        if event_schedule not in (None, ""):
            raise ValueError("manual dispatch cannot have a schedule")
        return CollectionPlan("full", True)
    if not isinstance(event_schedule, str) or event_schedule not in SUPPORTED_SCHEDULES:
        raise ValueError("unsupported GitHub schedule")
    created = _github_datetime(created_at).astimezone(MEXICO_CITY)
    if event_schedule == "0 16 * * *":
        return CollectionPlan("cloud", True)
    if event_schedule == "7 * * * *" and created.hour in FULL_SCAN_HOURS:
        return CollectionPlan(
            "full",
            created.hour in RELEASE_HOURS,
        )
    return CollectionPlan("adaptive", False)


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
) -> int:
    parser = _BoundedArgumentParser(add_help=False)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--created-at")
    parser.add_argument("--schedule")
    parser.add_argument("--plan", action="store_true")
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
        plan = (
            collection_plan(
                args.created_at,
                event_name=args.event_name,
                event_schedule=args.schedule,
            )
            if eligible and args.plan
            else None
        )
    except (TypeError, ValueError):
        print("collection_window=invalid")
        return 2

    if eligible:
        print("collection_window=eligible")
        if plan is not None:
            print(f"scan_mode={plan.scan_mode}")
            print(
                "release_eligible="
                f"{'true' if plan.release_eligible else 'false'}"
            )
        return 0
    print("collection_window=stale")
    return 3


if __name__ == "__main__":
    raise SystemExit(run_cli())

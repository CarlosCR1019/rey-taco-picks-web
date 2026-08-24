from datetime import datetime, timedelta, timezone

import pytest

from backend.adaptive_schedule import (
    collection_plan,
    run_cli,
    scheduled_run_is_eligible,
)


NOW = datetime(2026, 8, 23, 18, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("created_at", "expected"),
    [
        ("2026-08-23T17:40:00Z", True),
        ("2026-08-23T17:39:59Z", False),
        ("2026-08-23T18:00:01Z", False),
        ("2026-08-23T11:40:00-06:00", True),
    ],
)
def test_scheduled_gate_uses_authoritative_utc_age(created_at, expected):
    assert scheduled_run_is_eligible(
        created_at,
        now=NOW,
        event_name="schedule",
    ) is expected


def test_manual_dispatch_bypasses_scheduled_age():
    assert scheduled_run_is_eligible(
        None,
        now=NOW,
        event_name="workflow_dispatch",
    ) is True


@pytest.mark.parametrize(
    "created_at",
    [
        "",
        "not-a-date",
        "2026-08-23T17:40:00",
        123,
    ],
)
def test_scheduled_gate_rejects_malformed_or_naive_timestamp(created_at):
    with pytest.raises((TypeError, ValueError)):
        scheduled_run_is_eligible(
            created_at,
            now=NOW,
            event_name="schedule",
        )


@pytest.mark.parametrize(
    ("now", "event_name", "max_age_minutes"),
    [
        (datetime(2026, 8, 23, 18, 0), "schedule", 20),
        (NOW, "push", 20),
        (NOW, "schedule", True),
        (NOW, "schedule", 0),
        (NOW, "schedule", 61),
    ],
)
def test_scheduled_gate_rejects_invalid_contract(
    now,
    event_name,
    max_age_minutes,
):
    with pytest.raises((TypeError, ValueError)):
        scheduled_run_is_eligible(
            "2026-08-23T17:40:00Z",
            now=now,
            event_name=event_name,
            max_age_minutes=max_age_minutes,
        )


@pytest.mark.parametrize(
    ("created_at", "expected_code", "expected_output"),
    [
        ("2026-08-23T17:40:00Z", 0, "collection_window=eligible"),
        ("2026-08-23T17:39:59Z", 3, "collection_window=stale"),
        ("bad", 2, "collection_window=invalid"),
    ],
)
def test_gate_cli_has_bounded_exit_codes(
    created_at,
    expected_code,
    expected_output,
    capsys,
):
    code = run_cli(
        ["--event-name", "schedule", "--created-at", created_at],
        clock=lambda: NOW,
    )

    assert code == expected_code
    assert capsys.readouterr().out.strip() == expected_output


def test_gate_cli_allows_manual_dispatch_without_created_at(capsys):
    code = run_cli(
        ["--event-name", "workflow_dispatch"],
        clock=lambda: NOW,
    )

    assert code == 0
    assert capsys.readouterr().out.strip() == "collection_window=eligible"


def test_gate_cli_missing_arguments_has_only_bounded_invalid_output(capsys):
    code = run_cli([], clock=lambda: NOW)

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.strip() == "collection_window=invalid"
    assert captured.err == ""


@pytest.mark.parametrize(
    ("created_at", "schedule", "mode", "release"),
    [
        ("2026-08-23T14:07:00Z", "7 * * * *", "full", False),
        ("2026-08-23T18:07:00Z", "7 * * * *", "full", False),
        ("2026-08-23T22:07:00Z", "7 * * * *", "full", True),
        ("2026-08-24T02:07:00Z", "7 * * * *", "full", False),
        ("2026-08-24T05:07:00Z", "7 * * * *", "full", True),
        ("2026-08-23T14:37:00Z", "37 * * * *", "adaptive", False),
        ("2026-08-23T15:07:00Z", "7 * * * *", "adaptive", False),
        ("2026-08-23T16:00:00Z", "0 16 * * *", "cloud", True),
    ],
)
def test_collection_plan_preserves_full_and_release_windows(
    created_at, schedule, mode, release
):
    plan = collection_plan(
        created_at,
        event_name="schedule",
        event_schedule=schedule,
    )

    assert plan.scan_mode == mode
    assert plan.release_eligible is release


def test_manual_plan_is_full_and_release_eligible():
    plan = collection_plan(
        None,
        event_name="workflow_dispatch",
        event_schedule=None,
    )
    assert plan.scan_mode == "full"
    assert plan.release_eligible is True


@pytest.mark.parametrize("schedule", [None, "", "0 14 * * *", "7,37 * * * *"])
def test_scheduled_plan_rejects_unknown_cron_identity(schedule):
    with pytest.raises((TypeError, ValueError)):
        collection_plan(
            "2026-08-23T14:07:00Z",
            event_name="schedule",
            event_schedule=schedule,
        )


def test_plan_cli_emits_bounded_github_outputs(capsys):
    code = run_cli(
        [
            "--event-name", "schedule",
            "--created-at", "2026-08-23T22:07:00Z",
            "--schedule", "7 * * * *",
            "--plan",
        ],
        clock=lambda: datetime(2026, 8, 23, 22, 10, tzinfo=timezone.utc),
    )

    assert code == 0
    assert capsys.readouterr().out.splitlines() == [
        "collection_window=eligible",
        "scan_mode=full",
        "release_eligible=true",
    ]

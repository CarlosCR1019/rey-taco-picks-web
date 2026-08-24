from datetime import datetime, timedelta, timezone

import pytest

from backend.adaptive_schedule import run_cli, scheduled_run_is_eligible


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

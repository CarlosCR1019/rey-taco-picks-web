from datetime import datetime, timezone

import pytest

from backend.daily_portfolio import (
    audit_identity,
    merge_daily_portfolio,
    mexico_portfolio_date,
    physical_event_key,
    run_cli,
)


def pick(
    number: int,
    *,
    event: int | None = None,
    visibility: str | None = None,
    parlay: bool = False,
):
    row = {
        "source": "playdoit",
        "source_event_id": f"event-{event if event is not None else number}",
        "source_market_key": f"market-{number}",
        "source_selection_key": f"selection-{number}",
        "partido": f"Local {event if event is not None else number} vs Visitante {event if event is not None else number}",
        "pick": f"Pick {number}",
        "es_parlay": parlay,
    }
    if visibility is not None:
        row["visibility"] = visibility
    return row


def thaw(rows):
    return [dict(row) for row in rows]


def test_mexico_portfolio_date_uses_america_mexico_city_calendar():
    assert mexico_portfolio_date(
        datetime(2026, 8, 24, 4, 30, tzinfo=timezone.utc)
    ) == "2026-08-23"


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 8, 23),
        "2026-08-23",
        None,
    ],
)
def test_mexico_portfolio_date_rejects_non_aware_datetime(value):
    with pytest.raises((TypeError, ValueError)):
        mexico_portfolio_date(value)


def test_audit_identity_is_exact_and_rejects_incomplete_rows():
    assert audit_identity(pick(1)) == (
        "playdoit",
        "event-1",
        "market-1",
        "selection-1",
    )

    for field in (
        "source",
        "source_event_id",
        "source_market_key",
        "source_selection_key",
    ):
        row = pick(1)
        row[field] = ""
        with pytest.raises(ValueError, match=field):
            audit_identity(row)


def test_first_draft_keeps_rank_order_caps_six_and_assigns_two_free():
    result = thaw(merge_daily_portfolio([], [pick(i) for i in range(1, 9)]))

    assert [row["pick"] for row in result] == [f"Pick {i}" for i in range(1, 7)]
    assert [row["visibility"] for row in result] == [
        "public",
        "public",
        "premium",
        "premium",
        "premium",
        "premium",
    ]


def test_one_to_five_picks_have_exactly_one_free_pick():
    for count in range(1, 6):
        result = thaw(
            merge_daily_portfolio([], [pick(i) for i in range(1, count + 1)])
        )
        assert sum(row["visibility"] == "public" for row in result) == 1


def test_released_rows_are_immutable_and_only_new_slots_are_filled():
    released = [
        pick(1, visibility="public"),
        pick(2, visibility="premium"),
        pick(3, visibility="premium"),
    ]
    result = thaw(
        merge_daily_portfolio(
            released,
            [pick(20), pick(21), pick(22)],
        )
    )

    assert result[:3] == released
    assert [row["pick"] for row in result[3:]] == ["Pick 20", "Pick 21", "Pick 22"]
    assert result[3]["visibility"] == "public"
    assert sum(row["visibility"] == "public" for row in result) == 2


def test_new_scan_replaces_unreleased_draft_when_released_prefix_is_same():
    released = [pick(1, visibility="public")]

    first = thaw(merge_daily_portfolio(released, [pick(2), pick(3)]))
    second = thaw(merge_daily_portfolio(released, [pick(40), pick(41)]))

    assert first[0] == second[0] == released[0]
    assert [row["pick"] for row in first[1:]] == ["Pick 2", "Pick 3"]
    assert [row["pick"] for row in second[1:]] == ["Pick 40", "Pick 41"]


def test_duplicate_physical_matches_and_audit_rows_are_skipped():
    result = thaw(
        merge_daily_portfolio(
            [pick(1, visibility="public")],
            [
                pick(10, event=1),
                pick(20, event=2),
                pick(20, event=2),
                pick(30, event=3),
            ],
        )
    )

    assert [row["source_event_id"] for row in result] == [
        "event-1",
        "event-2",
        "event-3",
    ]


def test_same_match_from_different_sources_has_one_physical_identity():
    released = pick(1, visibility="public")
    candidate = {
        **pick(20),
        "source": "the-odds-api",
        "source_event_id": "different-provider-id",
        "partido": "Visitante 1 contra Lócal 1",
    }

    result = thaw(merge_daily_portfolio([released], [candidate, pick(2)]))

    assert [row["source_event_id"] for row in result] == ["event-1", "event-2"]
    assert physical_event_key(released) == physical_event_key(candidate)


@pytest.mark.parametrize("value", [None, "false", 0])
def test_daily_portfolio_requires_explicit_boolean_parlay_flag(value):
    candidate = pick(1)
    if value is None:
        candidate.pop("es_parlay")
    else:
        candidate["es_parlay"] = value

    with pytest.raises(ValueError, match="es_parlay"):
        merge_daily_portfolio([], [candidate])


def test_sixth_pick_is_not_forced_when_second_free_would_be_a_parlay():
    released = [
        pick(1, visibility="public"),
        pick(2, visibility="premium"),
        pick(3, visibility="premium"),
        pick(4, visibility="premium"),
        pick(5, visibility="premium"),
    ]

    result = thaw(merge_daily_portfolio(released, [pick(6, parlay=True)]))

    assert result == released


def test_parlays_may_be_premium_when_a_safe_public_pick_exists():
    result = thaw(
        merge_daily_portfolio(
            [],
            [pick(1, parlay=True), pick(2), pick(3, parlay=True)],
        )
    )

    assert [row["visibility"] for row in result] == [
        "premium",
        "public",
        "premium",
    ]


@pytest.mark.parametrize(
    "released",
    [
        [pick(1, visibility="premium")],
        [pick(1, visibility="public"), pick(2, visibility="public")],
        [pick(1, visibility="public", parlay=True)],
        [pick(1, visibility="public"), pick(2, event=1, visibility="premium")],
    ],
)
def test_invalid_released_portfolio_fails_closed(released):
    with pytest.raises(ValueError, match="released"):
        merge_daily_portfolio(released, [])


def test_returned_rows_are_defensive_immutable_copies():
    candidate = pick(1)
    result = merge_daily_portfolio([], [candidate])
    candidate["pick"] = "mutated"

    assert result[0]["pick"] == "Pick 1"
    with pytest.raises(TypeError):
        result[0]["pick"] = "mutation"  # type: ignore[index]


def test_cli_emits_stable_mexico_date_from_github_created_at(capsys):
    code = run_cli(["--created-at", "2026-08-24T05:02:00Z"])

    assert code == 0
    assert capsys.readouterr().out.strip() == "portfolio_date=2026-08-23"


@pytest.mark.parametrize("arguments", [[], ["--created-at", "bad-date"]])
def test_cli_rejects_missing_or_invalid_created_at_with_one_safe_line(
    arguments, capsys
):
    assert run_cli(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == "portfolio_date=invalid"
    assert captured.err == ""

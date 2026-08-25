import pytest

from tests.daily_visibility_sync_model import synchronize_daily_visibility


def _six_entries():
    return [
        {
            "pick_id": 100 + position,
            "position": position,
            "visibility": "public" if position in {1, 5} else "premium",
            "payload": {"razonamiento": f"trusted-rationale-{position}"},
        }
        for position in range(1, 7)
    ]


def _stale_persisted_picks():
    return [
        {
            "id": 100 + position,
            "position": position,
            "visibility": "public" if position in {1, 4, 5} else "premium",
            "razonamiento": None if position in {1, 4, 5} else f"premium-{position}",
        }
        for position in range(1, 7)
    ]


@pytest.mark.parametrize("created", [True, False], ids=["create", "replay"])
def test_six_pick_release_reconciles_stale_third_public_pick(created):
    result = synchronize_daily_visibility(
        _six_entries(),
        _stale_persisted_picks(),
        created=created,
        feed_eligible=True,
    )

    assert result["created"] is created
    assert result["feed_eligible"] is True
    assert len(result["picks"]) == 6
    assert [
        pick["position"]
        for pick in result["picks"]
        if pick["visibility"] == "public"
    ] == [1, 5]
    assert all(
        pick["razonamiento"] is None
        for pick in result["picks"]
        if pick["visibility"] == "public"
    )
    assert result["picks"][3]["visibility"] == "premium"
    assert result["picks"][3]["razonamiento"] == "trusted-rationale-4"


def test_replay_ignores_two_later_unreleased_drafts():
    released_entries = _six_entries()[:4]
    staged_drafts = [
        {**entry, "pick_id": None}
        for entry in _six_entries()[4:]
    ]

    result = synchronize_daily_visibility(
        [*released_entries, *staged_drafts],
        _stale_persisted_picks()[:4],
        created=False,
        feed_eligible=True,
    )

    assert result["created"] is False
    assert len(result["picks"]) == 4
    assert [pick["id"] for pick in result["picks"]] == [101, 102, 103, 104]
    assert result["picks"][3]["visibility"] == "premium"
    assert result["picks"][3]["razonamiento"] == "trusted-rationale-4"


@pytest.mark.parametrize(
    ("entries", "picks"),
    [
        (_six_entries()[:5], _stale_persisted_picks()),
        (
            _six_entries(),
            [*_stale_persisted_picks()[:5], {**_stale_persisted_picks()[5], "id": 107}],
        ),
        (
            [*_six_entries(), {**_six_entries()[0], "pick_id": 107, "position": 7}],
            [*_stale_persisted_picks(), {**_stale_persisted_picks()[0], "id": 107, "position": 7}],
        ),
    ],
    ids=["entry-count-mismatch", "missing-persisted-pick", "too-many-entries"],
)
def test_visibility_sync_fails_closed_on_incomplete_cardinality(entries, picks):
    with pytest.raises(ValueError, match="active batch"):
        synchronize_daily_visibility(
            entries,
            picks,
            created=True,
            feed_eligible=False,
        )


@pytest.mark.parametrize("rationale", [None, "short", {"unsafe": True}])
def test_visibility_sync_rejects_invalid_trusted_premium_rationale(rationale):
    entries = _six_entries()
    entries[3] = {
        **entries[3],
        "payload": {"razonamiento": rationale},
    }

    with pytest.raises(ValueError, match="premium rationale"):
        synchronize_daily_visibility(
            entries,
            _stale_persisted_picks(),
            created=True,
            feed_eligible=True,
        )


def test_visibility_sync_fails_closed_when_an_entry_cannot_map_exactly_once():
    entries = _six_entries()
    entries[-1] = {**entries[-1], "pick_id": entries[0]["pick_id"]}

    with pytest.raises(ValueError, match="map every active entry"):
        synchronize_daily_visibility(
            entries,
            _stale_persisted_picks(),
            created=False,
            feed_eligible=False,
        )

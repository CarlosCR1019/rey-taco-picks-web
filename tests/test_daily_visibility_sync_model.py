import pytest

from tests.daily_visibility_sync_model import synchronize_daily_visibility


def _six_entries():
    return [
        {
            "pick_id": 100 + position,
            "position": position,
            "visibility": "public" if position in {1, 5} else "premium",
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


@pytest.mark.parametrize(
    ("entries", "picks"),
    [
        (_six_entries()[:5], _stale_persisted_picks()),
        (_six_entries(), _stale_persisted_picks()[:5]),
        (_six_entries() + [{**_six_entries()[0], "position": 7}], _stale_persisted_picks()),
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

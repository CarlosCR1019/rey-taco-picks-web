import pytest

from backend.round_feed_eligibility import validate_round_feed_release


def pending_pick(index, visibility="premium"):
    return {
        "id": index,
        "active": True,
        "estado": "pendiente",
        "visibility": visibility,
        "es_parlay": False,
    }


def test_second_round_feed_accepts_one_public_pick_in_four_pick_batch():
    release = {
        "run_id": "11111111-1111-1111-1111-111111111111",
        "batch_id": "22222222-2222-2222-2222-222222222222",
        "portfolio_date": "2026-08-24",
        "feed_eligible": False,
    }
    picks = [pending_pick(1, "public"), *[pending_pick(i) for i in range(2, 5)]]

    assert validate_round_feed_release(release, picks) == release["run_id"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda release, picks: release.update(feed_eligible=True),
        lambda release, picks: picks[0].update(estado="ganado"),
        lambda release, picks: picks[1].update(visibility="public"),
        lambda release, picks: picks[0].update(es_parlay=True),
    ],
)
def test_second_round_feed_rejects_non_pending_or_invalid_allocations(mutate):
    release = {
        "run_id": "11111111-1111-1111-1111-111111111111",
        "batch_id": "22222222-2222-2222-2222-222222222222",
        "portfolio_date": "2026-08-24",
        "feed_eligible": False,
    }
    picks = [pending_pick(1, "public"), *[pending_pick(i) for i in range(2, 5)]]
    mutate(release, picks)

    with pytest.raises(ValueError):
        validate_round_feed_release(release, picks)

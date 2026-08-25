import pytest

from backend.settled_round_rollover import validate_settled_round


def released_entry(position, **pick_overrides):
    pick = {
        "id": 100 + position,
        "batch_id": "11111111-1111-1111-1111-111111111111",
        "estado": "ganado",
        "resultado_verificado_at": "2026-08-24T17:00:00+00:00",
    }
    pick.update(pick_overrides)
    return {
        "id": f"entry-{position}",
        "portfolio_date": "2026-08-24",
        "released_revision": 1,
        "pick_id": pick["id"],
        "picks": pick,
    }


def test_rollover_accepts_one_complete_six_pick_round():
    batch_id = validate_settled_round(
        "2026-08-24",
        [released_entry(position) for position in range(1, 7)],
    )

    assert batch_id == "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize(
    "entry_override",
    [
        {"released_revision": None},
        {"picks": {"estado": "pendiente"}},
        {"picks": {"resultado_verificado_at": None}},
    ],
)
def test_rollover_rejects_incomplete_or_unverified_entries(entry_override):
    entries = [released_entry(position) for position in range(1, 7)]
    entries[0].update(entry_override)

    with pytest.raises(ValueError):
        validate_settled_round("2026-08-24", entries)


def test_rollover_rejects_mixed_batches():
    entries = [released_entry(position) for position in range(1, 7)]
    entries[-1]["picks"]["batch_id"] = (
        "22222222-2222-2222-2222-222222222222"
    )

    with pytest.raises(ValueError, match="one batch"):
        validate_settled_round("2026-08-24", entries)

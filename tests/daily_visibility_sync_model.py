from collections.abc import Mapping, Sequence


def synchronize_daily_visibility(
    entries: Sequence[Mapping[str, object]],
    persisted_picks: Sequence[Mapping[str, object]],
    *,
    created: bool,
    feed_eligible: bool,
) -> dict[str, object]:
    """Executable model of the SQL visibility synchronization boundary."""

    if not 1 <= len(entries) <= 6 or len(persisted_picks) != len(entries):
        raise ValueError("daily release visibility sync found an incomplete active batch")

    entries_by_pick_id = {entry["pick_id"]: entry for entry in entries}
    picks_by_id = {pick["id"]: pick for pick in persisted_picks}
    if (
        len(entries_by_pick_id) != len(entries)
        or len(picks_by_id) != len(persisted_picks)
        or set(entries_by_pick_id) != set(picks_by_id)
    ):
        raise ValueError(
            "daily release visibility sync could not map every active entry"
        )

    synchronized = []
    for pick in persisted_picks:
        copied = dict(pick)
        visibility = entries_by_pick_id[pick["id"]]["visibility"]
        copied["visibility"] = visibility
        if visibility == "public":
            copied["razonamiento"] = None
        synchronized.append(copied)

    return {
        "created": created,
        "feed_eligible": feed_eligible,
        "picks": synchronized,
    }

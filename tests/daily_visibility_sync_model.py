from collections.abc import Mapping, Sequence


def synchronize_daily_visibility(
    entries: Sequence[Mapping[str, object]],
    persisted_picks: Sequence[Mapping[str, object]],
    *,
    created: bool,
    feed_eligible: bool,
) -> dict[str, object]:
    """Executable model of the SQL visibility synchronization boundary."""

    if not 1 <= len(persisted_picks) <= 6:
        raise ValueError("daily release visibility sync found an incomplete active batch")

    picks_by_id = {pick["id"]: pick for pick in persisted_picks}
    mapped_entries = [entry for entry in entries if entry["pick_id"] in picks_by_id]
    if len(mapped_entries) != len(persisted_picks):
        raise ValueError("daily release visibility sync found an incomplete active batch")

    entries_by_pick_id = {entry["pick_id"]: entry for entry in mapped_entries}
    if (
        len(entries_by_pick_id) != len(mapped_entries)
        or len(picks_by_id) != len(persisted_picks)
        or set(entries_by_pick_id) != set(picks_by_id)
    ):
        raise ValueError(
            "daily release visibility sync could not map every active entry"
        )

    synchronized = []
    for pick in persisted_picks:
        copied = dict(pick)
        entry = entries_by_pick_id[pick["id"]]
        visibility = entry["visibility"]
        copied["visibility"] = visibility
        if visibility == "public":
            copied["razonamiento"] = None
        else:
            rationale = entry.get("payload", {}).get("razonamiento")
            if not isinstance(rationale, str) or not 10 <= len(rationale.strip()) <= 500:
                raise ValueError("daily release visibility sync found invalid premium rationale")
            copied["razonamiento"] = rationale.strip()
        synchronized.append(copied)

    return {
        "created": created,
        "feed_eligible": feed_eligible,
        "picks": synchronized,
    }

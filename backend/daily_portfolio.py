"""Deterministic rules for one revisioned Mexico-day pick portfolio."""

from __future__ import annotations

from argparse import ArgumentParser
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import re
from typing import Iterator
import unicodedata
from zoneinfo import ZoneInfo

from backend.publishing_policy import expected_public_pick_count


MEXICO_CITY = ZoneInfo("America/Mexico_City")
MAX_DAILY_PICKS = 6
MAX_TIME_BLOCK_PICKS = 2
_AUDIT_FIELDS = (
    "source",
    "source_event_id",
    "source_market_key",
    "source_selection_key",
)


class _BoundedArgumentParser(ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid arguments")


@dataclass(frozen=True, slots=True)
class FrozenDailyPick(Mapping[str, object]):
    """Immutable scalar copy used across the stage/release boundary."""

    _items: tuple[tuple[str, object], ...]

    def __getitem__(self, key: str) -> object:
        for item_key, value in self._items:
            if item_key == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _value in self._items)

    def __len__(self) -> int:
        return len(self._items)


def mexico_portfolio_date(value: datetime) -> str:
    """Return the Mexico City calendar date for one aware instant."""

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("value must be timezone-aware")
    return value.astimezone(MEXICO_CITY).date().isoformat()


def _created_at(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("created_at must be an ISO timestamp")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise ValueError("created_at must be an ISO timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    return parsed


def run_cli(argv: Sequence[str] | None = None) -> int:
    parser = _BoundedArgumentParser(add_help=False)
    parser.add_argument("--created-at", required=True)
    try:
        args = parser.parse_args(argv)
        portfolio_date = mexico_portfolio_date(_created_at(args.created_at))
    except (SystemExit, TypeError, ValueError):
        print("portfolio_date=invalid")
        return 2
    print(f"portfolio_date={portfolio_date}")
    return 0


def audit_identity(row: Mapping[str, object]) -> tuple[str, str, str, str]:
    """Return the complete official source identity or fail closed."""

    if not isinstance(row, Mapping):
        raise TypeError("pick must be a mapping")
    identity: list[str] = []
    for field in _AUDIT_FIELDS:
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must not be empty")
        identity.append(value.strip())
    return tuple(identity)  # type: ignore[return-value]


def physical_event_identity(row: Mapping[str, object]) -> str:
    return physical_event_key(row)


def physical_event_key(row: Mapping[str, object]) -> str:
    """Return a source-independent identity for one physical matchup."""

    matchup = row.get("partido")
    if not isinstance(matchup, str) or not matchup.strip():
        raise ValueError("partido must not be empty")
    normalized_matchup = _normalize_matchup(matchup)
    if not normalized_matchup:
        raise ValueError("partido must contain an identifiable matchup")
    digest = sha256(normalized_matchup.encode("utf-8")).hexdigest()
    return f"physical:v1:{digest}"


def mexico_time_block(row: Mapping[str, object]) -> int:
    """Return the six-hour CDMX block for one audited event start."""

    if not isinstance(row, Mapping):
        raise TypeError("pick must be a mapping")
    return _created_at(row.get("source_starts_at")).astimezone(
        MEXICO_CITY
    ).hour // 6


def _normalize_matchup(value: str) -> str:
    ascii_value = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    ).casefold()
    sides = re.split(
        r"\s+(?:v(?:s)?[.]?|versus|contra)\s+|\s+[-–—]\s+",
        ascii_value,
        maxsplit=1,
    )
    normalized_sides = [" ".join(re.findall(r"[a-z0-9]+", side)) for side in sides]
    normalized_sides = [side for side in normalized_sides if side]
    if len(normalized_sides) == 2:
        normalized_sides.sort()
        return " vs ".join(normalized_sides)
    return " ".join(normalized_sides)


def merge_daily_portfolio(
    released_rows: Sequence[Mapping[str, object]],
    ranked_rows: Sequence[Mapping[str, object]],
) -> tuple[FrozenDailyPick, ...]:
    """Keep released picks immutable and replace only the remaining draft.

    Candidate order is authoritative. Duplicate events and audit identities are
    skipped. The largest safe prefix is retained without ever forcing a parlay
    into a public slot.
    """

    released = _validated_sequence(released_rows, field="released")
    ranked = _validated_sequence(ranked_rows, field="ranked")
    for row in [*released, *ranked]:
        if type(row.get("es_parlay")) is not bool:
            raise ValueError("es_parlay must be an explicit boolean")
    if len(released) > MAX_DAILY_PICKS:
        raise ValueError("released portfolio exceeds six picks")

    used_audits: set[tuple[str, str, str, str]] = set()
    used_events: set[str] = set()
    block_counts = [0, 0, 0, 0]
    public_blocks: set[int] = set()
    public_count = 0
    for row in released:
        identity = audit_identity(row)
        event = physical_event_identity(row)
        if identity in used_audits or event in used_events:
            raise ValueError("released portfolio contains duplicate identities")
        used_audits.add(identity)
        used_events.add(event)
        block = mexico_time_block(row)
        if block_counts[block] >= MAX_TIME_BLOCK_PICKS:
            raise ValueError("released portfolio exceeds time block capacity")
        block_counts[block] += 1
        visibility = row.get("visibility")
        if visibility not in {"public", "premium"}:
            raise ValueError("released portfolio has invalid visibility")
        if visibility == "public":
            if row.get("es_parlay") is not False:
                raise ValueError("released public pick cannot be a parlay")
            public_count += 1
            public_blocks.add(block)

    if released and public_count != expected_public_pick_count(len(released)):
        raise ValueError("released portfolio has invalid public allocation")

    candidate_pool: list[dict[str, object]] = []
    for row in ranked:
        identity = audit_identity(row)
        event = physical_event_identity(row)
        if identity in used_audits or event in used_events:
            continue
        block = mexico_time_block(row)
        if block_counts[block] >= MAX_TIME_BLOCK_PICKS:
            continue
        used_audits.add(identity)
        used_events.add(event)
        block_counts[block] += 1
        prepared = dict(row)
        prepared["visibility"] = "premium"
        candidate_pool.append(prepared)

    available_slots = MAX_DAILY_PICKS - len(released)
    selected = candidate_pool[:available_slots]
    needed = (
        expected_public_pick_count(len(released) + len(selected))
        - public_count
    )
    if len(released) + len(selected) == MAX_DAILY_PICKS and needed > 0:
        preferred_public: list[dict[str, object]] = []
        preferred_blocks = set(public_blocks)
        for prefer_new_block in (True, False):
            for row in candidate_pool:
                if row.get("es_parlay") is not False:
                    continue
                if row in preferred_public:
                    continue
                block = mexico_time_block(row)
                if prefer_new_block and block in preferred_blocks:
                    continue
                preferred_public.append(row)
                preferred_blocks.add(block)
                if len(preferred_public) == needed:
                    break
            if len(preferred_public) == needed:
                break

        preferred_identities = {
            audit_identity(row) for row in preferred_public
        }
        selected_identities = {audit_identity(row) for row in selected}
        for preferred in preferred_public:
            preferred_identity = audit_identity(preferred)
            if preferred_identity in selected_identities:
                continue
            replacement_index = next(
                (
                    index
                    for index in range(len(selected) - 1, -1, -1)
                    if audit_identity(selected[index])
                    not in preferred_identities
                ),
                None,
            )
            if replacement_index is None:
                break
            selected_identities.discard(
                audit_identity(selected[replacement_index])
            )
            selected[replacement_index] = preferred
            selected_identities.add(preferred_identity)
        selected.sort(key=candidate_pool.index)

    while selected or released:
        total = len(released) + len(selected)
        target = expected_public_pick_count(total)
        needed = target - public_count
        eligible_new = sum(row.get("es_parlay") is False for row in selected)
        if needed >= 0 and eligible_new >= needed:
            break
        if not selected:
            raise ValueError("released portfolio has invalid public allocation")
        selected.pop()

    needed = expected_public_pick_count(len(released) + len(selected)) - public_count
    assigned_public: set[tuple[str, str, str, str]] = set()
    for prefer_new_block in (True, False):
        for row in selected:
            identity = audit_identity(row)
            block = mexico_time_block(row)
            if (
                not needed
                or row.get("es_parlay") is not False
                or identity in assigned_public
                or (prefer_new_block and block in public_blocks)
            ):
                continue
            row["visibility"] = "public"
            assigned_public.add(identity)
            public_blocks.add(block)
            needed -= 1
        if not needed:
            break
    if needed:
        raise ValueError("portfolio cannot satisfy the public allocation")

    return tuple(_freeze(row) for row in [*released, *selected])


def _validated_sequence(
    value: Sequence[Mapping[str, object]], *, field: str
) -> list[dict[str, object]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise TypeError(f"{field} rows must be a sequence")
    rows: list[dict[str, object]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise TypeError(f"{field} row must be a mapping")
        rows.append(dict(row))
    return rows


def _freeze(row: Mapping[str, object]) -> FrozenDailyPick:
    for value in row.values():
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise ValueError("portfolio picks must contain scalar values")
    return FrozenDailyPick(tuple((key, row[key]) for key in sorted(row)))


if __name__ == "__main__":
    raise SystemExit(run_cli())

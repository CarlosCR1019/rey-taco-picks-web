"""Open a new same-day round only after a six-pick round is fully audited."""

from __future__ import annotations

import os
from datetime import date
from uuid import UUID

from dotenv import load_dotenv
from supabase import create_client


FINAL_STATES = frozenset({"ganado", "perdido", "void"})


def _related_pick(entry: dict) -> dict:
    related = entry.get("picks")
    if isinstance(related, list):
        if len(related) != 1:
            raise ValueError("settled entry must resolve to one pick")
        related = related[0]
    if not isinstance(related, dict):
        raise ValueError("settled entry is missing its pick")
    return related


def validate_settled_round(portfolio_date: str, entries: list[dict]) -> str:
    try:
        if date.fromisoformat(portfolio_date).isoformat() != portfolio_date:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("rollover portfolio date is invalid") from exc
    if not isinstance(entries, list) or len(entries) != 6:
        raise ValueError("rollover requires exactly six active entries")

    entry_ids = set()
    pick_ids = set()
    batch_ids = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or entry.get("portfolio_date") != portfolio_date
            or entry.get("released_revision") is None
            or entry.get("pick_id") is None
        ):
            raise ValueError("rollover entry is not a released pick")
        pick = _related_pick(entry)
        if (
            pick.get("estado") not in FINAL_STATES
            or not pick.get("resultado_verificado_at")
            or pick.get("id") != entry.get("pick_id")
            or not pick.get("batch_id")
        ):
            raise ValueError("rollover pick is not verified and final")
        entry_ids.add(entry.get("id"))
        pick_ids.add(pick.get("id"))
        batch_ids.add(str(pick.get("batch_id")))

    if len(entry_ids) != 6 or len(pick_ids) != 6:
        raise ValueError("rollover entries must be unique")
    if len(batch_ids) != 1:
        raise ValueError("rollover entries must belong to one batch")
    batch_id = next(iter(batch_ids))
    try:
        UUID(batch_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("rollover batch id is invalid") from exc
    return batch_id


def rollover_settled_round(client, portfolio_date: str) -> int:
    entries = (
        client.table("daily_pick_entries")
        .select(
            "id,portfolio_date,released_revision,pick_id,"
            "picks(id,batch_id,estado,resultado_verificado_at)"
        )
        .eq("portfolio_date", portfolio_date)
        .eq("active", True)
        .execute()
        .data
        or []
    )
    batch_id = validate_settled_round(portfolio_date, entries)

    portfolios = (
        client.table("daily_pick_portfolios")
        .select("portfolio_date,batch_id")
        .eq("portfolio_date", portfolio_date)
        .execute()
        .data
        or []
    )
    if len(portfolios) != 1 or str(portfolios[0].get("batch_id")) != batch_id:
        raise RuntimeError("daily portfolio no longer points to the settled batch")

    detached = (
        client.table("daily_pick_portfolios")
        .update({"batch_id": None})
        .eq("portfolio_date", portfolio_date)
        .eq("batch_id", batch_id)
        .execute()
        .data
        or []
    )
    if len(detached) != 1:
        raise RuntimeError("settled daily portfolio changed before rollover")

    deleted = (
        client.table("daily_pick_entries")
        .delete()
        .eq("portfolio_date", portfolio_date)
        .execute()
        .data
        or []
    )
    if len(deleted) != 6:
        raise RuntimeError("settled entry cleanup was incomplete")
    return len(deleted)


def main() -> int:
    load_dotenv()
    url = (os.getenv("SUPABASE_URL") or "").strip()
    service_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    portfolio_date = (os.getenv("ROLLOVER_SETTLED_PORTFOLIO_DATE") or "").strip()
    if not url or not service_key or not portfolio_date:
        raise RuntimeError("Supabase and rollover portfolio date are required")

    client = create_client(url, service_key)
    count = rollover_settled_round(client, portfolio_date)
    print(f"settled_round_rollover_entries={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Promote one audited same-day release to the social feed recovery path."""

from __future__ import annotations

import os
from datetime import date
from uuid import UUID

from dotenv import load_dotenv
from supabase import create_client


def validate_round_feed_release(release: dict, picks: list[dict]) -> str:
    if not isinstance(release, dict) or release.get("feed_eligible") is not False:
        raise ValueError("round release must exist and be feed-ineligible")
    try:
        run_id = str(UUID(str(release.get("run_id"))))
        UUID(str(release.get("batch_id")))
        portfolio_date = str(release.get("portfolio_date"))
        if date.fromisoformat(portfolio_date).isoformat() != portfolio_date:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("round release identifiers are invalid") from exc
    if not isinstance(picks, list) or not 1 <= len(picks) <= 6:
        raise ValueError("round feed requires between one and six picks")
    if any(
        not isinstance(pick, dict)
        or pick.get("active") is not True
        or pick.get("estado") != "pendiente"
        or pick.get("visibility") not in {"public", "premium"}
        or type(pick.get("es_parlay")) is not bool
        for pick in picks
    ):
        raise ValueError("round feed picks must be active and pending")
    public = [pick for pick in picks if pick["visibility"] == "public"]
    expected_public = 2 if len(picks) == 6 else 1
    if len(public) != expected_public or any(pick["es_parlay"] for pick in public):
        raise ValueError("round feed has an invalid public allocation")
    if len({pick.get("id") for pick in picks}) != len(picks):
        raise ValueError("round feed picks must be unique")
    return run_id


def enable_round_feed(client, run_key: str) -> str:
    runs = (
        client.table("scraper_runs")
        .select("id,run_key,status")
        .eq("run_key", run_key)
        .execute()
        .data
        or []
    )
    if len(runs) != 1 or runs[0].get("status") not in {"published", "partial"}:
        raise RuntimeError("collector run is not a published exact target")
    run_id = str(runs[0]["id"])
    releases = (
        client.table("daily_pick_releases")
        .select("run_id,batch_id,portfolio_date,feed_eligible")
        .eq("run_id", run_id)
        .execute()
        .data
        or []
    )
    if len(releases) != 1:
        raise RuntimeError("collector run does not have one daily release")
    release = releases[0]
    picks = (
        client.table("picks")
        .select("id,active,estado,visibility,es_parlay")
        .eq("batch_id", release["batch_id"])
        .eq("active", True)
        .execute()
        .data
        or []
    )
    validate_round_feed_release(release, picks)

    other_eligible = (
        client.table("daily_pick_releases")
        .select("run_id")
        .eq("batch_id", release["batch_id"])
        .eq("feed_eligible", True)
        .execute()
        .data
        or []
    )
    if other_eligible:
        raise RuntimeError("round batch already has a feed-eligible release")
    updated = (
        client.table("daily_pick_releases")
        .update({"feed_eligible": True})
        .eq("run_id", run_id)
        .eq("feed_eligible", False)
        .execute()
        .data
        or []
    )
    if len(updated) != 1:
        raise RuntimeError("round release changed before feed promotion")
    return run_id


def main() -> int:
    load_dotenv()
    url = (os.getenv("SUPABASE_URL") or "").strip()
    service_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    run_key = (os.getenv("ENABLE_ROUND_FEED_RUN_KEY") or "").strip()
    if not url or not service_key or not run_key:
        raise RuntimeError("Supabase and exact round run key are required")
    run_id = enable_round_feed(create_client(url, service_key), run_key)
    print(f"round_feed_release={run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Apply narrowly scoped, human-reviewed final-score evidence to pending picks."""

from __future__ import annotations

import json
import os
from datetime import date
from urllib.parse import urlparse

from dotenv import load_dotenv
from supabase import create_client

from backend.verificar_resultados import grade_pending_pick


def _text(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _validated_evidence(row: object) -> dict:
    if not isinstance(row, dict):
        raise ValueError("manual evidence row must be an object")
    required = (
        "partido",
        "pick",
        "source",
        "source_id",
        "event_date",
        "home_team",
        "away_team",
        "home_score",
        "away_score",
        "completed",
    )
    if any(key not in row for key in required):
        raise ValueError("manual evidence row is incomplete")
    if row["completed"] is not True:
        raise ValueError("manual evidence must describe a final event")
    try:
        if date.fromisoformat(str(row["event_date"])).isoformat() != row["event_date"]:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("manual evidence has an invalid event date") from exc
    source_url = urlparse(str(row["source_id"]))
    if source_url.scheme != "https" or not source_url.netloc:
        raise ValueError("manual evidence source_id must be an HTTPS result URL")
    if not _text(row["source"]):
        raise ValueError("manual evidence source must not be blank")
    return dict(row)


def build_manual_result_updates(pending_picks: list[dict], evidence: list[dict]):
    """Build audited optimistic updates without mutating the database."""
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
        raise ValueError("manual evidence must contain between one and twenty rows")

    updates = []
    seen_ids = set()
    for raw in evidence:
        result = _validated_evidence(raw)
        candidates = [
            pick
            for pick in pending_picks
            if pick.get("estado") == "pendiente"
            and pick.get("active") is True
            and _text(pick.get("partido")) == _text(result["partido"])
            and str(pick.get("fecha_evento") or pick.get("fecha_generacion", ""))[:10]
            == result["event_date"]
        ]
        if len(candidates) != 1:
            raise ValueError("manual evidence must match exactly one pending pick")
        selected = candidates[0]
        if _text(selected.get("pick")) != _text(result["pick"]):
            raise ValueError("manual evidence selection does not match the pending pick")
        if selected.get("id") in seen_ids:
            raise ValueError("manual evidence contains a duplicate pending pick")

        audited_result = dict(result)
        audited_result["scores"] = [
            {"name": result["home_team"], "score": result["home_score"]},
            {"name": result["away_team"], "score": result["away_score"]},
        ]
        decision = grade_pending_pick(selected, audited_result)
        if not decision or decision.get("estado") not in {"ganado", "perdido", "void"}:
            raise ValueError("manual evidence could not produce a final audited result")
        seen_ids.add(selected["id"])
        updates.append((selected["id"], decision))
    return updates


def apply_manual_result_updates(client, updates) -> int:
    updated = 0
    for pick_id, decision in updates:
        response = (
            client.table("picks")
            .update(decision)
            .eq("id", pick_id)
            .eq("estado", "pendiente")
            .eq("active", True)
            .execute()
        )
        if len(response.data or []) != 1:
            raise RuntimeError(
                f"pending pick {pick_id} changed before the audited update"
            )
        updated += 1
    return updated


def main() -> int:
    load_dotenv()
    url = (os.getenv("SUPABASE_URL") or "").strip()
    service_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    raw_evidence = (os.getenv("MANUAL_RESULT_EVIDENCE_JSON") or "").strip()
    if not url or not service_key or not raw_evidence:
        raise RuntimeError("Supabase and manual result evidence are required")

    evidence = json.loads(raw_evidence)
    client = create_client(url, service_key)
    pending = (
        client.table("picks")
        .select("*")
        .eq("estado", "pendiente")
        .eq("active", True)
        .execute()
        .data
        or []
    )
    updates = build_manual_result_updates(pending, evidence)
    count = apply_manual_result_updates(client, updates)
    print(f"manual_result_updates={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fail-closed preflight for an exact persisted delivery recovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from typing import Literal

from dotenv import dotenv_values

from backend.scraper_config import BACKEND_DIR, load_settings
from backend.social_poster import MetaSettings


RecoveryState = Literal["eligible", "complete", "ambiguous", "not_configured"]
_META_TERMINAL_ERRORS = frozenset(
    {"token_invalid", "delivery_failed", "not_configured"}
)


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    telegram: RecoveryState
    social: RecoveryState


def _telegram_plan(
    ledger: Mapping[str, object], destinations: Sequence[str]
) -> RecoveryState:
    if not destinations:
        return "not_configured"
    retry_needed = False
    for destination in destinations:
        entry = ledger.get(destination)
        if not isinstance(entry, Mapping):
            return "ambiguous"
        if entry.get("success") is True:
            continue
        error = entry.get("error")
        if entry.get("success") is False and isinstance(error, str) and error:
            retry_needed = True
            continue
        return "ambiguous"
    return "eligible" if retry_needed else "complete"


def _social_plan(
    ledger: Mapping[str, object], destinations: Sequence[str]
) -> RecoveryState:
    if not destinations:
        return "not_configured"
    retry_needed = False
    for destination in destinations:
        entry = ledger.get(destination)
        # Meta persists a claim before transmitting, so an absent entry proves
        # that this destination has not started and is safe to attempt.
        if entry is None:
            retry_needed = True
            continue
        if not isinstance(entry, Mapping):
            return "ambiguous"
        if entry.get("success") is True and entry.get("state") == "success":
            continue
        if (
            entry.get("success") is False
            and entry.get("state") == "failed"
            and entry.get("error") in _META_TERMINAL_ERRORS
        ):
            retry_needed = True
            continue
        return "ambiguous"
    return "eligible" if retry_needed else "complete"


def build_recovery_plan(
    release: Mapping[str, object] | None,
    *,
    portfolio_date: str,
    telegram_destinations: Sequence[str],
    meta_destinations: Sequence[str],
) -> RecoveryPlan:
    if release is None:
        raise RuntimeError("exact daily release does not exist")
    if release.get("portfolio_date") != portfolio_date:
        raise RuntimeError("exact daily release date mismatch")
    ledger = release.get("delivery_status")
    if not isinstance(ledger, Mapping):
        raise RuntimeError("exact daily release ledger is invalid")
    return RecoveryPlan(
        telegram=_telegram_plan(ledger, telegram_destinations),
        social=_social_plan(ledger, meta_destinations),
    )


def run_main(*, values: Mapping[str, str] | None = None, repository=None) -> int:
    try:
        settings = load_settings(values, dry_run=False)
        runtime_values = values
        if runtime_values is None:
            loaded_values = dict(dotenv_values(BACKEND_DIR / ".env"))
            loaded_values.update(os.environ)
            runtime_values = loaded_values
        meta_settings = MetaSettings.from_mapping(runtime_values)
        active_repository = repository
        if active_repository is None:
            from supabase import create_client

            from backend.pick_publisher import SupabaseBatchRepository

            client = create_client(settings.supabase_url, settings.service_role_key)
            active_repository = SupabaseBatchRepository(client)
        release = active_repository.resume_daily(settings.run_key)
        telegram_destinations = tuple(
            name
            for name, configured in (
                ("admin", settings.telegram_admin_id),
                ("vip", settings.telegram_vip_id),
                ("free", settings.telegram_free_id),
            )
            if configured
        )
        meta_destinations = tuple(
            name
            for name, configured in (
                (
                    "facebook",
                    bool(meta_settings.token and meta_settings.facebook_page_id),
                ),
                (
                    "instagram",
                    bool(meta_settings.token and meta_settings.instagram_user_id),
                ),
            )
            if configured
        )
        plan = build_recovery_plan(
            release,
            portfolio_date=settings.daily_portfolio_date,
            telegram_destinations=telegram_destinations,
            meta_destinations=meta_destinations,
        )
    except Exception:
        print("recovery_target=invalid")
        return 2
    print("recovery_target=valid")
    print(f"telegram_recovery={plan.telegram}")
    print(f"social_recovery={plan.social}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_main())

"""Idempotent orchestration for audited vertical social media."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
import logging
from typing import Protocol

from backend.social_poster import MetaSettings, _runtime_values, resolve_run_key
from backend.social_repository import MetaSocialBatch, SupabaseSocialRepository
from backend.story_renderer import render_story_jpeg
from backend.telegram_publisher import TelegramDestination, TelegramHttpTransport
from backend.vertical_content import (
    VerticalCard,
    build_public_pick_story,
    build_vip_teaser_story,
)
from backend.vertical_meta import VerticalDelivery, VerticalMetaHttpTransport
from backend.vertical_repository import (
    SupabaseVerticalRepository,
    TemporaryAsset,
    VerticalClaim,
)


LOGGER = logging.getLogger(__name__)
_PRE_EVENT_KINDS = ("public_pick_story", "vip_teaser_story")
_SAFE_KINDS = frozenset(
    {
        *_PRE_EVENT_KINDS,
        "final_results_story",
        "verified_result_story",
        "ticket_evidence_story",
        "reel_cta_story",
        "daily_results_reel",
    }
)
_HEALTHY_STATUSES = frozenset({"success", "complete", "dry_run"})
_SAFE_STATUSES = frozenset(
    {
        *_HEALTHY_STATUSES,
        "ambiguous",
        "not_configured",
        "token_invalid",
        "delivery_failed",
        "media_invalid",
        "pending_review",
        "crosspost_unverified",
    }
)


class VerticalRepository(Protocol):
    def claim(self, **kwargs: object) -> VerticalClaim: ...

    def upload_story(
        self, *, card: VerticalCard, jpeg: bytes
    ) -> TemporaryAsset: ...

    def complete(self, **kwargs: object) -> None: ...

    def delete_temporary(self, asset: TemporaryAsset) -> None: ...


class VerticalTransport(Protocol):
    def publish_instagram_story(
        self, *, image_url: str, settings: MetaSettings
    ) -> VerticalDelivery: ...


class TelegramTransport(Protocol):
    def __call__(self, destination: TelegramDestination, text: str) -> None: ...


def _record_failure(
    card: VerticalCard,
    *,
    repository: VerticalRepository,
    attempt_id: str,
    error: str,
) -> None:
    try:
        repository.complete(
            package=card,
            destination="instagram_story",
            attempt_id=attempt_id,
            success=False,
            receipt="",
            error=error,
        )
    except Exception as exc:
        LOGGER.warning(
            "vertical completion status=failed kind=%s exception=%s",
            card.kind,
            type(exc).__name__,
        )


def _publish_story(
    card: VerticalCard,
    *,
    repository: VerticalRepository,
    transport: VerticalTransport,
    settings: MetaSettings,
    renderer: Callable[[VerticalCard], bytes],
) -> str:
    """Claim and finish one story without exposing raw dependency errors."""

    try:
        claim = repository.claim(
            batch_id=card.batch_id,
            portfolio_date=card.portfolio_date,
            content_kind=card.kind,
            destination="instagram_story",
            digest=card.digest,
            template_version=card.template_version,
        )
    except Exception as exc:
        LOGGER.warning(
            "vertical claim status=failed kind=%s exception=%s",
            card.kind,
            type(exc).__name__,
        )
        return "delivery_failed"
    if claim.state != "claimed":
        return claim.state
    if claim.attempt_id is None:
        LOGGER.warning("vertical claim status=invalid kind=%s", card.kind)
        return "delivery_failed"

    asset: TemporaryAsset | None = None
    try:
        jpeg = renderer(card)
        asset = repository.upload_story(card=card, jpeg=jpeg)
        delivery = transport.publish_instagram_story(
            image_url=asset.url,
            settings=settings,
        )
        if (
            not isinstance(delivery, VerticalDelivery)
            or delivery.destination != "instagram_story"
        ):
            raise RuntimeError("vertical transport returned invalid delivery")
        success = delivery.status == "success"
        repository.complete(
            package=card,
            destination="instagram_story",
            attempt_id=claim.attempt_id,
            success=success,
            receipt=delivery.receipt if success else "",
            error="" if success else delivery.status,
        )
        return delivery.status
    except Exception as exc:
        LOGGER.warning(
            "vertical delivery status=failed kind=%s exception=%s",
            card.kind,
            type(exc).__name__,
        )
        _record_failure(
            card,
            repository=repository,
            attempt_id=claim.attempt_id,
            error="delivery_failed",
        )
        return "delivery_failed"
    finally:
        if asset is not None:
            try:
                repository.delete_temporary(asset)
            except RuntimeError as exc:
                LOGGER.warning(
                    "vertical cleanup status=failed kind=%s exception=%s",
                    card.kind,
                    type(exc).__name__,
                )


def publish_pre_event_stories(
    *,
    batch: MetaSocialBatch,
    portfolio_date: str,
    repository: VerticalRepository,
    transport: VerticalTransport,
    settings: MetaSettings,
    renderer: Callable[[VerticalCard], bytes],
) -> dict[str, str]:
    """Publish the public story followed by the privacy-safe VIP teaser."""

    cards = (
        build_public_pick_story(batch, portfolio_date=portfolio_date),
        build_vip_teaser_story(batch, portfolio_date=portfolio_date),
    )
    outcomes: dict[str, str] = {}
    for card in cards:
        if settings.dry_run:
            try:
                renderer(card)
            except Exception as exc:
                LOGGER.warning(
                    "vertical render status=failed kind=%s exception=%s",
                    card.kind,
                    type(exc).__name__,
                )
                outcomes[card.kind] = "delivery_failed"
            else:
                outcomes[card.kind] = "dry_run"
            continue
        outcomes[card.kind] = _publish_story(
            card,
            repository=repository,
            transport=transport,
            settings=settings,
            renderer=renderer,
        )
    return outcomes


def _validated_outcomes(outcomes: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(outcomes, Mapping):
        raise ValueError("vertical outcomes must be safe")
    normalized: dict[str, str] = {}
    for name, status in outcomes.items():
        if name not in _SAFE_KINDS or status not in _SAFE_STATUSES:
            raise ValueError("vertical outcomes must be safe")
        normalized[name] = status
    return normalized


def notify_vertical_failures(
    outcomes: Mapping[str, str],
    *,
    telegram: TelegramTransport | None,
    admin_chat_id: str,
) -> None:
    """Send a fixed-format admin alert containing no raw exception detail."""

    safe_outcomes = _validated_outcomes(outcomes)
    failures = [
        (name, status)
        for name, status in sorted(safe_outcomes.items())
        if status not in _HEALTHY_STATUSES
    ]
    if not failures or telegram is None or not admin_chat_id:
        return
    lines = ["⚠️ Rey Taco · contenido vertical incompleto"]
    lines.extend(f"• {name}: {status}" for name, status in failures)
    telegram(
        TelegramDestination("admin", admin_chat_id, "all"),
        "\n".join(lines),
    )


def _portfolio_date(values: Mapping[str, object]) -> str:
    raw = values.get("DAILY_PORTFOLIO_DATE")
    if not isinstance(raw, str) or raw != raw.strip():
        raise ValueError("DAILY_PORTFOLIO_DATE must be a canonical date")
    try:
        normalized = date.fromisoformat(raw).isoformat()
    except ValueError:
        raise ValueError("DAILY_PORTFOLIO_DATE must be a canonical date") from None
    if normalized != raw:
        raise ValueError("DAILY_PORTFOLIO_DATE must be a canonical date")
    return normalized


def _required_runtime_string(values: Mapping[str, object], field: str) -> str:
    value = values.get(field, "")
    if not isinstance(value, str):
        raise ValueError(f"{field} is invalid")
    return value


def _exit_code(outcomes: Mapping[str, str], *, settings: MetaSettings) -> int:
    safe_outcomes = _validated_outcomes(outcomes)
    incomplete = any(
        status not in _HEALTHY_STATUSES for status in safe_outcomes.values()
    )
    if settings.dry_run:
        return int(incomplete)
    if not settings.token or not settings.instagram_user_id:
        return 0
    return int(incomplete)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish Rey Taco vertical media")
    parser.add_argument("--mode", choices=("pre-event",), required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run the pre-event publisher and return a safe process exit code."""

    try:
        _parser().parse_args(argv)
        values = _runtime_values(environ)
        portfolio_date = _portfolio_date(values)
        run_key = resolve_run_key(values)
        supabase_url = _required_runtime_string(values, "SUPABASE_URL")
        service_role_key = _required_runtime_string(
            values, "SUPABASE_SERVICE_ROLE_KEY"
        )
        settings = MetaSettings.from_mapping(values)
        reference_at = datetime.now(timezone.utc)
        social_repository = SupabaseSocialRepository(
            supabase_url=supabase_url,
            service_role_key=service_role_key,
        )
        exact_batch = social_repository.get_batch(
            run_key=run_key,
            reference_at=reference_at,
        )
        if exact_batch is None:
            LOGGER.info("vertical mode=pre-event batch=no_batch")
            return 0

        repository = SupabaseVerticalRepository(
            url=supabase_url,
            service_role_key=service_role_key,
        )
        outcomes = publish_pre_event_stories(
            batch=exact_batch,
            portfolio_date=portfolio_date,
            repository=repository,
            transport=VerticalMetaHttpTransport(),
            settings=settings,
            renderer=render_story_jpeg,
        )
        safe_outcomes = _validated_outcomes(outcomes)
        for kind, status in safe_outcomes.items():
            LOGGER.info("vertical kind=%s status=%s", kind, status)

        if not settings.dry_run:
            telegram_token = _required_runtime_string(values, "TELEGRAM_BOT_TOKEN")
            admin_chat_id = _required_runtime_string(values, "TELEGRAM_CHAT_ID")
            telegram: TelegramTransport | None = None
            if telegram_token and admin_chat_id:
                telegram = TelegramHttpTransport(telegram_token)
            try:
                notify_vertical_failures(
                    safe_outcomes,
                    telegram=telegram,
                    admin_chat_id=admin_chat_id,
                )
            except Exception as exc:
                LOGGER.warning(
                    "vertical alert status=failed exception=%s", type(exc).__name__
                )
        return _exit_code(safe_outcomes, settings=settings)
    except Exception as exc:
        LOGGER.info(
            "vertical command=status_failed exception=%s", type(exc).__name__
        )
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())

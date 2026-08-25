"""Idempotent orchestration for audited vertical social media."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timezone
import logging
from pathlib import Path
import re
import shutil
from typing import Protocol, cast

from supabase import create_client

from backend.social_poster import MetaSettings, _runtime_values, resolve_run_key
from backend.result_report_repository import SupabaseResultReportRepository
from backend.result_reporting import ResultReport, build_result_report
from backend.reel_renderer import ReelRenderer as LocalReelRenderer
from backend.social_repository import MetaSocialBatch, SupabaseSocialRepository
from backend.story_renderer import render_story_jpeg, render_ticket_evidence_jpeg
from backend.telegram_publisher import TelegramDestination, TelegramHttpTransport
from backend.ticket_evidence import (
    EvidenceInspector,
    MatchedEvidence,
    TelegramTicketFetcher,
    collect_matched_evidence,
    tesseract_ocr,
)
from backend.vertical_content import (
    ReelPackage,
    VerticalCard,
    build_daily_reel_package,
    build_final_results_story,
    build_public_pick_story,
    build_reel_cta_story,
    build_ticket_evidence_card,
    build_verified_result_story,
    build_vip_teaser_story,
)
from backend.vertical_meta import VerticalDelivery, VerticalMetaHttpTransport
from backend.vertical_repository import (
    SupabaseTicketEvidenceRepository,
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
        "instagram_reel",
        "facebook_reel",
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


def _write_dry_run_preview(
    settings: MetaSettings,
    *,
    name: str,
    suffix: str,
    payload: bytes,
) -> None:
    """Persist an explicitly requested local preview without logging its path."""

    if not settings.dry_run_output:
        return
    if re.fullmatch(r"[a-z0-9_-]{1,100}", name) is None:
        raise ValueError("vertical preview name is invalid")
    if suffix not in {".jpg", ".mp4"} or not isinstance(payload, bytes):
        raise ValueError("vertical preview payload is invalid")
    directory = Path(settings.dry_run_output).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}{suffix}").write_bytes(payload)
    LOGGER.info("vertical preview kind=%s status=written", name)


class VerticalRepository(Protocol):
    def claim(self, **kwargs: object) -> VerticalClaim: ...

    def upload_story(
        self, *, card: VerticalCard, jpeg: bytes
    ) -> TemporaryAsset: ...

    def upload_reel(
        self, *, package: ReelPackage, mp4: bytes
    ) -> TemporaryAsset: ...

    def begin_remote_delivery(self, **kwargs: object) -> None: ...

    def complete(self, **kwargs: object) -> None: ...

    def delete_temporary(self, asset: TemporaryAsset) -> None: ...


class VerticalTransport(Protocol):
    def publish_instagram_story(
        self, *, image_url: str, settings: MetaSettings
    ) -> VerticalDelivery: ...

    def publish_instagram_reel(
        self, *, video_url: str, settings: MetaSettings
    ) -> VerticalDelivery: ...

    def publish_facebook_reel(
        self,
        *,
        mp4: bytes,
        settings: MetaSettings,
        description: str,
    ) -> VerticalDelivery: ...


class ReelRenderer(Protocol):
    def render(self, frames: Sequence[bytes]) -> bytes: ...


class TelegramTransport(Protocol):
    def __call__(self, destination: TelegramDestination, text: str) -> None: ...


def _record_failure(
    card: VerticalCard | ReelPackage,
    *,
    repository: VerticalRepository,
    attempt_id: str,
    error: str,
    destination: str = "instagram_story",
) -> bool:
    try:
        repository.complete(
            package=card,
            destination=destination,
            attempt_id=attempt_id,
            success=False,
            receipt="",
            error=error,
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "vertical completion status=failed kind=%s exception=%s",
            card.kind,
            type(exc).__name__,
        )
        return False


def _publish_story(
    card: VerticalCard,
    *,
    repository: VerticalRepository,
    transport: VerticalTransport,
    settings: MetaSettings,
    renderer: Callable[[VerticalCard], bytes],
    on_remote_success: Callable[[str], None] | None = None,
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
        try:
            jpeg = renderer(card)
            asset = repository.upload_story(card=card, jpeg=jpeg)
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

        try:
            repository.begin_remote_delivery(
                package=card,
                destination="instagram_story",
                attempt_id=claim.attempt_id,
            )
        except Exception as exc:
            LOGGER.warning(
                "vertical remote_transition status=failed kind=%s exception=%s",
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

        try:
            delivery = transport.publish_instagram_story(
                image_url=asset.url,
                settings=settings,
            )
        except Exception as exc:
            LOGGER.warning(
                "vertical remote status=ambiguous kind=%s exception=%s",
                card.kind,
                type(exc).__name__,
            )
            return "pending_review"
        if (
            not isinstance(delivery, VerticalDelivery)
            or delivery.destination != "instagram_story"
        ):
            LOGGER.warning("vertical remote status=ambiguous kind=%s", card.kind)
            return "pending_review"
        if delivery.status == "pending_review":
            return "pending_review"
        if delivery.status == "success":
            if on_remote_success is not None:
                try:
                    on_remote_success(delivery.receipt)
                except Exception as exc:
                    LOGGER.warning(
                        "vertical receipt status=ambiguous kind=%s exception=%s",
                        card.kind,
                        type(exc).__name__,
                    )
                    return "pending_review"
            try:
                repository.complete(
                    package=card,
                    destination="instagram_story",
                    attempt_id=claim.attempt_id,
                    success=True,
                    receipt=delivery.receipt,
                    error="",
                )
            except Exception as exc:
                LOGGER.warning(
                    "vertical completion status=ambiguous kind=%s exception=%s",
                    card.kind,
                    type(exc).__name__,
                )
                return "pending_review"
            return "success"

        persisted = _record_failure(
            card,
            repository=repository,
            attempt_id=claim.attempt_id,
            error=delivery.status,
        )
        return delivery.status if persisted else "pending_review"
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
                jpeg = renderer(card)
                _write_dry_run_preview(
                    settings,
                    name=card.kind,
                    suffix=".jpg",
                    payload=jpeg,
                )
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


def publish_daily_reel(
    report: ResultReport,
    *,
    frames: Sequence[bytes],
    repository: VerticalRepository,
    renderer: ReelRenderer,
    transport: VerticalTransport,
    settings: MetaSettings,
) -> dict[str, str]:
    """Render once and deliver one daily reel to independent destinations."""

    package = build_daily_reel_package(report)
    destinations = ("instagram_reel", "facebook_reel")
    if settings.dry_run:
        try:
            mp4 = renderer.render(frames)
            _write_dry_run_preview(
                settings,
                name=package.kind,
                suffix=".mp4",
                payload=mp4,
            )
        except Exception as exc:
            LOGGER.warning(
                "vertical render status=failed kind=daily_results_reel exception=%s",
                type(exc).__name__,
            )
            return {destination: "delivery_failed" for destination in destinations}
        return {destination: "dry_run" for destination in destinations}

    outcomes: dict[str, str] = {}
    active: dict[str, VerticalClaim] = {}
    for destination in destinations:
        try:
            claim = repository.claim(
                batch_id=package.batch_id,
                portfolio_date=package.portfolio_date,
                content_kind=package.kind,
                destination=destination,
                digest=package.digest,
                template_version=package.template_version,
            )
        except Exception as exc:
            LOGGER.warning(
                "vertical claim status=failed kind=daily_results_reel "
                "destination=%s exception=%s",
                destination,
                type(exc).__name__,
            )
            outcomes[destination] = "delivery_failed"
            continue
        if claim.state == "claimed":
            if claim.attempt_id is None:
                outcomes[destination] = "delivery_failed"
            else:
                active[destination] = claim
        else:
            outcomes[destination] = claim.state
    if not active:
        return outcomes

    asset: TemporaryAsset | None = None
    try:
        try:
            mp4 = renderer.render(frames)
            asset = repository.upload_reel(package=package, mp4=mp4)
        except Exception as exc:
            LOGGER.warning(
                "vertical delivery status=failed kind=daily_results_reel exception=%s",
                type(exc).__name__,
            )
            for destination, claim in active.items():
                persisted = _record_failure(
                    package,
                    repository=repository,
                    attempt_id=claim.attempt_id or "",
                    error="delivery_failed",
                    destination=destination,
                )
                outcomes[destination] = (
                    "delivery_failed" if persisted else "pending_review"
                )
            return outcomes

        for destination, claim in active.items():
            attempt_id = claim.attempt_id
            if attempt_id is None:
                outcomes[destination] = "delivery_failed"
                continue
            try:
                repository.begin_remote_delivery(
                    package=package,
                    destination=destination,
                    attempt_id=attempt_id,
                )
            except Exception as exc:
                LOGGER.warning(
                    "vertical remote_transition status=failed "
                    "kind=daily_results_reel destination=%s exception=%s",
                    destination,
                    type(exc).__name__,
                )
                persisted = _record_failure(
                    package,
                    repository=repository,
                    attempt_id=attempt_id,
                    error="delivery_failed",
                    destination=destination,
                )
                outcomes[destination] = (
                    "delivery_failed" if persisted else "pending_review"
                )
                continue
            try:
                if destination == "instagram_reel":
                    delivery = transport.publish_instagram_reel(
                        video_url=asset.url,
                        settings=settings,
                    )
                else:
                    delivery = transport.publish_facebook_reel(
                        mp4=mp4,
                        settings=settings,
                        description=package.caption,
                    )
            except Exception as exc:
                LOGGER.warning(
                    "vertical remote status=ambiguous kind=daily_results_reel "
                    "destination=%s exception=%s",
                    destination,
                    type(exc).__name__,
                )
                outcomes[destination] = "pending_review"
                continue
            if (
                not isinstance(delivery, VerticalDelivery)
                or delivery.destination != destination
            ):
                outcomes[destination] = "pending_review"
                continue
            if delivery.status == "pending_review":
                outcomes[destination] = "pending_review"
                continue
            if delivery.status == "success":
                try:
                    repository.complete(
                        package=package,
                        destination=destination,
                        attempt_id=attempt_id,
                        success=True,
                        receipt=delivery.receipt,
                        error="",
                    )
                except Exception as exc:
                    LOGGER.warning(
                        "vertical completion status=ambiguous "
                        "kind=daily_results_reel destination=%s exception=%s",
                        destination,
                        type(exc).__name__,
                    )
                    outcomes[destination] = "pending_review"
                else:
                    outcomes[destination] = "success"
                continue
            persisted = _record_failure(
                package,
                repository=repository,
                attempt_id=attempt_id,
                error=delivery.status,
                destination=destination,
            )
            outcomes[destination] = delivery.status if persisted else "pending_review"
        return outcomes
    finally:
        if asset is not None:
            try:
                repository.delete_temporary(asset)
            except RuntimeError as exc:
                LOGGER.warning(
                    "vertical cleanup status=failed kind=daily_results_reel "
                    "exception=%s",
                    type(exc).__name__,
                )


def frames_for_daily_reel(
    report: ResultReport,
    *,
    evidence: Sequence[MatchedEvidence],
) -> tuple[bytes, ...]:
    """Render truthful source frames for one final daily reel."""

    summary = build_final_results_story(report)
    winner = next(
        (row for row in report.rows if row["estado"] == "ganado"),
        None,
    )
    if winner is None:
        raise ValueError("daily reel requires at least one verified win")
    detail = build_verified_result_story(report, pick_id=int(winner["id"]))
    closing = build_reel_cta_story(report)
    frames = [render_story_jpeg(summary), render_story_jpeg(detail)]
    if evidence:
        selected = sorted(
            evidence,
            key=lambda item: (-len(item.pick_ids), item.evidence_id),
        )[0]
        frames.append(
            render_ticket_evidence_jpeg(
                selected.jpeg,
                observed_label=f"{report.portfolio_date} · CDMX",
            )
        )
    frames.append(render_story_jpeg(closing))
    return tuple(frames)


def publish_daily_reel_from_runtime(
    report: ResultReport,
    *,
    evidence: Sequence[MatchedEvidence],
    repository: VerticalRepository,
    transport: VerticalTransport,
    settings: MetaSettings,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Resolve runner media tools and publish one daily reel."""

    values = _runtime_values(environ)
    configured_ffmpeg = values.get("FFMPEG_PATH", "")
    configured_ffprobe = values.get("FFPROBE_PATH", "")
    if not isinstance(configured_ffmpeg, str) or not isinstance(
        configured_ffprobe,
        str,
    ):
        raise ValueError("local media tool paths are invalid")
    ffmpeg = configured_ffmpeg or shutil.which("ffmpeg") or ""
    ffprobe = configured_ffprobe or shutil.which("ffprobe") or ""
    renderer = LocalReelRenderer(ffmpeg=ffmpeg, ffprobe=ffprobe)
    frames = frames_for_daily_reel(report, evidence=evidence)
    return publish_daily_reel(
        report,
        frames=frames,
        repository=repository,
        renderer=renderer,
        transport=transport,
        settings=settings,
    )


def publish_final_stories(
    report: ResultReport,
    *,
    evidence: Sequence[MatchedEvidence],
    repository: VerticalRepository,
    transport: VerticalTransport,
    settings: MetaSettings,
    renderer: Callable[[VerticalCard], bytes],
    evidence_renderer: Callable[[bytes, VerticalCard], bytes],
    evidence_receipt_recorder: (
        Callable[[MatchedEvidence, str], None] | None
    ) = None,
) -> dict[str, str]:
    """Publish final results followed by one validated original ticket."""

    if (
        not isinstance(report, ResultReport)
        or report.kind != "final"
        or not report.terminal
    ):
        raise ValueError("final stories require a final report")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise ValueError("final story evidence must be a sequence")
    if any(not isinstance(item, MatchedEvidence) for item in evidence):
        raise ValueError("final story evidence is invalid")

    def publish(
        card: VerticalCard,
        render: Callable[[VerticalCard], bytes],
        *,
        on_remote_success: Callable[[str], None] | None = None,
    ) -> str:
        if settings.dry_run:
            try:
                jpeg = render(card)
                _write_dry_run_preview(
                    settings,
                    name=card.kind,
                    suffix=".jpg",
                    payload=jpeg,
                )
            except Exception as exc:
                LOGGER.warning(
                    "vertical render status=failed kind=%s exception=%s",
                    card.kind,
                    type(exc).__name__,
                )
                return "delivery_failed"
            return "dry_run"
        return _publish_story(
            card,
            repository=repository,
            transport=transport,
            settings=settings,
            renderer=render,
            on_remote_success=on_remote_success,
        )

    outcomes: dict[str, str] = {}
    summary = build_final_results_story(report)
    outcomes[summary.kind] = publish(summary, renderer)
    if not evidence:
        return outcomes

    item = sorted(
        evidence,
        key=lambda value: (-len(value.pick_ids), value.evidence_id),
    )[0]
    if len(item.pick_ids) == 1:
        matching_rows = tuple(
            row for row in report.rows if int(row["id"]) == item.pick_ids[0]
        )
        if len(matching_rows) == 1 and matching_rows[0]["estado"] == "ganado":
            verified = build_verified_result_story(
                report,
                pick_id=item.pick_ids[0],
            )
            outcomes[verified.kind] = publish(verified, renderer)
    evidence_card = build_ticket_evidence_card(
        report,
        evidence_id=item.evidence_id,
        media_digest=item.media_digest,
    )
    outcomes[evidence_card.kind] = publish(
        evidence_card,
        lambda card: evidence_renderer(item.jpeg, card),
        on_remote_success=(
            None
            if evidence_receipt_recorder is None
            else lambda receipt: evidence_receipt_recorder(item, receipt)
        ),
    )
    return outcomes


def publish_final_stories_from_runtime(
    report: ResultReport,
    *,
    environ: Mapping[str, str] | None = None,
    include_stories: bool = True,
    include_reels: bool = True,
) -> dict[str, str]:
    """Build runtime adapters and publish one final vertical package."""

    if type(include_stories) is not bool or type(include_reels) is not bool:
        raise ValueError("vertical publication scope is invalid")
    if not include_stories and not include_reels:
        raise ValueError("vertical publication scope is empty")

    values = _runtime_values(environ)
    supabase_url = _required_runtime_string(values, "SUPABASE_URL")
    service_role_key = _required_runtime_string(
        values,
        "SUPABASE_SERVICE_ROLE_KEY",
    )
    settings = MetaSettings.from_mapping(values)
    repository = SupabaseVerticalRepository(
        url=supabase_url,
        service_role_key=service_role_key,
    )
    matched: tuple[MatchedEvidence, ...] = ()
    story_evidence: tuple[MatchedEvidence, ...] = ()
    evidence_repository: SupabaseTicketEvidenceRepository | None = None
    telegram_token = _required_runtime_string(values, "TELEGRAM_BOT_TOKEN")
    raw_admin_id = _required_runtime_string(values, "TELEGRAM_ADMIN_ID")
    admin_chat_id = 0
    if not raw_admin_id:
        raw_admin_id = _required_runtime_string(values, "TELEGRAM_CHAT_ID")
    if telegram_token and raw_admin_id:
        try:
            if re.fullmatch(r"-?[0-9]{1,19}", raw_admin_id) is None:
                raise ValueError("Telegram admin identity is invalid")
            admin_chat_id = int(raw_admin_id)
            evidence_repository = SupabaseTicketEvidenceRepository(
                create_client(supabase_url, service_role_key),
                admin_chat_id=admin_chat_id,
            )
            collected = collect_matched_evidence(
                report,
                repository=evidence_repository,
                fetcher=TelegramTicketFetcher(telegram_token),
                inspector=EvidenceInspector(ocr=tesseract_ocr),
            )
            matched = tuple(collected)
            if include_stories:
                story_evidence = tuple(
                    item
                    for item in matched
                    if not evidence_repository.is_consumed(
                        evidence_key=item.evidence_id,
                        report=report,
                    )
                )
        except Exception as exc:
            LOGGER.warning(
                "ticket evidence status=pending_review exception=%s",
                type(exc).__name__,
            )
    meta_transport = VerticalMetaHttpTransport()
    outcomes: dict[str, str] = {}
    if include_stories:
        outcomes.update(
            publish_final_stories(
                report,
                evidence=story_evidence,
                repository=repository,
                transport=meta_transport,
                settings=settings,
                renderer=render_story_jpeg,
                evidence_renderer=lambda jpeg, card: render_ticket_evidence_jpeg(
                    jpeg,
                    observed_label=f"{card.portfolio_date} · CDMX",
                ),
                evidence_receipt_recorder=(
                    None
                    if evidence_repository is None
                    else lambda item, receipt: evidence_repository.record_story_receipt(
                        evidence_key=item.evidence_id,
                        report=report,
                        receipt=receipt,
                    )
                ),
            )
        )
    if include_reels:
        try:
            reel_outcomes = publish_daily_reel_from_runtime(
                report,
                evidence=matched,
                repository=repository,
                transport=meta_transport,
                settings=settings,
                environ=(None if environ is None else dict(environ)),
            )
        except Exception as exc:
            LOGGER.warning(
                "vertical reel status=failed exception=%s",
                type(exc).__name__,
            )
            reel_outcomes = {
                "instagram_reel": "media_invalid",
                "facebook_reel": "media_invalid",
            }
        outcomes.update(reel_outcomes)
    if not settings.dry_run and telegram_token and admin_chat_id:
        try:
            notify_vertical_failures(
                outcomes,
                telegram=TelegramHttpTransport(telegram_token),
                admin_chat_id=str(admin_chat_id),
            )
        except Exception as exc:
            LOGGER.warning(
                "vertical alert status=failed exception=%s",
                type(exc).__name__,
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


def require_healthy_vertical_outcomes(
    outcomes: Mapping[str, str],
    *,
    settings: MetaSettings,
) -> None:
    """Raise one safe error for incomplete configured vertical delivery."""

    safe_outcomes = _validated_outcomes(outcomes)
    if _exit_code(safe_outcomes, settings=settings) == 0:
        return
    failures = ", ".join(
        f"{name}={status}"
        for name, status in sorted(safe_outcomes.items())
        if status not in _HEALTHY_STATUSES
    )
    raise RuntimeError(f"vertical delivery incomplete: {failures}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish Rey Taco vertical media")
    parser.add_argument(
        "--mode",
        choices=("pre-event", "final", "recover"),
        required=True,
    )
    publication = parser.add_mutually_exclusive_group(required=True)
    publication.add_argument(
        "--dry-run",
        action="store_true",
        help="render locally without contacting Meta",
    )
    publication.add_argument(
        "--live",
        action="store_true",
        help="allow the configured Meta publication",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--stories-only", action="store_true")
    scope.add_argument("--reel-only", action="store_true")
    return parser


def _run_final_mode(
    values: Mapping[str, object],
    *,
    settings: MetaSettings,
    include_stories: bool,
    include_reels: bool,
) -> int:
    supabase_url = _required_runtime_string(values, "SUPABASE_URL")
    service_role_key = _required_runtime_string(
        values,
        "SUPABASE_SERVICE_ROLE_KEY",
    )
    repository = SupabaseResultReportRepository(
        url=supabase_url,
        service_role_key=service_role_key,
    )
    raw_date = values.get("DAILY_PORTFOLIO_DATE", "")
    if not isinstance(raw_date, str):
        raise ValueError("DAILY_PORTFOLIO_DATE must be a canonical date")
    requested_date = _portfolio_date(values) if raw_date else ""
    found = False
    for rows in repository.batches():
        try:
            report = build_result_report(rows, kind="final")
        except ValueError:
            continue
        if requested_date and report.portfolio_date != requested_date:
            continue
        found = True
        outcomes = publish_final_stories_from_runtime(
            report,
            environ=cast(Mapping[str, str], values),
            include_stories=include_stories,
            include_reels=include_reels,
        )
        safe_outcomes = _validated_outcomes(outcomes)
        for name, status in safe_outcomes.items():
            LOGGER.info("vertical kind=%s status=%s", name, status)
        require_healthy_vertical_outcomes(safe_outcomes, settings=settings)
    if not found:
        LOGGER.info("vertical mode=final report=no_final_report")
    return 0


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run the pre-event publisher and return a safe process exit code."""

    try:
        arguments = _parser().parse_args(argv)
        values = dict(_runtime_values(environ))
        if arguments.mode == "pre-event" and (
            arguments.stories_only or arguments.reel_only
        ):
            raise ValueError("pre-event mode does not accept final media scope")
        values["META_DRY_RUN"] = "true" if arguments.dry_run else "false"
        vertical_output = values.get("VERTICAL_DRY_RUN_OUTPUT", "")
        if vertical_output:
            values["META_DRY_RUN_OUTPUT"] = vertical_output
        settings = MetaSettings.from_mapping(values)
        if arguments.mode in {"final", "recover"}:
            return _run_final_mode(
                values,
                settings=settings,
                include_stories=not arguments.reel_only,
                include_reels=not arguments.stories_only,
            )
        portfolio_date = _portfolio_date(values)
        run_key = resolve_run_key(values)
        supabase_url = _required_runtime_string(values, "SUPABASE_URL")
        service_role_key = _required_runtime_string(
            values, "SUPABASE_SERVICE_ROLE_KEY"
        )
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

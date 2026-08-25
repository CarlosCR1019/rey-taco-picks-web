from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
from typing import Callable, cast

import pytest

import backend.vertical_publisher as vertical_publisher
from backend.social_poster import MetaSettings
from backend.social_repository import MetaSocialBatch
from backend.result_reporting import build_result_report
from backend.telegram_publisher import TelegramDestination
from backend.ticket_evidence import MatchedEvidence
from backend.vertical_content import VerticalCard, build_public_pick_story
from backend.vertical_meta import VerticalDelivery
from backend.vertical_publisher import (
    frames_for_daily_reel,
    notify_vertical_failures,
    publish_daily_reel,
    publish_final_stories,
    publish_pre_event_stories,
)
from backend.vertical_repository import TemporaryAsset, VerticalClaim
from tests.test_social_poster import INSTAGRAM_ID, TOKEN, batch
from tests.test_result_reporting import rows_with_states


PORTFOLIO_DATE = "2026-08-24"
ATTEMPT_ID = "33333333-3333-4333-8333-333333333333"


def configured_settings(**overrides: object) -> MetaSettings:
    values: dict[str, object] = {
        "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
        "IG_USER_ID": INSTAGRAM_ID,
    }
    values.update(overrides)
    return MetaSettings.from_mapping(values)


@dataclass(frozen=True)
class ClaimCall:
    batch_id: str
    portfolio_date: str
    kind: str
    destination: str
    digest: str
    template_version: int


class FakeStoryRepository:
    def __init__(self) -> None:
        self.states: dict[str, str] = {}
        self.claim_calls: list[ClaimCall] = []
        self.uploaded_kinds: list[str] = []
        self.remote_started_kinds: list[str] = []
        self.complete_calls: list[dict[str, object]] = []
        self.deleted_kinds: list[str] = []
        self.cleanup_error = False
        self.begin_error = False
        self.complete_error = False

    def claim(self, **kwargs: object) -> VerticalClaim:
        kind = cast(str, kwargs["content_kind"])
        self.claim_calls.append(
            ClaimCall(
                batch_id=cast(str, kwargs["batch_id"]),
                portfolio_date=cast(str, kwargs["portfolio_date"]),
                kind=kind,
                destination=cast(str, kwargs["destination"]),
                digest=cast(str, kwargs["digest"]),
                template_version=cast(int, kwargs["template_version"]),
            )
        )
        state = self.states.get(kind, "claimed")
        if state == "pending_review":
            state = "ambiguous"
        return VerticalClaim(
            cast(object, state),  # type: ignore[arg-type]
            ATTEMPT_ID if state == "claimed" else None,
        )

    def upload_story(self, *, card: VerticalCard, jpeg: bytes) -> TemporaryAsset:
        assert jpeg == f"jpeg:{card.kind}".encode()
        self.uploaded_kinds.append(card.kind)
        return TemporaryAsset(
            f"stories/{card.portfolio_date}/{card.kind}-{card.digest}.jpg",
            (
                "https://project.supabase.co/storage/v1/object/public/"
                f"social-vertical/stories/{card.portfolio_date}/"
                f"{card.kind}-{card.digest}.jpg"
            ),
            "image/jpeg",
        )

    def begin_remote_delivery(self, **kwargs: object) -> None:
        card = cast(VerticalCard, kwargs["package"])
        self.remote_started_kinds.append(card.kind)
        if self.begin_error:
            raise RuntimeError("raw begin response secret")
        self.states[card.kind] = "pending_review"

    def complete(self, **kwargs: object) -> None:
        self.complete_calls.append(dict(kwargs))
        if self.complete_error:
            raise RuntimeError("raw completion response secret")
        card = cast(VerticalCard, kwargs["package"])
        self.states[card.kind] = "complete" if kwargs["success"] else "failed"

    def delete_temporary(self, asset: TemporaryAsset) -> None:
        kind = asset.object_key.split("/")[-1].split("-")[0]
        self.deleted_kinds.append(kind)
        if self.cleanup_error:
            raise RuntimeError("raw storage secret")


class FakeMeta:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.statuses: dict[str, str] = {}

    def publish_instagram_story(
        self, *, image_url: str, settings: MetaSettings
    ) -> VerticalDelivery:
        kind = image_url.split("/")[-1].split("-")[0]
        self.calls.append((kind, "instagram_story"))
        status = self.statuses.get(kind, "success")
        return VerticalDelivery(
            "instagram_story",
            cast(object, status),  # type: ignore[arg-type]
            f"receipt_{kind}" if status == "success" else "",
        )


class FakeTelegram:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[TelegramDestination, str]] = []

    @property
    def messages(self) -> list[str]:
        return [text for _, text in self.calls]

    def __call__(self, destination: TelegramDestination, text: str) -> None:
        self.calls.append((destination, text))
        if self.fail:
            raise RuntimeError("raw telegram secret")


def render(card: VerticalCard) -> bytes:
    return f"jpeg:{card.kind}".encode()


def final_report():
    return build_result_report(rows_with_states(*(["ganado"] * 6)), kind="final")


def evidence() -> MatchedEvidence:
    return MatchedEvidence(
        "unique-photo-1",
        "5329224423",
        "c" * 64,
        (1,),
        b"original-ticket-jpeg",
    )


def test_final_result_publishes_summary_then_verified_pick_and_original_evidence() -> None:
    repository = FakeStoryRepository()
    meta = FakeMeta()
    evidence_render_calls: list[tuple[bytes, VerticalCard]] = []
    evidence_receipts: list[tuple[MatchedEvidence, str]] = []

    result = publish_final_stories(
        final_report(),
        evidence=(evidence(),),
        repository=repository,
        transport=meta,
        settings=configured_settings(),
        renderer=render,
        evidence_renderer=lambda jpeg, card: evidence_render_calls.append(
            (jpeg, card)
        )
        or render(card),
        evidence_receipt_recorder=lambda item, receipt: evidence_receipts.append(
            (item, receipt)
        ),
    )

    assert list(result) == [
        "final_results_story",
        "verified_result_story",
        "ticket_evidence_story",
    ]
    assert list(result.values()) == ["success", "success", "success"]
    assert [call.kind for call in repository.claim_calls] == list(result)
    assert [kind for kind, _ in meta.calls] == list(result)
    assert evidence_render_calls == [
        (
            b"original-ticket-jpeg",
            next(
                call
                for call in repository.complete_calls
                if cast(VerticalCard, call["package"]).kind
                == "ticket_evidence_story"
            )["package"],
        )
    ]
    assert evidence_receipts == [
        (evidence(), "receipt_ticket_evidence_story")
    ]


def test_evidence_receipt_failure_stays_pending_and_never_completes_delivery() -> None:
    repository = FakeStoryRepository()

    result = publish_final_stories(
        final_report(),
        evidence=(evidence(),),
        repository=repository,
        transport=FakeMeta(),
        settings=configured_settings(),
        renderer=render,
        evidence_renderer=lambda _jpeg, card: render(card),
        evidence_receipt_recorder=lambda _item, _receipt: (_ for _ in ()).throw(
            RuntimeError("raw database secret")
        ),
    )

    assert result["ticket_evidence_story"] == "pending_review"
    completed_kinds = [
        cast(VerticalCard, call["package"]).kind
        for call in repository.complete_calls
    ]
    assert "ticket_evidence_story" not in completed_kinds


def test_missing_evidence_does_not_block_final_result_summary() -> None:
    result = publish_final_stories(
        final_report(),
        evidence=(),
        repository=FakeStoryRepository(),
        transport=FakeMeta(),
        settings=configured_settings(),
        renderer=render,
        evidence_renderer=lambda _jpeg, card: render(card),
    )

    assert result == {"final_results_story": "success"}


def test_final_runtime_collects_evidence_and_uses_original_ticket_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}
    client = object()
    vertical_repository = object()
    class RuntimeEvidenceRepository:
        def __init__(self) -> None:
            self.consumed_calls: list[tuple[str, object]] = []
            self.receipt_calls: list[tuple[str, object, str]] = []

        def is_consumed(self, *, evidence_key: str, report: object) -> bool:
            self.consumed_calls.append((evidence_key, report))
            return False

        def record_story_receipt(
            self,
            *,
            evidence_key: str,
            report: object,
            receipt: str,
        ) -> None:
            self.receipt_calls.append((evidence_key, report, receipt))

    evidence_repository = RuntimeEvidenceRepository()
    meta = object()

    monkeypatch.setattr(
        vertical_publisher,
        "create_client",
        lambda url, key: observed.update(client_args=(url, key)) or client,
    )
    monkeypatch.setattr(
        vertical_publisher,
        "SupabaseVerticalRepository",
        lambda **kwargs: observed.update(vertical_args=kwargs) or vertical_repository,
    )
    monkeypatch.setattr(
        vertical_publisher,
        "SupabaseTicketEvidenceRepository",
        lambda value, *, admin_chat_id: observed.update(
            evidence_args=(value, admin_chat_id)
        )
        or evidence_repository,
    )
    monkeypatch.setattr(vertical_publisher, "VerticalMetaHttpTransport", lambda: meta)
    monkeypatch.setattr(
        vertical_publisher,
        "collect_matched_evidence",
        lambda report, **kwargs: observed.update(
            collection=(report, kwargs)
        )
        or (evidence(),),
    )

    def publish(report, **kwargs):
        observed["publish"] = (report, kwargs)
        return {"final_results_story": "success"}

    monkeypatch.setattr(vertical_publisher, "publish_final_stories", publish)
    monkeypatch.setattr(
        vertical_publisher,
        "publish_daily_reel_from_runtime",
        lambda report, **kwargs: observed.update(reel=(report, kwargs))
        or {
            "instagram_reel": "success",
            "facebook_reel": "success",
        },
    )

    report = final_report()
    result = vertical_publisher.publish_final_stories_from_runtime(
        report,
        environ=cli_values(
            TELEGRAM_ADMIN_ID="123456",
            DAILY_PORTFOLIO_DATE=report.portfolio_date,
        ),
    )

    assert result == {
        "final_results_story": "success",
        "instagram_reel": "success",
        "facebook_reel": "success",
    }
    assert observed["client_args"] == (
        "https://project.supabase.co",
        "service-role-secret",
    )
    assert observed["evidence_args"] == (client, 123456)
    publish_report, publish_kwargs = cast(
        tuple[object, dict[str, object]], observed["publish"]
    )
    assert publish_report == report
    assert publish_kwargs["evidence"] == (evidence(),)
    assert evidence_repository.consumed_calls == [
        ("unique-photo-1", report)
    ]
    assert publish_kwargs["repository"] is vertical_repository
    assert publish_kwargs["transport"] is meta
    evidence_renderer = cast(
        Callable[[bytes, VerticalCard], bytes], publish_kwargs["evidence_renderer"]
    )
    monkeypatch.setattr(
        vertical_publisher,
        "render_ticket_evidence_jpeg",
        lambda jpeg, observed_label: observed.update(
            rendered=(jpeg, observed_label)
        )
        or b"rendered",
    )
    card = build_public_pick_story(batch(), portfolio_date=PORTFOLIO_DATE)
    assert evidence_renderer(b"original", card) == b"rendered"
    assert observed["rendered"] == (
        b"original",
        "2026-08-24 · CDMX",
    )
    receipt_recorder = cast(
        Callable[[MatchedEvidence, str], None],
        publish_kwargs["evidence_receipt_recorder"],
    )
    receipt_recorder(evidence(), "story_media_1")
    assert evidence_repository.receipt_calls == [
        ("unique-photo-1", report, "story_media_1")
    ]


def test_reel_only_reuses_valid_evidence_even_after_story_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class EvidenceRepository:
        def is_consumed(self, **_kwargs: object) -> bool:
            raise AssertionError("reel-only must not apply the story receipt filter")

    monkeypatch.setattr(vertical_publisher, "create_client", lambda *_args: object())
    monkeypatch.setattr(
        vertical_publisher,
        "SupabaseVerticalRepository",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        vertical_publisher,
        "SupabaseTicketEvidenceRepository",
        lambda *_args, **_kwargs: EvidenceRepository(),
    )
    monkeypatch.setattr(
        vertical_publisher,
        "collect_matched_evidence",
        lambda *_args, **_kwargs: (evidence(),),
    )
    monkeypatch.setattr(vertical_publisher, "VerticalMetaHttpTransport", object)
    monkeypatch.setattr(
        vertical_publisher,
        "publish_final_stories",
        lambda *_args, **_kwargs: pytest.fail("stories were not requested"),
    )
    monkeypatch.setattr(
        vertical_publisher,
        "publish_daily_reel_from_runtime",
        lambda _report, **kwargs: observed.update(kwargs)
        or {
            "instagram_reel": "success",
            "facebook_reel": "success",
        },
    )

    result = vertical_publisher.publish_final_stories_from_runtime(
        final_report(),
        environ=cli_values(TELEGRAM_ADMIN_ID="123456"),
        include_stories=False,
        include_reels=True,
    )

    assert result == {
        "instagram_reel": "success",
        "facebook_reel": "success",
    }
    assert observed["evidence"] == (evidence(),)


def test_final_runtime_alerts_admin_with_safe_vertical_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    telegram = FakeTelegram()
    monkeypatch.setattr(
        vertical_publisher,
        "SupabaseVerticalRepository",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(vertical_publisher, "create_client", lambda *_args: object())
    monkeypatch.setattr(
        vertical_publisher,
        "SupabaseTicketEvidenceRepository",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        vertical_publisher,
        "collect_matched_evidence",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        vertical_publisher,
        "publish_final_stories",
        lambda *_args, **_kwargs: {
            "final_results_story": "delivery_failed"
        },
    )
    monkeypatch.setattr(
        vertical_publisher,
        "publish_daily_reel_from_runtime",
        lambda *_args, **_kwargs: {
            "instagram_reel": "success",
            "facebook_reel": "success",
        },
    )
    monkeypatch.setattr(
        vertical_publisher,
        "TelegramHttpTransport",
        lambda token: telegram if token == "telegram-secret" else None,
    )

    result = vertical_publisher.publish_final_stories_from_runtime(
        final_report(),
        environ=cli_values(TELEGRAM_ADMIN_ID="123456"),
    )

    assert result == {
        "final_results_story": "delivery_failed",
        "instagram_reel": "success",
        "facebook_reel": "success",
    }
    assert telegram.messages == [
        "⚠️ Rey Taco · contenido vertical incompleto\n"
        "• final_results_story: delivery_failed"
    ]


class FakeReelRepository:
    def __init__(self) -> None:
        self.states = {
            "instagram_reel": "pending",
            "facebook_reel": "pending",
        }
        self.claim_calls: list[str] = []
        self.begin_calls: list[str] = []
        self.complete_calls: list[dict[str, object]] = []
        self.upload_calls = 0
        self.delete_calls = 0

    def claim(self, **kwargs: object) -> VerticalClaim:
        destination = cast(str, kwargs["destination"])
        self.claim_calls.append(destination)
        state = self.states[destination]
        if state == "complete":
            return VerticalClaim("complete", None)
        if state == "pending_review":
            return VerticalClaim("ambiguous", None)
        self.states[destination] = "claimed"
        return VerticalClaim("claimed", ATTEMPT_ID)

    def begin_remote_delivery(self, **kwargs: object) -> None:
        destination = cast(str, kwargs["destination"])
        self.begin_calls.append(destination)
        self.states[destination] = "pending_review"

    def upload_reel(self, **_kwargs: object) -> TemporaryAsset:
        self.upload_calls += 1
        return TemporaryAsset(
            f"reels/{PORTFOLIO_DATE}/daily_results_reel-{'d' * 64}.mp4",
            (
                "https://project.supabase.co/storage/v1/object/public/"
                "social-vertical/reels/2026-08-24/reel.mp4"
            ),
            "video/mp4",
        )

    def complete(self, **kwargs: object) -> None:
        self.complete_calls.append(dict(kwargs))
        destination = cast(str, kwargs["destination"])
        self.states[destination] = "complete" if kwargs["success"] else "failed"

    def delete_temporary(self, _asset: TemporaryAsset) -> None:
        self.delete_calls += 1


class FakeReelRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, ...]] = []

    def render(self, frames: tuple[bytes, ...]) -> bytes:
        self.calls.append(frames)
        return REEL_BYTES


class FakeReelMeta:
    def __init__(self) -> None:
        self.instagram_calls: list[str] = []
        self.facebook_calls: list[bytes] = []

    def publish_instagram_reel(self, *, video_url: str, settings: MetaSettings):
        self.instagram_calls.append(video_url)
        return VerticalDelivery("instagram_reel", "success", "ig-reel")

    def publish_facebook_reel(
        self,
        *,
        mp4: bytes,
        settings: MetaSettings,
        description: str,
    ):
        self.facebook_calls.append(mp4)
        return VerticalDelivery("facebook_reel", "success", "fb-reel")


REEL_BYTES = b"\x00\x00\x00\x18ftypisom" + (b"\x00" * 64)
REEL_FRAMES = (b"frame-1", b"frame-2", b"frame-3")


def test_daily_reel_frames_include_summary_winner_and_cta() -> None:
    frames = frames_for_daily_reel(final_report(), evidence=())

    assert len(frames) == 3
    assert all(frame.startswith(b"\xff\xd8") for frame in frames)
    assert all(frame.endswith(b"\xff\xd9") for frame in frames)


def test_daily_reel_renders_once_and_completes_destinations_independently() -> None:
    repository = FakeReelRepository()
    renderer = FakeReelRenderer()
    meta = FakeReelMeta()

    outcomes = publish_daily_reel(
        final_report(),
        frames=REEL_FRAMES,
        repository=repository,
        renderer=renderer,
        transport=meta,
        settings=configured_settings(FB_PAGE_ID="1311611272037375"),
    )

    assert outcomes == {
        "instagram_reel": "success",
        "facebook_reel": "success",
    }
    assert renderer.calls == [REEL_FRAMES]
    assert repository.upload_calls == 1
    assert repository.begin_calls == ["instagram_reel", "facebook_reel"]
    assert repository.delete_calls == 1


def test_daily_reel_dry_run_writes_local_preview_without_remote_side_effects(
    tmp_path,
) -> None:
    repository = FakeReelRepository()
    renderer = FakeReelRenderer()
    meta = FakeReelMeta()

    outcomes = publish_daily_reel(
        final_report(),
        frames=REEL_FRAMES,
        repository=repository,
        renderer=renderer,
        transport=meta,
        settings=configured_settings(
            META_DRY_RUN="true",
            META_DRY_RUN_OUTPUT=str(tmp_path),
        ),
    )

    assert outcomes == {
        "instagram_reel": "dry_run",
        "facebook_reel": "dry_run",
    }
    assert (tmp_path / "daily_results_reel.mp4").read_bytes() == REEL_BYTES
    assert repository.claim_calls == []
    assert meta.instagram_calls == []
    assert meta.facebook_calls == []


def test_daily_reel_retry_calls_only_failed_facebook_destination() -> None:
    repository = FakeReelRepository()
    repository.states.update(
        instagram_reel="complete",
        facebook_reel="failed",
    )
    renderer = FakeReelRenderer()
    meta = FakeReelMeta()

    outcomes = publish_daily_reel(
        final_report(),
        frames=REEL_FRAMES,
        repository=repository,
        renderer=renderer,
        transport=meta,
        settings=configured_settings(FB_PAGE_ID="1311611272037375"),
    )

    assert outcomes == {
        "instagram_reel": "complete",
        "facebook_reel": "success",
    }
    assert meta.instagram_calls == []
    assert len(meta.facebook_calls) == 1
    assert renderer.calls == [REEL_FRAMES]


def test_daily_reel_records_failed_destination_without_touching_success() -> None:
    repository = FakeReelRepository()
    meta = FakeReelMeta()

    def fail_facebook(**_kwargs: object) -> VerticalDelivery:
        return VerticalDelivery("facebook_reel", "delivery_failed")

    meta.publish_facebook_reel = fail_facebook  # type: ignore[method-assign]

    outcomes = publish_daily_reel(
        final_report(),
        frames=REEL_FRAMES,
        repository=repository,
        renderer=FakeReelRenderer(),
        transport=meta,
        settings=configured_settings(FB_PAGE_ID="1311611272037375"),
    )

    assert outcomes == {
        "instagram_reel": "success",
        "facebook_reel": "delivery_failed",
    }
    failure = next(call for call in repository.complete_calls if not call["success"])
    assert failure["destination"] == "facebook_reel"


def test_second_settled_batch_same_portfolio_date_does_not_render_second_reel() -> None:
    repository = FakeReelRepository()
    renderer = FakeReelRenderer()
    meta = FakeReelMeta()
    first = final_report()
    second = replace(
        first,
        batch_id="22345678-1234-4234-8234-123456789abc",
        digest="e" * 64,
    )
    kwargs = {
        "frames": REEL_FRAMES,
        "repository": repository,
        "renderer": renderer,
        "transport": meta,
        "settings": configured_settings(FB_PAGE_ID="1311611272037375"),
    }

    publish_daily_reel(first, **kwargs)
    outcomes = publish_daily_reel(second, **kwargs)

    assert outcomes == {
        "instagram_reel": "complete",
        "facebook_reel": "complete",
    }
    assert renderer.calls == [REEL_FRAMES]


def test_pre_event_publishes_public_then_teaser_and_records_each() -> None:
    repository = FakeStoryRepository()
    meta = FakeMeta()

    result = publish_pre_event_stories(
        batch=batch(),
        portfolio_date=PORTFOLIO_DATE,
        repository=repository,
        transport=meta,
        settings=configured_settings(),
        renderer=render,
    )

    assert result == {
        "public_pick_story": "success",
        "vip_teaser_story": "success",
    }
    assert [call.kind for call in repository.claim_calls] == [
        "public_pick_story",
        "vip_teaser_story",
    ]
    assert meta.calls == [
        ("public_pick_story", "instagram_story"),
        ("vip_teaser_story", "instagram_story"),
    ]
    assert repository.remote_started_kinds == [
        "public_pick_story",
        "vip_teaser_story",
    ]
    assert [call["success"] for call in repository.complete_calls] == [True, True]
    assert [call["receipt"] for call in repository.complete_calls] == [
        "receipt_public_pick_story",
        "receipt_vip_teaser_story",
    ]
    assert repository.deleted_kinds == [
        "public_pick_story",
        "vip_teaser_story",
    ]


def test_completed_public_story_is_not_rendered_uploaded_or_sent() -> None:
    repository = FakeStoryRepository()
    repository.states["public_pick_story"] = "complete"
    meta = FakeMeta()
    rendered: list[str] = []

    def recording_renderer(card: VerticalCard) -> bytes:
        rendered.append(card.kind)
        return render(card)

    result = publish_pre_event_stories(
        batch=batch(),
        portfolio_date=PORTFOLIO_DATE,
        repository=repository,
        transport=meta,
        settings=configured_settings(),
        renderer=recording_renderer,
    )

    assert result["public_pick_story"] == "complete"
    assert repository.uploaded_kinds == ["vip_teaser_story"]
    assert rendered == ["vip_teaser_story"]
    assert meta.calls == [("vip_teaser_story", "instagram_story")]


def test_failed_public_story_is_completed_cleaned_and_does_not_block_teaser() -> None:
    repository = FakeStoryRepository()
    meta = FakeMeta()
    meta.statuses["public_pick_story"] = "token_invalid"

    result = publish_pre_event_stories(
        batch=batch(),
        portfolio_date=PORTFOLIO_DATE,
        repository=repository,
        transport=meta,
        settings=configured_settings(),
        renderer=render,
    )

    assert result == {
        "public_pick_story": "token_invalid",
        "vip_teaser_story": "success",
    }
    first, second = repository.complete_calls
    assert first["success"] is False
    assert first["error"] == "token_invalid"
    assert first["receipt"] == ""
    assert second["success"] is True
    assert repository.deleted_kinds == [
        "public_pick_story",
        "vip_teaser_story",
    ]


def test_render_exception_records_safe_failure_and_still_attempts_teaser() -> None:
    repository = FakeStoryRepository()
    meta = FakeMeta()

    def failing_public_renderer(card: VerticalCard) -> bytes:
        if card.kind == "public_pick_story":
            raise RuntimeError("raw rendered secret")
        return render(card)

    result = publish_pre_event_stories(
        batch=batch(),
        portfolio_date=PORTFOLIO_DATE,
        repository=repository,
        transport=meta,
        settings=configured_settings(),
        renderer=failing_public_renderer,
    )

    assert result == {
        "public_pick_story": "delivery_failed",
        "vip_teaser_story": "success",
    }
    assert repository.complete_calls[0]["error"] == "delivery_failed"
    assert repository.uploaded_kinds == ["vip_teaser_story"]


def test_remote_transition_failure_never_calls_meta_and_finishes_safely() -> None:
    repository = FakeStoryRepository()
    repository.begin_error = True
    meta = FakeMeta()
    card = build_public_pick_story(batch(), portfolio_date=PORTFOLIO_DATE)

    result = vertical_publisher._publish_story(
        card,
        repository=repository,
        transport=meta,
        settings=configured_settings(),
        renderer=render,
    )

    assert result == "delivery_failed"
    assert repository.remote_started_kinds == ["public_pick_story"]
    assert meta.calls == []
    assert repository.complete_calls == [
        {
            "package": card,
            "destination": "instagram_story",
            "attempt_id": ATTEMPT_ID,
            "success": False,
            "receipt": "",
            "error": "delivery_failed",
        }
    ]


def test_lost_success_completion_never_republishes_or_records_failure() -> None:
    repository = FakeStoryRepository()
    repository.complete_error = True
    meta = FakeMeta()
    card = build_public_pick_story(batch(), portfolio_date=PORTFOLIO_DATE)

    first = vertical_publisher._publish_story(
        card,
        repository=repository,
        transport=meta,
        settings=configured_settings(),
        renderer=render,
    )
    second = vertical_publisher._publish_story(
        card,
        repository=repository,
        transport=meta,
        settings=configured_settings(),
        renderer=render,
    )

    assert first == "pending_review"
    assert second == "ambiguous"
    assert meta.calls == [("public_pick_story", "instagram_story")]
    assert len(repository.complete_calls) == 1
    assert repository.complete_calls[0]["success"] is True
    assert repository.complete_calls[0]["receipt"] == "receipt_public_pick_story"
    assert repository.states["public_pick_story"] == "pending_review"


def test_cleanup_failure_does_not_erase_successful_meta_receipt(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeStoryRepository()
    repository.cleanup_error = True

    with caplog.at_level(logging.WARNING, logger="backend.vertical_publisher"):
        result = publish_pre_event_stories(
            batch=batch(),
            portfolio_date=PORTFOLIO_DATE,
            repository=repository,
            transport=FakeMeta(),
            settings=configured_settings(),
            renderer=render,
        )

    assert result == {
        "public_pick_story": "success",
        "vip_teaser_story": "success",
    }
    assert [call["receipt"] for call in repository.complete_calls] == [
        "receipt_public_pick_story",
        "receipt_vip_teaser_story",
    ]
    assert "cleanup status=failed" in caplog.text
    assert "raw storage secret" not in caplog.text


def test_dry_run_renders_both_cards_without_claim_upload_or_meta() -> None:
    repository = FakeStoryRepository()
    meta = FakeMeta()
    rendered: list[str] = []

    result = publish_pre_event_stories(
        batch=batch(),
        portfolio_date=PORTFOLIO_DATE,
        repository=repository,
        transport=meta,
        settings=configured_settings(META_DRY_RUN="true"),
        renderer=lambda card: rendered.append(card.kind) or render(card),
    )

    assert result == {
        "public_pick_story": "dry_run",
        "vip_teaser_story": "dry_run",
    }
    assert rendered == ["public_pick_story", "vip_teaser_story"]
    assert repository.claim_calls == []
    assert repository.uploaded_kinds == []
    assert meta.calls == []


def test_story_dry_run_writes_reviewable_jpegs_locally(tmp_path) -> None:
    repository = FakeStoryRepository()
    meta = FakeMeta()

    outcomes = publish_pre_event_stories(
        batch=batch(),
        portfolio_date=PORTFOLIO_DATE,
        repository=repository,
        transport=meta,
        settings=configured_settings(
            META_DRY_RUN="true",
            META_DRY_RUN_OUTPUT=str(tmp_path),
        ),
        renderer=vertical_publisher.render_story_jpeg,
    )

    assert outcomes == {
        "public_pick_story": "dry_run",
        "vip_teaser_story": "dry_run",
    }
    for kind in outcomes:
        preview = (tmp_path / f"{kind}.jpg").read_bytes()
        assert preview.startswith(b"\xff\xd8")
        assert preview.endswith(b"\xff\xd9")
    assert repository.claim_calls == []
    assert meta.calls == []


def test_dry_run_render_failure_returns_nonzero() -> None:
    settings = configured_settings(META_DRY_RUN="true")

    assert vertical_publisher._exit_code(
        {
            "public_pick_story": "delivery_failed",
            "vip_teaser_story": "dry_run",
        },
        settings=settings,
    ) == 1


def test_incomplete_story_alert_contains_only_safe_kind_and_status() -> None:
    telegram = FakeTelegram()

    notify_vertical_failures(
        {
            "vip_teaser_story": "success",
            "public_pick_story": "delivery_failed",
        },
        telegram=telegram,
        admin_chat_id="123",
    )

    assert telegram.messages == [
        "⚠️ Rey Taco · contenido vertical incompleto\n"
        "• public_pick_story: delivery_failed"
    ]
    assert telegram.calls[0][0] == TelegramDestination("admin", "123", "all")


@pytest.mark.parametrize(
    "outcomes",
    [
        {"unknown": "delivery_failed"},
        {"public_pick_story": "raw secret"},
        {"public_pick_story\nsecret": "delivery_failed"},
    ],
)
def test_alert_rejects_unrecognized_kind_or_status(outcomes: dict[str, str]) -> None:
    telegram = FakeTelegram()

    with pytest.raises(ValueError, match="safe"):
        notify_vertical_failures(outcomes, telegram=telegram, admin_chat_id="123")

    assert telegram.calls == []


class FakeSocialRepository:
    instances: list["FakeSocialRepository"] = []
    exact_batch: MetaSocialBatch | None = batch()

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.get_calls: list[tuple[str, datetime]] = []
        self.__class__.instances.append(self)

    def get_batch(
        self, *, run_key: str, reference_at: datetime
    ) -> MetaSocialBatch | None:
        self.get_calls.append((run_key, reference_at))
        return self.exact_batch


def cli_values(**overrides: str) -> dict[str, str]:
    values = {
        "SCRAPER_RUN_KEY": "residential:123",
        "DAILY_PORTFOLIO_DATE": PORTFOLIO_DATE,
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
        "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
        "IG_USER_ID": INSTAGRAM_ID,
        "META_GRAPH_VERSION": "v26.0",
        "TELEGRAM_BOT_TOKEN": "telegram-secret",
        "TELEGRAM_CHAT_ID": "123",
    }
    values.update(overrides)
    return values


def test_main_loads_same_run_key_batch_and_required_portfolio_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeSocialRepository.instances = []
    FakeSocialRepository.exact_batch = batch()
    vertical_repository = object()
    transport = object()
    observed: dict[str, object] = {}

    def vertical_repository_factory(**kwargs: object) -> object:
        observed["vertical_repository_args"] = kwargs
        return vertical_repository

    def telegram_factory(token: str) -> FakeTelegram:
        observed["telegram_token"] = token
        return FakeTelegram()

    monkeypatch.setattr(
        vertical_publisher, "SupabaseSocialRepository", FakeSocialRepository
    )
    monkeypatch.setattr(
        vertical_publisher,
        "SupabaseVerticalRepository",
        vertical_repository_factory,
    )
    monkeypatch.setattr(
        vertical_publisher,
        "VerticalMetaHttpTransport",
        lambda: transport,
    )
    monkeypatch.setattr(
        vertical_publisher,
        "TelegramHttpTransport",
        telegram_factory,
    )

    def publish_fake(**kwargs: object) -> dict[str, str]:
        observed["publish"] = kwargs
        return {
            "public_pick_story": "success",
            "vip_teaser_story": "complete",
        }

    monkeypatch.setattr(vertical_publisher, "publish_pre_event_stories", publish_fake)

    assert vertical_publisher.main(
        ["--mode", "pre-event", "--live"], cli_values()
    ) == 0

    social_repository = FakeSocialRepository.instances[0]
    assert social_repository.kwargs == {
        "supabase_url": "https://project.supabase.co",
        "service_role_key": "service-role-secret",
    }
    run_key, reference_at = social_repository.get_calls[0]
    assert run_key == "residential:123"
    assert reference_at.tzinfo is timezone.utc
    publish_call = cast(dict[str, object], observed["publish"])
    assert publish_call["batch"] == batch()
    assert publish_call["portfolio_date"] == PORTFOLIO_DATE
    assert observed["vertical_repository_args"] == {
        "url": "https://project.supabase.co",
        "service_role_key": "service-role-secret",
    }
    assert publish_call["repository"] is vertical_repository
    assert publish_call["transport"] is transport
    assert callable(publish_call["renderer"])


def test_main_returns_nonzero_for_configured_incomplete_story_and_alert_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    FakeSocialRepository.instances = []
    FakeSocialRepository.exact_batch = batch()
    telegram = FakeTelegram(fail=True)
    monkeypatch.setattr(
        vertical_publisher, "SupabaseSocialRepository", FakeSocialRepository
    )
    monkeypatch.setattr(
        vertical_publisher, "SupabaseVerticalRepository", lambda **_kwargs: object()
    )
    monkeypatch.setattr(vertical_publisher, "VerticalMetaHttpTransport", object)
    monkeypatch.setattr(
        vertical_publisher, "TelegramHttpTransport", lambda _token: telegram
    )
    monkeypatch.setattr(
        vertical_publisher,
        "publish_pre_event_stories",
        lambda **_kwargs: {
            "public_pick_story": "success",
            "vip_teaser_story": "delivery_failed",
        },
    )

    with caplog.at_level(logging.INFO, logger="backend.vertical_publisher"):
        result = vertical_publisher.main(
            ["--mode", "pre-event", "--live"], cli_values()
        )

    assert result == 1
    assert telegram.messages == [
        "⚠️ Rey Taco · contenido vertical incompleto\n"
        "• vip_teaser_story: delivery_failed"
    ]
    assert "public_pick_story status=success" in caplog.text
    assert "vip_teaser_story status=delivery_failed" in caplog.text
    assert "alert status=failed exception=RuntimeError" in caplog.text
    assert "raw telegram secret" not in caplog.text
    assert TOKEN not in caplog.text


def test_main_dry_run_render_failure_has_no_telegram_side_effect(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    FakeSocialRepository.instances = []
    FakeSocialRepository.exact_batch = batch()
    telegram_factory_calls: list[str] = []

    monkeypatch.setattr(
        vertical_publisher, "SupabaseSocialRepository", FakeSocialRepository
    )
    monkeypatch.setattr(
        vertical_publisher, "SupabaseVerticalRepository", lambda **_kwargs: object()
    )
    monkeypatch.setattr(vertical_publisher, "VerticalMetaHttpTransport", object)
    monkeypatch.setattr(
        vertical_publisher,
        "TelegramHttpTransport",
        lambda token: telegram_factory_calls.append(token) or FakeTelegram(),
    )
    monkeypatch.setattr(
        vertical_publisher,
        "publish_pre_event_stories",
        lambda **_kwargs: {
            "public_pick_story": "delivery_failed",
            "vip_teaser_story": "dry_run",
        },
    )

    with caplog.at_level(logging.INFO, logger="backend.vertical_publisher"):
        result = vertical_publisher.main(
            ["--mode", "pre-event", "--dry-run"],
            cli_values(META_DRY_RUN="false"),
        )

    assert result == 1
    assert telegram_factory_calls == []
    assert "public_pick_story status=delivery_failed" in caplog.text
    assert "vip_teaser_story status=dry_run" in caplog.text
    assert "telegram-secret" not in caplog.text
    assert TOKEN not in caplog.text


@pytest.mark.parametrize(
    "values",
    [
        cli_values(DAILY_PORTFOLIO_DATE=""),
        cli_values(DAILY_PORTFOLIO_DATE="24-08-2026"),
        cli_values(DAILY_PORTFOLIO_DATE="2026-08-24\nsecret"),
    ],
)
def test_main_requires_a_canonical_daily_portfolio_date(
    values: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="backend.vertical_publisher"):
        result = vertical_publisher.main(
            ["--mode", "pre-event", "--live"], values
        )

    assert result == 1
    assert "command=status_failed exception=ValueError" in caplog.text
    assert "secret" not in caplog.text


def test_main_no_exact_batch_is_a_safe_noop(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    FakeSocialRepository.instances = []
    FakeSocialRepository.exact_batch = None
    monkeypatch.setattr(
        vertical_publisher, "SupabaseSocialRepository", FakeSocialRepository
    )

    with caplog.at_level(logging.INFO, logger="backend.vertical_publisher"):
        result = vertical_publisher.main(
            ["--mode", "pre-event", "--live"], cli_values()
        )

    assert result == 0
    assert "batch=no_batch" in caplog.text


@pytest.mark.parametrize("mode", ["final", "recover"])
def test_main_final_modes_load_only_settled_reports_and_use_the_ledger(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[object] = []

    class ResultRepository:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs == {
                "url": "https://project.supabase.co",
                "service_role_key": "service-role-secret",
            }

        def batches(self):
            return (tuple(rows_with_states(*(["ganado"] * 6))),)

    monkeypatch.setattr(
        vertical_publisher,
        "SupabaseResultReportRepository",
        ResultRepository,
    )
    monkeypatch.setattr(
        vertical_publisher,
        "publish_final_stories_from_runtime",
        lambda report, **kwargs: observed.append((report, kwargs))
        or {
            "final_results_story": "complete",
            "instagram_reel": "complete",
            "facebook_reel": "complete",
        },
    )

    assert vertical_publisher.main(
        ["--mode", mode, "--live"], cli_values()
    ) == 0
    assert len(observed) == 1
    report, kwargs = cast(tuple[object, dict[str, object]], observed[0])
    assert report == final_report()
    expected = cli_values()
    expected["META_DRY_RUN"] = "false"
    assert kwargs["environ"] == expected
    assert kwargs["include_stories"] is True
    assert kwargs["include_reels"] is True


def test_main_requires_explicit_live_or_dry_run() -> None:
    with pytest.raises(SystemExit):
        vertical_publisher.main(["--mode", "pre-event"], cli_values())


@pytest.mark.parametrize(
    ("scope", "include_stories", "include_reels"),
    [
        ("--stories-only", True, False),
        ("--reel-only", False, True),
    ],
)
def test_main_final_mode_honors_vertical_scope(
    scope: str,
    include_stories: bool,
    include_reels: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class ResultRepository:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def batches(self):
            return (tuple(rows_with_states(*(["ganado"] * 6))),)

    monkeypatch.setattr(
        vertical_publisher,
        "SupabaseResultReportRepository",
        ResultRepository,
    )

    def publish(report: object, **kwargs: object) -> dict[str, str]:
        observed.update(kwargs)
        return {"final_results_story": "complete"}

    monkeypatch.setattr(
        vertical_publisher,
        "publish_final_stories_from_runtime",
        publish,
    )

    assert vertical_publisher.main(
        ["--mode", "final", "--dry-run", scope],
        cli_values(META_DRY_RUN="false"),
    ) == 0
    assert observed["include_stories"] is include_stories
    assert observed["include_reels"] is include_reels
    runtime = cast(dict[str, str], observed["environ"])
    assert runtime["META_DRY_RUN"] == "true"


def test_pre_event_rejects_final_only_scope(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="backend.vertical_publisher"):
        result = vertical_publisher.main(
            ["--mode", "pre-event", "--dry-run", "--reel-only"],
            cli_values(),
        )

    assert result == 1
    assert "command=status_failed exception=ValueError" in caplog.text

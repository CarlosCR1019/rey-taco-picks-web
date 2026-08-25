from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import cast

import pytest

import backend.vertical_publisher as vertical_publisher
from backend.social_poster import MetaSettings
from backend.social_repository import MetaSocialBatch
from backend.telegram_publisher import TelegramDestination
from backend.vertical_content import VerticalCard, build_public_pick_story
from backend.vertical_meta import VerticalDelivery
from backend.vertical_publisher import (
    notify_vertical_failures,
    publish_pre_event_stories,
)
from backend.vertical_repository import TemporaryAsset, VerticalClaim
from tests.test_social_poster import INSTAGRAM_ID, TOKEN, batch


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
        ["--mode", "pre-event"], cli_values()
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
            ["--mode", "pre-event"], cli_values()
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
            ["--mode", "pre-event"],
            cli_values(META_DRY_RUN="true"),
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
        result = vertical_publisher.main(["--mode", "pre-event"], values)

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
            ["--mode", "pre-event"], cli_values()
        )

    assert result == 0
    assert "batch=no_batch" in caplog.text

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
import logging
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from PIL import Image
import pytest
import requests

import backend.social_poster as social_poster
from backend.social_content import SocialCaptions, SocialContent
from backend.social_poster import (
    MetaDelivery,
    MetaHttpTransport,
    MetaSettings,
    MetaStatus,
)
from backend.social_repository import MetaSocialBatch, SocialRepository


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
RUN_ID = "11111111-1111-4111-8111-111111111111"
BATCH_ID = "22222222-2222-4222-8222-222222222222"
FACEBOOK_ID = "1311611272037375"
INSTAGRAM_ID = "17841441356316454"
TOKEN = "runtime-secret"
IMAGE_URL = (
    "https://project.supabase.co/storage/v1/object/public/social-media/"
    f"daily/{BATCH_ID}/321.jpg"
)


def content(*, is_demo: bool = False) -> SocialContent:
    return SocialContent(
        pick_id="321",
        category="Fútbol",
        event="Equipo Norte vs Equipo Sur",
        selection="Más de 1.5 goles",
        odds_text="1.85",
        schedule="22 ago · 18:00 CDMX",
        observed_at=datetime(2026, 8, 21, 11, 0, tzinfo=timezone.utc),
        starts_at=datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc),
        league="Liga de prueba",
        market="Total de goles",
        risk_label="Riesgo medio",
        evidence_label="Fuente auditada",
        has_value_signal=True,
        is_demo=is_demo,
    )


def batch(*, ledger: dict[str, object] | None = None, is_demo: bool = False) -> MetaSocialBatch:
    return MetaSocialBatch(
        run_id=RUN_ID,
        batch_id=BATCH_ID,
        delivery_status=MappingProxyType(ledger or {}),
        content=content(is_demo=is_demo),
    )


def jpeg_bytes() -> bytes:
    image = Image.new("RGB", (1080, 1080), "#102040")
    output = BytesIO()
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


class FakeResponse:
    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self.payload = payload

    def json(self) -> object:
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.post_responses: list[object] = []
        self.get_responses: list[object] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []
        self.get_calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> object:
        self.post_calls.append((url, kwargs))
        response = self.post_responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get(self, url: str, **kwargs: object) -> object:
        self.get_calls.append((url, kwargs))
        response = self.get_responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def configured_settings(**overrides: str) -> MetaSettings:
    values = {
        "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
        "FB_PAGE_ID": FACEBOOK_ID,
        "IG_USER_ID": INSTAGRAM_ID,
    }
    values.update(overrides)
    return MetaSettings.from_mapping(values)


def test_settings_use_one_system_user_token_and_default_graph_version() -> None:
    settings = MetaSettings.from_mapping(
        {
            "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
            "FB_PAGE_ID": FACEBOOK_ID,
            "IG_USER_ID": INSTAGRAM_ID,
            "FB_PAGE_ACCESS_TOKEN": "legacy-facebook-secret",
            "INSTAGRAM_ACCESS_TOKEN": "legacy-instagram-secret",
        }
    )

    assert settings.graph_version == "v26.0"
    assert settings.token == TOKEN
    assert settings.facebook_page_id == FACEBOOK_ID
    assert settings.instagram_user_id == INSTAGRAM_ID
    assert "legacy" not in repr(settings)
    assert TOKEN not in repr(settings)


def test_settings_ignore_legacy_tokens_when_system_token_is_missing() -> None:
    settings = MetaSettings.from_mapping(
        {
            "FB_PAGE_ACCESS_TOKEN": "legacy-facebook-secret",
            "INSTAGRAM_USER_ACCESS_TOKEN": "legacy-instagram-secret",
            "FB_PAGE_ID": FACEBOOK_ID,
            "IG_USER_ID": INSTAGRAM_ID,
        }
    )

    assert settings.token == ""


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("META_SYSTEM_USER_ACCESS_TOKEN", " unsafe\nsecret"),
        ("FB_PAGE_ID", "not-digits"),
        ("FB_PAGE_ID", "123 "),
        ("IG_USER_ID", "１２３"),
        ("META_GRAPH_VERSION", "26.0"),
        ("META_GRAPH_VERSION", "v26.0/evil"),
    ],
)
def test_settings_reject_unsafe_nonblank_runtime_values(key: str, value: str) -> None:
    values = {
        "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
        "FB_PAGE_ID": FACEBOOK_ID,
        "IG_USER_ID": INSTAGRAM_ID,
    }
    values[key] = value

    with pytest.raises(ValueError):
        MetaSettings.from_mapping(values)


def test_settings_parse_dry_run_without_accepting_ambiguous_values() -> None:
    settings = MetaSettings.from_mapping(
        {
            "META_DRY_RUN": "true",
            "META_DRY_RUN_OUTPUT": "preview.jpg",
        }
    )
    assert settings.dry_run is True
    assert settings.dry_run_output == "preview.jpg"

    with pytest.raises(ValueError, match="META_DRY_RUN"):
        MetaSettings.from_mapping({"META_DRY_RUN": "sometimes"})


@pytest.mark.parametrize(
    "arguments",
    [
        ("secret", FACEBOOK_ID, INSTAGRAM_ID, "v26.0/evil"),
        ("unsafe\u200bsecret", FACEBOOK_ID, INSTAGRAM_ID, "v26.0"),
        ("secret", "１２３", INSTAGRAM_ID, "v26.0"),
        ("secret", FACEBOOK_ID, "123\u2060", "v26.0"),
        (None, FACEBOOK_ID, INSTAGRAM_ID, "v26.0"),
        ("secret", None, INSTAGRAM_ID, "v26.0"),
    ],
)
def test_direct_settings_construction_cannot_bypass_runtime_validation(
    arguments: tuple[object, object, object, object],
) -> None:
    with pytest.raises(ValueError):
        MetaSettings(*arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("META_SYSTEM_USER_ACCESS_TOKEN", "unsafe\u200bsecret"),
        ("SCRAPER_RUN_KEY", "github-run:\u2060123"),
    ],
)
def test_runtime_security_boundaries_reject_unicode_format_controls(
    key: str,
    value: str,
) -> None:
    if key == "META_SYSTEM_USER_ACCESS_TOKEN":
        with pytest.raises(ValueError):
            MetaSettings.from_mapping({key: value})
    else:
        with pytest.raises(ValueError):
            social_poster.resolve_run_key({key: value})


def test_facebook_posts_local_jpeg_with_authorization_header() -> None:
    session = FakeSession()
    session.post_responses = [FakeResponse(payload={"id": "fb_photo:123"})]
    transport = MetaHttpTransport(session=session)
    image = jpeg_bytes()

    result = transport.publish_facebook(
        jpeg=image,
        caption="caption factual",
        settings=configured_settings(),
    )

    assert result == MetaDelivery("facebook", "success", "fb_photo:123")
    assert session.post_calls == [
        (
            f"https://graph.facebook.com/v26.0/{FACEBOOK_ID}/photos",
            {
                "headers": {"Authorization": f"Bearer {TOKEN}"},
                "data": {"message": "caption factual"},
                "files": {"source": ("rey-taco-pick.jpg", image, "image/jpeg")},
                "timeout": 30,
            },
        )
    ]
    assert TOKEN not in session.post_calls[0][0]


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (FakeResponse(400, {"error": {"code": 190, "message": "raw"}}), "token_invalid"),
        (FakeResponse(400, {"error": {"type": "OAuthException"}}), "token_invalid"),
        (FakeResponse(500, {"raw": "provider body"}), "delivery_failed"),
        (FakeResponse(200, ValueError("invalid json raw body")), "delivery_failed"),
        (FakeResponse(200, {}), "delivery_failed"),
        (FakeResponse(200, {"id": "unsafe id!"}), "delivery_failed"),
        (requests.Timeout("raw timeout secret"), "delivery_failed"),
    ],
)
def test_facebook_failures_are_sanitized(
    response: object,
    expected: MetaStatus,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeSession()
    session.post_responses = [response]

    with caplog.at_level(logging.INFO, logger="backend.social_poster"):
        result = MetaHttpTransport(session=session).publish_facebook(
            jpeg=b"jpeg",
            caption="caption",
            settings=configured_settings(),
        )

    assert result == MetaDelivery("facebook", expected)
    combined = caplog.text + repr(result)
    assert TOKEN not in combined
    assert "provider body" not in combined
    assert "raw timeout secret" not in combined
    assert "invalid json raw body" not in combined


def test_transport_returns_not_configured_without_http_calls() -> None:
    session = FakeSession()
    settings = MetaSettings.from_mapping(
        {"FB_PAGE_ID": "", "IG_USER_ID": ""}
    )
    transport = MetaHttpTransport(session=session)

    facebook = transport.publish_facebook(
        jpeg=b"jpeg", caption="caption", settings=settings
    )
    instagram = transport.publish_instagram(
        image_url=IMAGE_URL, caption="caption", settings=settings
    )

    assert facebook == MetaDelivery("facebook", "not_configured")
    assert instagram == MetaDelivery("instagram", "not_configured")
    assert session.post_calls == []
    assert session.get_calls == []


def test_instagram_creates_polls_and_publishes_public_jpeg() -> None:
    session = FakeSession()
    session.post_responses = [
        FakeResponse(payload={"id": "container_123"}),
        FakeResponse(payload={"id": "media_456"}),
    ]
    session.get_responses = [
        FakeResponse(payload={"status_code": "IN_PROGRESS"}),
        FakeResponse(payload={"status_code": "FINISHED"}),
    ]
    sleeps: list[float] = []
    transport = MetaHttpTransport(session=session, sleep=sleeps.append)

    result = transport.publish_instagram(
        image_url=IMAGE_URL,
        caption="caption factual",
        settings=configured_settings(),
    )

    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert result == MetaDelivery("instagram", "success", "media_456")
    assert session.post_calls == [
        (
            f"https://graph.facebook.com/v26.0/{INSTAGRAM_ID}/media",
            {
                "headers": headers,
                "data": {"image_url": IMAGE_URL, "caption": "caption factual"},
                "timeout": 30,
            },
        ),
        (
            f"https://graph.facebook.com/v26.0/{INSTAGRAM_ID}/media_publish",
            {
                "headers": headers,
                "data": {"creation_id": "container_123"},
                "timeout": 30,
            },
        ),
    ]
    assert session.get_calls == [
        (
            "https://graph.facebook.com/v26.0/container_123?fields=status_code",
            {"headers": headers, "timeout": 30},
        ),
        (
            "https://graph.facebook.com/v26.0/container_123?fields=status_code",
            {"headers": headers, "timeout": 30},
        ),
    ]
    assert sleeps == [1.0]


@pytest.mark.parametrize(
    "url",
    [
        "http://project.supabase.co/social-media/pick.jpg",
        "https://user:pass@project.supabase.co/pick.jpg",
        "https://project.supabase.co/pick.png",
        "https://project.supabase.co/pick.jpg?token=private",
        "https://project.supabase.co/pick.jpg#fragment",
        " https://project.supabase.co/pick.jpg",
    ],
)
def test_instagram_rejects_non_public_or_non_jpeg_urls_before_http(url: str) -> None:
    session = FakeSession()
    result = MetaHttpTransport(session=session).publish_instagram(
        image_url=url,
        caption="caption",
        settings=configured_settings(),
    )
    assert result == MetaDelivery("instagram", "delivery_failed")
    assert session.post_calls == []


@pytest.mark.parametrize(
    ("create_response", "status_responses", "publish_response", "expected"),
    [
        (FakeResponse(400, {"error": {"code": 190}}), [], None, "token_invalid"),
        (FakeResponse(200, {}), [], None, "delivery_failed"),
        (
            FakeResponse(200, {"id": "container"}),
            [FakeResponse(200, {"status_code": "ERROR"})],
            None,
            "delivery_failed",
        ),
        (
            FakeResponse(200, {"id": "container"}),
            [FakeResponse(200, {"status_code": "UNKNOWN"})],
            None,
            "delivery_failed",
        ),
        (
            FakeResponse(200, {"id": "container"}),
            [FakeResponse(200, {"status_code": "IN_PROGRESS"})] * 5,
            None,
            "delivery_failed",
        ),
        (
            FakeResponse(200, {"id": "container"}),
            [FakeResponse(200, {"status_code": "FINISHED"})],
            FakeResponse(200, {}),
            "delivery_failed",
        ),
        (
            FakeResponse(200, {"id": "container"}),
            [FakeResponse(400, {"error": {"code": 190}})],
            None,
            "token_invalid",
        ),
    ],
)
def test_instagram_failures_are_bounded_and_sanitized(
    create_response: object,
    status_responses: list[object],
    publish_response: object | None,
    expected: MetaStatus,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeSession()
    session.post_responses = [create_response]
    if publish_response is not None:
        session.post_responses.append(publish_response)
    session.get_responses = list(status_responses)
    sleeps: list[float] = []

    with caplog.at_level(logging.INFO, logger="backend.social_poster"):
        result = MetaHttpTransport(session=session, sleep=sleeps.append).publish_instagram(
            image_url=IMAGE_URL,
            caption="caption",
            settings=configured_settings(),
        )

    assert result == MetaDelivery("instagram", expected)
    assert len(session.get_calls) <= 5
    assert len(sleeps) <= 4
    assert TOKEN not in caplog.text
    assert "raw" not in caplog.text


class FakeRepository:
    def __init__(self, exact_batch: MetaSocialBatch | None) -> None:
        self.exact_batch = exact_batch
        self.get_calls: list[tuple[str, datetime]] = []
        self.upload_calls: list[tuple[MetaSocialBatch, bytes]] = []
        self.record_calls: list[tuple[str, MetaDelivery]] = []
        self.upload_error: Exception | None = None
        self.upload_url = IMAGE_URL

    def get_batch(self, *, run_key: str, reference_at: datetime) -> MetaSocialBatch | None:
        self.get_calls.append((run_key, reference_at))
        return self.exact_batch

    def upload_jpeg(self, *, batch: MetaSocialBatch, jpeg: bytes) -> str:
        self.upload_calls.append((batch, jpeg))
        if self.upload_error is not None:
            raise self.upload_error
        return self.upload_url

    def record_delivery(self, *, run_id: str, result: MetaDelivery) -> None:
        self.record_calls.append((run_id, result))


class FakeTransport:
    def __init__(
        self,
        *,
        facebook: MetaDelivery | None = None,
        instagram: MetaDelivery | None = None,
    ) -> None:
        self.facebook_result = facebook or MetaDelivery("facebook", "success", "fb_1")
        self.instagram_result = instagram or MetaDelivery("instagram", "success", "ig_1")
        self.facebook_calls: list[dict[str, object]] = []
        self.instagram_calls: list[dict[str, object]] = []

    def publish_facebook(self, **kwargs: object) -> MetaDelivery:
        self.facebook_calls.append(kwargs)
        return self.facebook_result

    def publish_instagram(self, **kwargs: object) -> MetaDelivery:
        self.instagram_calls.append(kwargs)
        return self.instagram_result


class FakeCopyProvider:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[SocialContent] = []
        self.error = error

    def captions(self, value: SocialContent) -> SocialCaptions:
        self.calls.append(value)
        if self.error is not None:
            raise self.error
        return SocialCaptions(facebook="facebook caption", instagram="instagram caption")


class FakeBackgroundProvider:
    def __init__(self, *, value: bytes | None = b"background", error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.calls = 0

    def create(self) -> bytes | None:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


@dataclass
class RenderSpy:
    image: bytes
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, value: SocialContent, **kwargs: object) -> bytes:
        self.calls.append({"content": value, **kwargs})
        if self.error is not None:
            raise self.error
        return self.image


def run_publish(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repository: FakeRepository,
    transport: FakeTransport | None = None,
    copy_provider: FakeCopyProvider | None = None,
    background_provider: FakeBackgroundProvider | None = None,
    settings: MetaSettings | None = None,
    renderer: RenderSpy | None = None,
) -> tuple[tuple[MetaDelivery, MetaDelivery], FakeTransport, FakeCopyProvider, RenderSpy]:
    active_transport = transport or FakeTransport()
    active_copy = copy_provider or FakeCopyProvider()
    active_renderer = renderer or RenderSpy(jpeg_bytes())
    monkeypatch.setattr(social_poster, "render_social_jpeg", active_renderer)
    result = social_poster.publish_meta(
        run_key="github-run:123",
        reference_at=NOW,
        settings=settings or configured_settings(),
        repository=cast(SocialRepository, repository),
        transport=active_transport,  # type: ignore[arg-type]
        copy_provider=active_copy,
        background_provider=background_provider,
    )
    return result, active_transport, active_copy, active_renderer


def test_no_exact_batch_has_no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = FakeRepository(None)
    background = FakeBackgroundProvider()

    results, transport, copy, renderer = run_publish(
        monkeypatch,
        repository=repository,
        background_provider=background,
    )

    assert results == (
        MetaDelivery("facebook", "skipped"),
        MetaDelivery("instagram", "skipped"),
    )
    assert repository.get_calls == [("github-run:123", NOW)]
    assert repository.upload_calls == []
    assert repository.record_calls == []
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []
    assert copy.calls == []
    assert renderer.calls == []
    assert background.calls == 0


def test_successful_ledger_destinations_skip_without_expensive_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(
        batch(
            ledger={
                "facebook": {"success": True, "receipt": "fb_existing"},
                "instagram": {"success": True, "receipt": "ig_existing"},
            }
        )
    )

    results, transport, copy, renderer = run_publish(monkeypatch, repository=repository)

    assert results == (
        MetaDelivery("facebook", "skipped", "fb_existing"),
        MetaDelivery("instagram", "skipped", "ig_existing"),
    )
    assert repository.upload_calls == []
    assert repository.record_calls == []
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []
    assert copy.calls == []
    assert renderer.calls == []


def test_retry_calls_only_failed_instagram_and_reuses_one_render_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(
        batch(ledger={"facebook": {"success": True, "receipt": "fb_existing"}})
    )

    results, transport, _copy, renderer = run_publish(monkeypatch, repository=repository)

    assert results == (
        MetaDelivery("facebook", "skipped", "fb_existing"),
        MetaDelivery("instagram", "success", "ig_1"),
    )
    assert len(renderer.calls) == 1
    assert len(repository.upload_calls) == 1
    assert transport.facebook_calls == []
    assert len(transport.instagram_calls) == 1
    assert repository.record_calls == [
        (RUN_ID, MetaDelivery("instagram", "success", "ig_1"))
    ]


@pytest.mark.parametrize(
    ("facebook_result", "instagram_result"),
    [
        (
            MetaDelivery("facebook", "success", "fb_1"),
            MetaDelivery("instagram", "delivery_failed"),
        ),
        (
            MetaDelivery("facebook", "delivery_failed"),
            MetaDelivery("instagram", "success", "ig_1"),
        ),
    ],
)
def test_destinations_publish_and_record_independently(
    monkeypatch: pytest.MonkeyPatch,
    facebook_result: MetaDelivery,
    instagram_result: MetaDelivery,
) -> None:
    repository = FakeRepository(batch())
    transport = FakeTransport(facebook=facebook_result, instagram=instagram_result)

    results, _, _, _ = run_publish(
        monkeypatch, repository=repository, transport=transport
    )

    assert results == (facebook_result, instagram_result)
    assert len(transport.facebook_calls) == 1
    assert len(transport.instagram_calls) == 1
    assert repository.record_calls == [
        (RUN_ID, facebook_result),
        (RUN_ID, instagram_result),
    ]


def test_optional_copy_and_background_failures_use_local_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch())
    copy = FakeCopyProvider(error=RuntimeError("raw Groq provider body"))
    background = FakeBackgroundProvider(error=RuntimeError("raw Cloudflare body"))

    results, transport, _, renderer = run_publish(
        monkeypatch,
        repository=repository,
        copy_provider=copy,
        background_provider=background,
    )

    assert all(result.status == "success" for result in results)
    assert renderer.calls[0]["background_bytes"] is None
    facebook_caption = transport.facebook_calls[0]["caption"]
    instagram_caption = transport.instagram_calls[0]["caption"]
    assert isinstance(facebook_caption, str) and "Momio observado: 1.85" in facebook_caption
    assert isinstance(instagram_caption, str) and "Momio observado: 1.85" in instagram_caption


def test_dry_run_renders_exact_batch_but_has_no_remote_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = FakeRepository(batch())
    output = tmp_path / "review.jpg"
    settings = MetaSettings.from_mapping(
        {"META_DRY_RUN": "true", "META_DRY_RUN_OUTPUT": str(output)}
    )

    results, transport, _, renderer = run_publish(
        monkeypatch,
        repository=repository,
        settings=settings,
    )

    assert results == (
        MetaDelivery("facebook", "skipped"),
        MetaDelivery("instagram", "skipped"),
    )
    assert len(renderer.calls) == 1
    assert output.read_bytes() == jpeg_bytes()
    assert repository.upload_calls == []
    assert repository.record_calls == []
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []


def test_dry_run_still_renders_when_live_destinations_already_succeeded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository = FakeRepository(
        batch(
            ledger={
                "facebook": {"success": True, "receipt": "fb_existing"},
                "instagram": {"success": True, "receipt": "ig_existing"},
            }
        )
    )
    output = tmp_path / "review.jpg"
    settings = MetaSettings.from_mapping(
        {"META_DRY_RUN": "true", "META_DRY_RUN_OUTPUT": str(output)}
    )

    results, transport, _, renderer = run_publish(
        monkeypatch,
        repository=repository,
        settings=settings,
    )

    assert results == (
        MetaDelivery("facebook", "skipped", "fb_existing"),
        MetaDelivery("instagram", "skipped", "ig_existing"),
    )
    assert len(renderer.calls) == 1
    assert output.is_file()
    assert repository.upload_calls == []
    assert repository.record_calls == []
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []


def test_demo_content_can_never_reach_meta_or_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch(is_demo=True))

    results, transport, _, renderer = run_publish(monkeypatch, repository=repository)

    assert results == (
        MetaDelivery("facebook", "delivery_failed"),
        MetaDelivery("instagram", "delivery_failed"),
    )
    assert renderer.calls == []
    assert repository.upload_calls == []
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []
    assert repository.record_calls == [
        (RUN_ID, MetaDelivery("facebook", "delivery_failed")),
        (RUN_ID, MetaDelivery("instagram", "delivery_failed")),
    ]


def test_renderer_failure_is_sanitized_recorded_and_makes_no_meta_request(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeRepository(batch())
    renderer = RenderSpy(b"", error=RuntimeError("raw renderer secret"))

    with caplog.at_level(logging.INFO, logger="backend.social_poster"):
        results, transport, _, _ = run_publish(
            monkeypatch,
            repository=repository,
            renderer=renderer,
        )

    assert results == (
        MetaDelivery("facebook", "delivery_failed"),
        MetaDelivery("instagram", "delivery_failed"),
    )
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []
    assert repository.upload_calls == []
    assert [result for _, result in repository.record_calls] == list(results)
    assert "raw renderer secret" not in caplog.text


def test_storage_failure_does_not_erase_or_block_facebook_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch())
    repository.upload_error = RuntimeError("raw storage provider body")

    results, transport, _, _ = run_publish(monkeypatch, repository=repository)

    assert results == (
        MetaDelivery("facebook", "success", "fb_1"),
        MetaDelivery("instagram", "delivery_failed"),
    )
    assert len(transport.facebook_calls) == 1
    assert transport.instagram_calls == []
    assert repository.record_calls == [
        (RUN_ID, MetaDelivery("facebook", "success", "fb_1")),
        (RUN_ID, MetaDelivery("instagram", "delivery_failed")),
    ]


def test_non_deterministic_storage_url_never_reaches_instagram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch())
    repository.upload_url = (
        "https://project.supabase.co/storage/v1/object/public/social-media/"
        f"daily/{BATCH_ID}/999.jpg"
    )

    results, transport, _, _ = run_publish(monkeypatch, repository=repository)

    assert results == (
        MetaDelivery("facebook", "success", "fb_1"),
        MetaDelivery("instagram", "delivery_failed"),
    )
    assert transport.instagram_calls == []
    assert repository.record_calls[-1] == (
        RUN_ID,
        MetaDelivery("instagram", "delivery_failed"),
    )


def test_blank_destination_ids_record_not_configured_and_publish_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch())
    settings = MetaSettings.from_mapping(
        {
            "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
            "FB_PAGE_ID": "",
            "IG_USER_ID": INSTAGRAM_ID,
        }
    )

    results, transport, _, _ = run_publish(
        monkeypatch, repository=repository, settings=settings
    )

    assert results == (
        MetaDelivery("facebook", "not_configured"),
        MetaDelivery("instagram", "success", "ig_1"),
    )
    assert transport.facebook_calls == []
    assert len(transport.instagram_calls) == 1
    assert repository.record_calls == [
        (RUN_ID, MetaDelivery("facebook", "not_configured")),
        (RUN_ID, MetaDelivery("instagram", "success", "ig_1")),
    ]


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ((MetaDelivery("facebook", "success", "a"), MetaDelivery("instagram", "success", "b")), 0),
        ((MetaDelivery("facebook", "not_configured"), MetaDelivery("instagram", "success", "b")), 0),
        ((MetaDelivery("facebook", "delivery_failed"), MetaDelivery("instagram", "success", "b")), 1),
        ((MetaDelivery("facebook", "success", "a"), MetaDelivery("instagram", "token_invalid")), 1),
    ],
)
def test_exit_code_reflects_only_configured_failures(
    results: tuple[MetaDelivery, MetaDelivery], expected: int
) -> None:
    assert social_poster.exit_code_for(results) == expected


def test_run_key_prefers_explicit_and_otherwise_derives_github_key() -> None:
    assert social_poster.resolve_run_key(
        {"SCRAPER_RUN_KEY": "manual:abc", "GITHUB_RUN_ID": "123"}
    ) == "manual:abc"
    assert social_poster.resolve_run_key({"GITHUB_RUN_ID": "123"}) == "github-run:123"
    with pytest.raises(ValueError, match="run key"):
        social_poster.resolve_run_key({})

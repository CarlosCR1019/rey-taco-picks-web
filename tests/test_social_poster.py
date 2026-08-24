from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import logging
import math
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast
from uuid import UUID

from PIL import Image
import pytest
import requests

import backend.social_poster as social_poster
from backend.social_content import (
    SocialCaptions,
    SocialContent,
    build_fallback_captions,
)
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
    def __init__(
        self,
        status_code: int = 200,
        payload: object = None,
        *,
        raw_body: bytes | None = None,
        content_length: str | None = "auto",
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.payload = payload
        self.body = (
            raw_body
            if raw_body is not None
            else (
                b""
                if isinstance(payload, BaseException)
                else json.dumps(payload).encode("utf-8")
            )
        )
        self.headers: dict[str, str] = {}
        if content_length == "auto":
            self.headers["Content-Length"] = str(len(self.body))
        elif content_length is not None:
            self.headers["Content-Length"] = content_length
        self.chunks = chunks
        self.close_count = 0
        self.json_calls = 0

    def json(self) -> object:
        self.json_calls += 1
        raise AssertionError("response.json() must never be called")

    def iter_content(self, chunk_size: int) -> object:
        assert chunk_size <= 64 * 1024
        if isinstance(self.payload, BaseException):
            raise self.payload
        for chunk in self.chunks or [self.body]:
            yield chunk

    def close(self) -> None:
        self.close_count += 1


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
    response = FakeResponse(payload={"id": "fb_photo:123"})
    session.post_responses = [response]
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
                "headers": {
                    "Authorization": f"Bearer {TOKEN}",
                    "Accept-Encoding": "identity",
                },
                "data": {"message": "caption factual"},
                "files": {"source": ("rey-taco-pick.jpg", image, "image/jpeg")},
                "timeout": 30,
                "stream": True,
            },
        )
    ]
    assert TOKEN not in session.post_calls[0][0]
    assert session.post_responses == []
    assert response.close_count == 1
    assert response.json_calls == 0


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (FakeResponse(400, {"error": {"code": 190, "message": "raw"}}), "token_invalid"),
        (FakeResponse(400, {"error": {"type": "OAuthException"}}), "delivery_failed"),
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


def test_facebook_http_failure_logs_only_safe_error_metadata(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeSession()
    session.post_responses = [
        FakeResponse(
            400,
            {
                "error": {
                    "code": 200,
                    "error_subcode": 2018065,
                    "type": "OAuthException",
                    "message": "private provider explanation",
                }
            },
        )
    ]

    with caplog.at_level(logging.INFO, logger="backend.social_poster"):
        result = MetaHttpTransport(session=session).publish_facebook(
            jpeg=b"jpeg",
            caption="caption",
            settings=configured_settings(),
        )

    assert result == MetaDelivery("facebook", "delivery_failed")
    assert "http_status=400" in caplog.text
    assert "error_code=200" in caplog.text
    assert "error_subcode=2018065" in caplog.text
    assert "private provider explanation" not in caplog.text


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


@pytest.mark.parametrize("interval", [0, -1, 61, math.nan, math.inf, -math.inf, True])
def test_instagram_poll_interval_must_be_finite_positive_and_at_most_sixty(
    interval: object,
) -> None:
    with pytest.raises(ValueError, match="poll_interval"):
        MetaHttpTransport(
            session=FakeSession(),
            sleep=lambda _seconds: None,
            poll_interval=interval,  # type: ignore[arg-type]
        )


def test_instagram_creates_polls_and_publishes_public_jpeg() -> None:
    session = FakeSession()
    post_responses = [
        FakeResponse(payload={"id": "container_123"}),
        FakeResponse(payload={"id": "media_456"}),
    ]
    get_responses = [
        FakeResponse(payload={"status_code": "IN_PROGRESS"}),
        FakeResponse(payload={"status_code": "FINISHED"}),
    ]
    session.post_responses = list(post_responses)
    session.get_responses = list(get_responses)
    sleeps: list[float] = []
    transport = MetaHttpTransport(session=session, sleep=sleeps.append)

    result = transport.publish_instagram(
        image_url=IMAGE_URL,
        caption="caption factual",
        settings=configured_settings(),
    )

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept-Encoding": "identity",
    }
    assert result == MetaDelivery("instagram", "success", "media_456")
    assert session.post_calls == [
        (
            f"https://graph.facebook.com/v26.0/{INSTAGRAM_ID}/media",
            {
                "headers": headers,
                "data": {"image_url": IMAGE_URL, "caption": "caption factual"},
                "timeout": 30,
                "stream": True,
            },
        ),
        (
            f"https://graph.facebook.com/v26.0/{INSTAGRAM_ID}/media_publish",
            {
                "headers": headers,
                "data": {"creation_id": "container_123"},
                "timeout": 30,
                "stream": True,
            },
        ),
    ]
    assert session.get_calls == [
        (
            "https://graph.facebook.com/v26.0/container_123?fields=status_code",
            {"headers": headers, "timeout": 30, "stream": True},
        ),
        (
            "https://graph.facebook.com/v26.0/container_123?fields=status_code",
            {"headers": headers, "timeout": 30, "stream": True},
        ),
    ]
    assert sleeps == [60.0]
    assert all(response.close_count == 1 for response in post_responses + get_responses)
    assert all(response.json_calls == 0 for response in post_responses + get_responses)


def test_meta_response_without_content_length_streams_success_and_closes() -> None:
    response = FakeResponse(
        payload={"id": "fb_chunked"},
        content_length=None,
        chunks=[b'{"id":', b' "fb_chunked"}'],
    )
    session = FakeSession()
    session.post_responses = [response]

    result = MetaHttpTransport(session=session).publish_facebook(
        jpeg=b"jpeg",
        caption="caption",
        settings=configured_settings(),
    )

    assert result == MetaDelivery("facebook", "success", "fb_chunked")
    assert response.close_count == 1
    assert response.json_calls == 0


def test_meta_chunked_response_over_cap_fails_before_json_and_closes() -> None:
    response = FakeResponse(
        payload=None,
        content_length=None,
        chunks=[b"x" * (64 * 1024)] * 4 + [b"x"],
    )
    session = FakeSession()
    session.post_responses = [response]

    result = MetaHttpTransport(session=session).publish_facebook(
        jpeg=b"jpeg",
        caption="caption",
        settings=configured_settings(),
    )

    assert result == MetaDelivery("facebook", "delivery_failed")
    assert response.close_count == 1
    assert response.json_calls == 0


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(payload={"id": "fb_1"}, content_length=str(256 * 1024 + 1)),
        FakeResponse(payload={"id": "fb_1"}, content_length="1"),
        FakeResponse(payload={"id": "fb_1"}, content_length="not-a-number"),
        FakeResponse(payload={"id": "fb_1"}, content_length="1, 1"),
        FakeResponse(payload={"id": "fb_1"}, content_length="-1"),
        FakeResponse(payload={"id": "fb_1"}, content_length="01"),
    ],
    ids=(
        "declared-oversized",
        "lying-small",
        "invalid-length",
        "duplicate-comma-length",
        "negative-length",
        "noncanonical-leading-zero",
    ),
)
def test_present_meta_content_length_is_canonical_exact_bounded_and_closes(
    response: FakeResponse,
) -> None:
    session = FakeSession()
    session.post_responses = [response]

    result = MetaHttpTransport(session=session).publish_facebook(
        jpeg=b"jpeg",
        caption="caption",
        settings=configured_settings(),
    )

    assert result == MetaDelivery("facebook", "delivery_failed")
    assert response.close_count == 1
    assert response.json_calls == 0


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
    def __init__(
        self,
        exact_batch: MetaSocialBatch | None,
        *,
        events: list[str] | None = None,
    ) -> None:
        self.exact_batch = exact_batch
        self.events = events
        self.get_calls: list[tuple[str, datetime]] = []
        self.upload_calls: list[tuple[MetaSocialBatch, bytes]] = []
        self.record_calls: list[tuple[str, MetaDelivery]] = []
        self.record_attempts: list[str] = []
        self.claim_calls: list[dict[str, object]] = []
        self.claim_results = {"facebook": True, "instagram": True}
        self.claim_errors: dict[str, Exception] = {}
        self.record_errors: dict[str, Exception] = {}
        self.upload_error: Exception | None = None
        self.upload_url = IMAGE_URL

    def get_batch(self, *, run_key: str, reference_at: datetime) -> MetaSocialBatch | None:
        if self.events is not None:
            self.events.append("repository:get")
        self.get_calls.append((run_key, reference_at))
        return self.exact_batch

    def upload_jpeg(self, *, batch: MetaSocialBatch, jpeg: bytes) -> str:
        if self.events is not None:
            self.events.append("storage:instagram")
        self.upload_calls.append((batch, jpeg))
        if self.upload_error is not None:
            raise self.upload_error
        return self.upload_url

    def claim_destination(
        self,
        *,
        run_id: str,
        destination: Literal["facebook", "instagram"],
        attempt_id: str,
        lease_expires_at: datetime,
    ) -> bool:
        if self.events is not None:
            self.events.append(f"claim:{destination}")
        self.claim_calls.append(
            {
                "run_id": run_id,
                "destination": destination,
                "attempt_id": attempt_id,
                "lease_expires_at": lease_expires_at,
            }
        )
        if destination in self.claim_errors:
            raise self.claim_errors[destination]
        return self.claim_results[destination]

    def record_delivery(
        self,
        *,
        run_id: str,
        result: MetaDelivery,
        attempt_id: str,
    ) -> None:
        if self.events is not None:
            self.events.append(f"record:{result.destination}")
        self.record_calls.append((run_id, result))
        self.record_attempts.append(attempt_id)
        if result.destination in self.record_errors:
            raise self.record_errors[result.destination]


class FakeTransport:
    def __init__(
        self,
        *,
        facebook: MetaDelivery | None = None,
        instagram: MetaDelivery | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.facebook_result = facebook or MetaDelivery("facebook", "success", "fb_1")
        self.instagram_result = instagram or MetaDelivery("instagram", "success", "ig_1")
        self.facebook_calls: list[dict[str, object]] = []
        self.instagram_calls: list[dict[str, object]] = []
        self.events = events

    def publish_facebook(self, **kwargs: object) -> MetaDelivery:
        if self.events is not None:
            self.events.append("meta:facebook")
        self.facebook_calls.append(kwargs)
        return self.facebook_result

    def publish_instagram(self, **kwargs: object) -> MetaDelivery:
        if self.events is not None:
            self.events.append("meta:instagram")
        self.instagram_calls.append(kwargs)
        return self.instagram_result


class FakeCopyProvider:
    def __init__(
        self,
        *,
        candidate: SocialCaptions | None = None,
        error: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.calls: list[SocialContent] = []
        self.candidate = candidate
        self.error = error
        self.events = events

    def captions(self, value: SocialContent) -> SocialCaptions:
        if self.events is not None:
            self.events.append("copy")
        self.calls.append(value)
        if self.error is not None:
            raise self.error
        return self.candidate or build_fallback_captions(value)


class FakeBackgroundProvider:
    def __init__(
        self,
        *,
        value: bytes | None = b"background",
        error: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.value = value
        self.error = error
        self.calls = 0
        self.events = events

    def create(self) -> bytes | None:
        if self.events is not None:
            self.events.append("background")
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


@dataclass
class RenderSpy:
    image: bytes
    error: Exception | None = None
    events: list[str] | None = None

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, value: SocialContent, **kwargs: object) -> bytes:
        if self.events is not None:
            self.events.append("render")
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


def test_active_claim_denial_skips_destination_without_meta_or_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch())
    repository.claim_results["facebook"] = False

    results, transport, _, renderer = run_publish(monkeypatch, repository=repository)

    assert results == (
        MetaDelivery("facebook", "skipped"),
        MetaDelivery("instagram", "success", "ig_1"),
    )
    assert len(renderer.calls) == 1
    assert transport.facebook_calls == []
    assert len(transport.instagram_calls) == 1
    assert repository.record_calls == [
        (RUN_ID, MetaDelivery("instagram", "success", "ig_1"))
    ]


def test_two_denied_jit_claims_skip_meta_and_completion_after_preparation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch())
    repository.claim_results = {"facebook": False, "instagram": False}

    results, transport, copy, renderer = run_publish(monkeypatch, repository=repository)

    assert results == (
        MetaDelivery("facebook", "skipped"),
        MetaDelivery("instagram", "skipped"),
    )
    assert len(renderer.calls) == 1
    assert len(copy.calls) == 1
    assert len(repository.upload_calls) == 1
    assert repository.record_calls == []
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []


def test_claim_attempts_are_unique_bounded_and_reused_for_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch())
    before = datetime.now(timezone.utc)

    run_publish(monkeypatch, repository=repository)

    after = datetime.now(timezone.utc)
    assert [call["destination"] for call in repository.claim_calls] == [
        "facebook",
        "instagram",
    ]
    attempt_ids = [str(call["attempt_id"]) for call in repository.claim_calls]
    assert len(set(attempt_ids)) == 2
    for attempt_id in attempt_ids:
        assert str(UUID(attempt_id)) == attempt_id
    for call in repository.claim_calls:
        lease = call["lease_expires_at"]
        assert isinstance(lease, datetime)
        assert before < lease <= after + timedelta(minutes=10)
    assert repository.record_attempts == attempt_ids


def test_jit_claims_exclude_copy_render_facebook_and_storage_from_ig_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worst live path starts each bounded lease immediately before Meta."""

    events: list[str] = []
    repository = FakeRepository(batch(), events=events)
    transport = FakeTransport(events=events)
    copy = FakeCopyProvider(events=events)
    background = FakeBackgroundProvider(events=events)
    renderer = RenderSpy(jpeg_bytes(), events=events)

    results, _, _, _ = run_publish(
        monkeypatch,
        repository=repository,
        transport=transport,
        copy_provider=copy,
        background_provider=background,
        renderer=renderer,
    )

    assert all(result.status == "success" for result in results)
    assert events == [
        "repository:get",
        "copy",
        "background",
        "render",
        "claim:facebook",
        "meta:facebook",
        "record:facebook",
        "storage:instagram",
        "claim:instagram",
        "meta:instagram",
        "record:instagram",
    ]


def test_missing_config_claim_is_immediately_completed_before_preparing_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    repository = FakeRepository(batch(), events=events)
    transport = FakeTransport(events=events)
    settings = MetaSettings.from_mapping(
        {
            "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
            "FB_PAGE_ID": "",
            "IG_USER_ID": INSTAGRAM_ID,
        }
    )

    run_publish(
        monkeypatch,
        repository=repository,
        transport=transport,
        copy_provider=FakeCopyProvider(events=events),
        background_provider=FakeBackgroundProvider(events=events),
        renderer=RenderSpy(jpeg_bytes(), events=events),
        settings=settings,
    )

    assert events == [
        "repository:get",
        "claim:facebook",
        "record:facebook",
        "copy",
        "background",
        "render",
        "storage:instagram",
        "claim:instagram",
        "meta:instagram",
        "record:instagram",
    ]


def test_render_failure_claims_each_destination_only_for_immediate_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    repository = FakeRepository(batch(), events=events)

    run_publish(
        monkeypatch,
        repository=repository,
        transport=FakeTransport(events=events),
        copy_provider=FakeCopyProvider(events=events),
        background_provider=FakeBackgroundProvider(events=events),
        renderer=RenderSpy(
            b"", error=RuntimeError("renderer failed"), events=events
        ),
    )

    assert events == [
        "repository:get",
        "copy",
        "background",
        "render",
        "claim:facebook",
        "record:facebook",
        "claim:instagram",
        "record:instagram",
    ]


def test_caption_failure_claims_each_destination_only_for_immediate_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    repository = FakeRepository(batch(), events=events)

    def fail_captions(_provider: object, _content: SocialContent) -> SocialCaptions:
        events.append("copy")
        raise RuntimeError("caption validation failed")

    monkeypatch.setattr(social_poster, "_safe_captions", fail_captions)

    run_publish(
        monkeypatch,
        repository=repository,
        transport=FakeTransport(events=events),
    )

    assert events == [
        "repository:get",
        "copy",
        "claim:facebook",
        "record:facebook",
        "claim:instagram",
        "record:instagram",
    ]


def test_storage_failure_does_not_start_instagram_lease_until_upload_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    repository = FakeRepository(batch(), events=events)
    repository.upload_error = RuntimeError("storage failed")

    run_publish(
        monkeypatch,
        repository=repository,
        transport=FakeTransport(events=events),
        copy_provider=FakeCopyProvider(events=events),
        background_provider=FakeBackgroundProvider(events=events),
        renderer=RenderSpy(jpeg_bytes(), events=events),
    )

    assert events == [
        "repository:get",
        "copy",
        "background",
        "render",
        "claim:facebook",
        "meta:facebook",
        "record:facebook",
        "storage:instagram",
        "claim:instagram",
        "record:instagram",
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


def test_facebook_ledger_outage_is_sanitized_and_instagram_still_completes(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeRepository(batch())
    repository.record_errors["facebook"] = RuntimeError(
        "raw ledger response service-secret"
    )

    with caplog.at_level(logging.INFO, logger="backend.social_poster"):
        results, transport, _, _ = run_publish(monkeypatch, repository=repository)

    assert results == (
        MetaDelivery("facebook", "delivery_failed"),
        MetaDelivery("instagram", "success", "ig_1"),
    )
    assert len(transport.facebook_calls) == 1
    assert len(transport.instagram_calls) == 1
    assert [result.destination for _, result in repository.record_calls] == [
        "facebook",
        "instagram",
    ]
    assert "raw ledger response" not in caplog.text
    assert "service-secret" not in caplog.text
    assert "ledger=delivery_failed" in caplog.text


def test_claim_outage_isolated_per_destination_without_unclaimed_completion(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeRepository(batch())
    repository.claim_errors["facebook"] = RuntimeError("raw claim body")

    with caplog.at_level(logging.INFO, logger="backend.social_poster"):
        results, transport, _, _ = run_publish(monkeypatch, repository=repository)

    assert results == (
        MetaDelivery("facebook", "delivery_failed"),
        MetaDelivery("instagram", "success", "ig_1"),
    )
    assert transport.facebook_calls == []
    assert len(transport.instagram_calls) == 1
    assert [result.destination for _, result in repository.record_calls] == [
        "instagram"
    ]
    assert "raw claim body" not in caplog.text


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


def test_unsafe_injected_caption_package_is_revalidated_before_live_delivery(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeRepository(batch())
    fallback = build_fallback_captions(repository.exact_batch.content)  # type: ignore[union-attr]
    unsafe = SocialCaptions(
        facebook=f"{fallback.facebook}\nResultado garantizado.",
        instagram=fallback.instagram,
    )

    with caplog.at_level(logging.INFO, logger="backend.social_poster"):
        results, transport, _, _ = run_publish(
            monkeypatch,
            repository=repository,
            copy_provider=FakeCopyProvider(candidate=unsafe),
        )

    assert all(result.status == "success" for result in results)
    assert transport.facebook_calls[0]["caption"] == fallback.facebook
    assert transport.instagram_calls[0]["caption"] == fallback.instagram
    assert unsafe.facebook not in {
        transport.facebook_calls[0]["caption"],
        transport.instagram_calls[0]["caption"],
    }
    assert "meta copy=fallback exception=ValueError" in caplog.text


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
    assert repository.claim_calls == []
    assert repository.upload_calls == []
    assert repository.record_calls == []
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []


def test_dry_run_revalidates_unsafe_injected_captions_before_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = FakeRepository(batch())
    fallback = build_fallback_captions(repository.exact_batch.content)  # type: ignore[union-attr]
    unsafe = SocialCaptions(
        facebook=fallback.facebook,
        instagram=f"{fallback.instagram}\nApuesta ahora.",
    )
    output = tmp_path / "review.jpg"
    settings = MetaSettings.from_mapping(
        {"META_DRY_RUN": "true", "META_DRY_RUN_OUTPUT": str(output)}
    )

    with caplog.at_level(logging.INFO, logger="backend.social_poster"):
        results, transport, provider, renderer = run_publish(
            monkeypatch,
            repository=repository,
            settings=settings,
            copy_provider=FakeCopyProvider(candidate=unsafe),
        )

    assert results == (
        MetaDelivery("facebook", "skipped"),
        MetaDelivery("instagram", "skipped"),
    )
    assert provider.calls == [repository.exact_batch.content]  # type: ignore[union-attr]
    assert len(renderer.calls) == 1
    assert output.is_file()
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []
    assert "meta copy=fallback exception=ValueError" in caplog.text


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


def test_renderer_failure_completion_outages_are_isolated_per_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch())
    repository.record_errors["facebook"] = RuntimeError("raw ledger body")
    renderer = RenderSpy(b"", error=RuntimeError("raw renderer body"))

    results, transport, _, _ = run_publish(
        monkeypatch,
        repository=repository,
        renderer=renderer,
    )

    assert results == (
        MetaDelivery("facebook", "delivery_failed"),
        MetaDelivery("instagram", "delivery_failed"),
    )
    assert [result.destination for _, result in repository.record_calls] == [
        "facebook",
        "instagram",
    ]
    assert transport.facebook_calls == []
    assert transport.instagram_calls == []


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


def test_missing_configuration_ledger_outage_does_not_block_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FakeRepository(batch())
    repository.record_errors["facebook"] = RuntimeError("raw ledger body")
    settings = MetaSettings.from_mapping(
        {
            "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
            "FB_PAGE_ID": "",
            "IG_USER_ID": INSTAGRAM_ID,
        }
    )

    results, transport, _, _ = run_publish(
        monkeypatch,
        repository=repository,
        settings=settings,
    )

    assert results == (
        MetaDelivery("facebook", "delivery_failed"),
        MetaDelivery("instagram", "success", "ig_1"),
    )
    assert transport.facebook_calls == []
    assert len(transport.instagram_calls) == 1
    assert [result.destination for _, result in repository.record_calls] == [
        "facebook",
        "instagram",
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


def cli_values(**overrides: str) -> dict[str, str]:
    values = {
        "SCRAPER_RUN_KEY": "manual:cli",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
        "GROQ_API_KEY": "groq-secret",
        "GROQ_CONTENT_MODEL": "approved-model",
        "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
        "FB_PAGE_ID": FACEBOOK_ID,
        "IG_USER_ID": INSTAGRAM_ID,
    }
    values.update(overrides)
    return values


def test_runtime_environment_overrides_backend_dotenv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        social_poster,
        "dotenv_values",
        lambda _path: {
            "SCRAPER_RUN_KEY": "file-run",
            "META_SYSTEM_USER_ACCESS_TOKEN": "file-secret",
        },
    )
    monkeypatch.setenv("SCRAPER_RUN_KEY", "environment-run")
    monkeypatch.setenv("META_SYSTEM_USER_ACCESS_TOKEN", "environment-secret")

    values = social_poster._runtime_values(None)

    assert values["SCRAPER_RUN_KEY"] == "environment-run"
    assert values["META_SYSTEM_USER_ACCESS_TOKEN"] == "environment-secret"


@pytest.mark.parametrize(
    ("run_values", "expected_run_key", "expected_dry_run"),
    [
        ({"SCRAPER_RUN_KEY": "manual:explicit"}, "manual:explicit", False),
        (
            {"SCRAPER_RUN_KEY": "", "GITHUB_RUN_ID": "987"},
            "github-run:987",
            False,
        ),
        (
            {
                "SCRAPER_RUN_KEY": "manual:preview",
                "META_DRY_RUN": "true",
                "META_SYSTEM_USER_ACCESS_TOKEN": "",
                "FB_PAGE_ID": "",
                "IG_USER_ID": "",
            },
            "manual:preview",
            True,
        ),
    ],
)
def test_main_constructs_runtime_adapters_without_network(
    monkeypatch: pytest.MonkeyPatch,
    run_values: dict[str, str],
    expected_run_key: str,
    expected_dry_run: bool,
) -> None:
    repository = object()
    copy_provider = object()
    transport = object()
    constructed: dict[str, object] = {}

    def repository_factory(**kwargs: object) -> object:
        constructed["repository"] = kwargs
        return repository

    def copy_factory(**kwargs: object) -> object:
        constructed["copy"] = kwargs
        return copy_provider

    def transport_factory() -> object:
        constructed["transport"] = True
        return transport

    def publish_fake(**kwargs: object) -> tuple[MetaDelivery, MetaDelivery]:
        constructed["publish"] = kwargs
        return (
            MetaDelivery("facebook", "success", "fb_cli"),
            MetaDelivery("instagram", "success", "ig_cli"),
        )

    monkeypatch.setattr(social_poster, "SupabaseSocialRepository", repository_factory)
    monkeypatch.setattr(social_poster, "GroqCopyProvider", copy_factory)
    monkeypatch.setattr(social_poster, "MetaHttpTransport", transport_factory)
    monkeypatch.setattr(social_poster, "publish_meta", publish_fake)

    assert social_poster.main(cli_values(**run_values)) == 0

    assert constructed["repository"] == {
        "supabase_url": "https://project.supabase.co",
        "service_role_key": "service-role-secret",
    }
    assert constructed["copy"] == {
        "api_key": "groq-secret",
        "model": "approved-model",
    }
    publish_call = cast(dict[str, object], constructed["publish"])
    assert publish_call["run_key"] == expected_run_key
    assert publish_call["repository"] is repository
    assert publish_call["transport"] is transport
    assert publish_call["copy_provider"] is copy_provider
    assert publish_call["background_provider"] is None
    assert isinstance(publish_call["reference_at"], datetime)
    assert cast(datetime, publish_call["reference_at"]).tzinfo is timezone.utc
    assert cast(MetaSettings, publish_call["settings"]).dry_run is expected_dry_run


def test_main_sanitizes_top_level_adapter_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_repository(**_kwargs: object) -> object:
        raise RuntimeError("raw response contained service-role-secret")

    monkeypatch.setattr(social_poster, "SupabaseSocialRepository", fail_repository)

    with caplog.at_level(logging.INFO, logger="backend.social_poster"):
        result = social_poster.main(cli_values())

    assert result == 1
    assert "RuntimeError" in caplog.text
    assert "raw response" not in caplog.text
    assert "service-role-secret" not in caplog.text

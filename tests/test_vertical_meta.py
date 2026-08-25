from __future__ import annotations

import json
import math

import pytest
import requests

from backend.social_poster import MetaSettings
from backend.vertical_meta import VerticalDelivery, VerticalMetaHttpTransport


TOKEN = "runtime-secret"
INSTAGRAM_ID = "17841441356316454"
STORY_URL = (
    "https://project.supabase.co/storage/v1/object/public/social-vertical/"
    "stories/2026-08-24/story.jpg"
)


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        payload: object = None,
        *,
        content_length: str | None = "auto",
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.body = json.dumps(payload).encode("utf-8")
        self.headers: dict[str, str] = {}
        if content_length == "auto":
            self.headers["Content-Length"] = str(len(self.body))
        elif content_length is not None:
            self.headers["Content-Length"] = content_length
        self.chunks = chunks
        self.close_count = 0

    def iter_content(self, chunk_size: int):
        assert chunk_size <= 64 * 1024
        yield from self.chunks or [self.body]

    def close(self) -> None:
        self.close_count += 1


class FakeSession:
    def __init__(self) -> None:
        self.post_responses: list[object] = []
        self.get_responses: list[object] = []
        self.post_calls: list[tuple[str, dict[str, object]]] = []
        self.get_calls: list[tuple[str, dict[str, object]]] = []

    def queue_posts(self, *responses: object) -> None:
        self.post_responses.extend(responses)

    def queue_gets(self, *responses: object) -> None:
        self.get_responses.extend(responses)

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


@pytest.fixture
def meta_settings() -> MetaSettings:
    return MetaSettings.from_mapping(
        {
            "META_SYSTEM_USER_ACCESS_TOKEN": TOKEN,
            "IG_USER_ID": INSTAGRAM_ID,
        }
    )


def test_instagram_story_creates_polls_and_publishes(
    meta_settings: MetaSettings,
) -> None:
    session = FakeSession()
    created = FakeResponse(200, {"id": "story_container_1"})
    processing = FakeResponse(200, {"status_code": "IN_PROGRESS"})
    finished = FakeResponse(200, {"status_code": "FINISHED"})
    published = FakeResponse(200, {"id": "story_media_1"})
    session.queue_posts(created, published)
    session.queue_gets(processing, finished)
    sleeps: list[float] = []

    delivery = VerticalMetaHttpTransport(
        session=session, sleep=sleeps.append, poll_interval=2
    ).publish_instagram_story(image_url=STORY_URL, settings=meta_settings)

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept-Encoding": "identity",
    }
    assert delivery == VerticalDelivery("instagram_story", "success", "story_media_1")
    assert session.post_calls == [
        (
            f"https://graph.facebook.com/v26.0/{INSTAGRAM_ID}/media",
            {
                "headers": headers,
                "data": {"image_url": STORY_URL, "media_type": "STORIES"},
                "timeout": 30,
                "stream": True,
            },
        ),
        (
            f"https://graph.facebook.com/v26.0/{INSTAGRAM_ID}/media_publish",
            {
                "headers": headers,
                "data": {"creation_id": "story_container_1"},
                "timeout": 30,
                "stream": True,
            },
        ),
    ]
    assert "caption" not in session.post_calls[0][1]["data"]
    assert session.get_calls == [
        (
            "https://graph.facebook.com/v26.0/story_container_1?fields=status_code",
            {"headers": headers, "timeout": 30, "stream": True},
        ),
        (
            "https://graph.facebook.com/v26.0/story_container_1?fields=status_code",
            {"headers": headers, "timeout": 30, "stream": True},
        ),
    ]
    assert sleeps == [2.0]
    assert TOKEN not in repr([url for url, _ in session.post_calls + session.get_calls])
    assert all(
        response.close_count == 1
        for response in (created, processing, finished, published)
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://project.supabase.co/storage/v1/object/public/social-vertical/a.jpg",
        "https://attacker.example/storage/v1/object/public/social-vertical/a.jpg",
        "https://project.supabase.co.evil.example/storage/v1/object/public/social-vertical/a.jpg",
        "https://user:pass@project.supabase.co/storage/v1/object/public/social-vertical/a.jpg",
        "https://project.supabase.co:444/storage/v1/object/public/social-vertical/a.jpg",
        "https://project.supabase.co/storage/v1/object/public/another-bucket/a.jpg",
        "https://project.supabase.co/storage/v1/object/public/social-vertical/a.png",
        "https://project.supabase.co/storage/v1/object/public/social-vertical/a.jpg?token=x",
        "https://project.supabase.co/storage/v1/object/public/social-vertical/a.jpg#fragment",
        " https://project.supabase.co/storage/v1/object/public/social-vertical/a.jpg",
        "https://project.supabase.co/storage/v1/object/public/social-vertical/a\u200b.jpg",
    ],
)
def test_story_rejects_non_supabase_or_non_https_url_before_http(
    url: str, meta_settings: MetaSettings
) -> None:
    session = FakeSession()
    delivery = VerticalMetaHttpTransport(session=session).publish_instagram_story(
        image_url=url, settings=meta_settings
    )
    assert delivery == VerticalDelivery("instagram_story", "media_invalid")
    assert session.post_calls == []
    assert session.get_calls == []


def test_story_returns_not_configured_before_url_or_http() -> None:
    session = FakeSession()
    settings = MetaSettings.from_mapping({})

    delivery = VerticalMetaHttpTransport(session=session).publish_instagram_story(
        image_url="invalid", settings=settings
    )

    assert delivery == VerticalDelivery("instagram_story", "not_configured")
    assert session.post_calls == []
    assert session.get_calls == []


@pytest.mark.parametrize("interval", [0, -1, 61, math.nan, math.inf, -math.inf, True])
def test_story_poll_interval_is_finite_positive_and_at_most_sixty(
    interval: object,
) -> None:
    with pytest.raises(ValueError, match="poll interval"):
        VerticalMetaHttpTransport(
            session=FakeSession(),
            poll_interval=interval,  # type: ignore[arg-type]
        )


def test_story_polling_is_bounded_to_five_attempts(
    meta_settings: MetaSettings,
) -> None:
    session = FakeSession()
    session.queue_posts(FakeResponse(200, {"id": "story_container_1"}))
    session.queue_gets(
        *(FakeResponse(200, {"status_code": "IN_PROGRESS"}) for _ in range(5))
    )
    sleeps: list[float] = []

    delivery = VerticalMetaHttpTransport(
        session=session, sleep=sleeps.append, poll_interval=3
    ).publish_instagram_story(image_url=STORY_URL, settings=meta_settings)

    assert delivery == VerticalDelivery("instagram_story", "delivery_failed")
    assert len(session.get_calls) == 5
    assert sleeps == [3.0] * 4
    assert len(session.post_calls) == 1


@pytest.mark.parametrize(
    ("post_responses", "get_responses", "expected"),
    [
        ([FakeResponse(400, {"error": {"code": 190}})], [], "token_invalid"),
        ([FakeResponse(500, {"error": {"code": 2}})], [], "delivery_failed"),
        ([FakeResponse(200, {})], [], "delivery_failed"),
        (
            [FakeResponse(200, {"id": "container"})],
            [FakeResponse(400, {"error": {"code": 190}})],
            "token_invalid",
        ),
        (
            [FakeResponse(200, {"id": "container"})],
            [FakeResponse(200, {"status_code": "ERROR"})],
            "delivery_failed",
        ),
        (
            [FakeResponse(200, {"id": "container"}), FakeResponse(200, {})],
            [FakeResponse(200, {"status_code": "FINISHED"})],
            "pending_review",
        ),
        (
            [
                FakeResponse(200, {"id": "container"}),
                FakeResponse(500, {"error": {"code": 2}}),
            ],
            [FakeResponse(200, {"status_code": "FINISHED"})],
            "pending_review",
        ),
        (
            [
                FakeResponse(200, {"id": "container"}),
                FakeResponse(400, {"error": {"code": 190}}),
            ],
            [FakeResponse(200, {"status_code": "FINISHED"})],
            "token_invalid",
        ),
        ([requests.Timeout("raw secret response")], [], "delivery_failed"),
    ],
)
def test_story_failures_return_only_safe_statuses(
    post_responses: list[object],
    get_responses: list[object],
    expected: str,
    meta_settings: MetaSettings,
) -> None:
    session = FakeSession()
    session.queue_posts(*post_responses)
    session.queue_gets(*get_responses)

    delivery = VerticalMetaHttpTransport(session=session).publish_instagram_story(
        image_url=STORY_URL, settings=meta_settings
    )

    assert delivery == VerticalDelivery("instagram_story", expected)
    assert "raw secret response" not in repr(delivery)


def test_story_timeout_after_media_publish_is_pending_review_and_not_retried(
    meta_settings: MetaSettings,
) -> None:
    session = FakeSession()
    session.queue_posts(
        FakeResponse(200, {"id": "container"}),
        requests.Timeout("raw uncertain response runtime-secret"),
    )
    session.queue_gets(FakeResponse(200, {"status_code": "FINISHED"}))

    delivery = VerticalMetaHttpTransport(session=session).publish_instagram_story(
        image_url=STORY_URL,
        settings=meta_settings,
    )

    assert delivery == VerticalDelivery("instagram_story", "pending_review")
    assert len(session.post_calls) == 2
    assert "runtime-secret" not in repr(delivery)


def test_story_rejects_oversized_streamed_meta_response_and_closes(
    meta_settings: MetaSettings,
) -> None:
    response = FakeResponse(
        200,
        None,
        content_length=None,
        chunks=[b"x" * (64 * 1024)] * 4 + [b"x"],
    )
    session = FakeSession()
    session.queue_posts(response)

    delivery = VerticalMetaHttpTransport(session=session).publish_instagram_story(
        image_url=STORY_URL, settings=meta_settings
    )

    assert delivery == VerticalDelivery("instagram_story", "delivery_failed")
    assert response.close_count == 1

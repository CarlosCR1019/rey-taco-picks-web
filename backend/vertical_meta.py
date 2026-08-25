"""Bounded Meta Graph transport for vertical social media."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import math
import re
import time
from typing import Literal, Protocol, cast
from unicodedata import category as unicode_category
from urllib.parse import urlsplit

import requests

from backend.meta_http import (
    MetaResponse,
    meta_auth_headers,
    meta_graph_url,
    meta_token_invalid,
    read_meta_json,
    safe_meta_id,
)
from backend.social_poster import MetaSettings


VerticalStatus = Literal[
    "success",
    "complete",
    "not_configured",
    "token_invalid",
    "delivery_failed",
    "media_invalid",
]
VerticalDestination = Literal[
    "instagram_story",
    "instagram_reel",
    "facebook_reel",
]
_SAFE_RECEIPT = re.compile(r"^[A-Za-z0-9_:-]{1,200}$")


@dataclass(frozen=True, slots=True)
class VerticalDelivery:
    destination: VerticalDestination
    status: VerticalStatus
    receipt: str = ""

    def __post_init__(self) -> None:
        if self.destination not in {
            "instagram_story",
            "instagram_reel",
            "facebook_reel",
        }:
            raise ValueError("invalid vertical destination")
        if self.status not in {
            "success",
            "complete",
            "not_configured",
            "token_invalid",
            "delivery_failed",
            "media_invalid",
        }:
            raise ValueError("invalid vertical status")
        if not isinstance(self.receipt, str):
            raise ValueError("vertical receipt must be a string")
        if self.status == "success":
            if _SAFE_RECEIPT.fullmatch(self.receipt) is None:
                raise ValueError("vertical success requires a safe receipt")
        elif self.status == "complete":
            if self.receipt and _SAFE_RECEIPT.fullmatch(self.receipt) is None:
                raise ValueError("vertical complete receipt must be safe")
        elif self.receipt:
            raise ValueError("failed vertical delivery cannot contain a receipt")


class _HttpSession(Protocol):
    def post(self, url: str, **kwargs: object) -> object: ...

    def get(self, url: str, **kwargs: object) -> object: ...


class VerticalMetaHttpTransport:
    def __init__(
        self,
        *,
        session: _HttpSession | None = None,
        sleep: Callable[[float], object] = time.sleep,
        poll_interval: float = 2.0,
    ) -> None:
        if (
            isinstance(poll_interval, bool)
            or not isinstance(poll_interval, (int, float))
            or not math.isfinite(poll_interval)
            or poll_interval <= 0
            or poll_interval > 60
        ):
            raise ValueError("poll interval is invalid")
        self._session = (
            session if session is not None else cast(_HttpSession, requests.Session())
        )
        self._sleep = sleep
        self._poll_interval = float(poll_interval)

    def _post(
        self, url: str, settings: MetaSettings, data: dict[str, str]
    ) -> tuple[int, object]:
        response = cast(
            MetaResponse,
            self._session.post(
                url,
                headers=meta_auth_headers(settings.token),
                data=data,
                timeout=30,
                stream=True,
            ),
        )
        return read_meta_json(response)

    def _wait_for_container(
        self,
        container_id: str,
        *,
        settings: MetaSettings,
        destination: VerticalDestination,
    ) -> VerticalDelivery | None:
        for index in range(5):
            response = cast(
                MetaResponse,
                self._session.get(
                    meta_graph_url(settings, f"{container_id}?fields=status_code"),
                    headers=meta_auth_headers(settings.token),
                    timeout=30,
                    stream=True,
                ),
            )
            status, payload = read_meta_json(response)
            failure = _meta_failure(destination, status, payload)
            if failure is not None:
                return failure
            media_status = (
                payload.get("status_code") if isinstance(payload, Mapping) else None
            )
            if media_status == "FINISHED":
                return None
            if media_status != "IN_PROGRESS" or index == 4:
                return VerticalDelivery(destination, "delivery_failed")
            self._sleep(self._poll_interval)
        return VerticalDelivery(destination, "delivery_failed")

    def publish_instagram_story(
        self, *, image_url: str, settings: MetaSettings
    ) -> VerticalDelivery:
        destination: VerticalDestination = "instagram_story"
        if not settings.token or not settings.instagram_user_id:
            return VerticalDelivery(destination, "not_configured")
        if not _validated_vertical_url(image_url, suffix=".jpg"):
            return VerticalDelivery(destination, "media_invalid")
        try:
            created = self._post(
                meta_graph_url(settings, f"{settings.instagram_user_id}/media"),
                settings,
                {"image_url": image_url, "media_type": "STORIES"},
            )
            container = _required_id(created, destination=destination)
            if isinstance(container, VerticalDelivery):
                return container
            status = self._wait_for_container(
                container,
                settings=settings,
                destination=destination,
            )
            if status is not None:
                return status
            published = self._post(
                meta_graph_url(settings, f"{settings.instagram_user_id}/media_publish"),
                settings,
                {"creation_id": container},
            )
            receipt = _required_id(published, destination=destination)
            if isinstance(receipt, VerticalDelivery):
                return receipt
            return VerticalDelivery(destination, "success", receipt)
        except Exception:
            return VerticalDelivery(destination, "delivery_failed")


def _required_id(
    response: tuple[int, object], *, destination: VerticalDestination
) -> str | VerticalDelivery:
    status, payload = response
    failure = _meta_failure(destination, status, payload)
    if failure is not None:
        return failure
    receipt = safe_meta_id(payload)
    if receipt is None:
        return VerticalDelivery(destination, "delivery_failed")
    return receipt


def _meta_failure(
    destination: VerticalDestination, status: int, payload: object
) -> VerticalDelivery | None:
    if meta_token_invalid(payload):
        return VerticalDelivery(destination, "token_invalid")
    if status < 200 or status >= 300:
        return VerticalDelivery(destination, "delivery_failed")
    return None


def _validated_vertical_url(value: object, *, suffix: str) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(unicode_category(character) in {"Cc", "Cf"} for character in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and isinstance(parsed.hostname, str)
        and parsed.hostname.endswith(".supabase.co")
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path.startswith("/storage/v1/object/public/social-vertical/")
        and parsed.path.endswith(suffix)
        and not parsed.query
        and not parsed.fragment
    )

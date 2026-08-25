"""Bounded Meta Graph transport for vertical social media."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
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
    "pending_review",
]
VerticalDestination = Literal[
    "instagram_story",
    "instagram_reel",
    "facebook_reel",
]
_SAFE_RECEIPT = re.compile(r"^[A-Za-z0-9_:-]{1,200}$")
LOGGER = logging.getLogger(__name__)


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
            "pending_review",
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
        poll_interval: float = 60.0,
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
                allow_redirects=False,
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
                    allow_redirects=False,
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
        except Exception:
            return VerticalDelivery(destination, "delivery_failed")
        try:
            published = self._post(
                meta_graph_url(settings, f"{settings.instagram_user_id}/media_publish"),
                settings,
                {"creation_id": container},
            )
        except Exception:
            return VerticalDelivery(destination, "pending_review")
        try:
            receipt = _required_publish_id(published, destination=destination)
            if isinstance(receipt, VerticalDelivery):
                return receipt
            return VerticalDelivery(destination, "success", receipt)
        except Exception:
            return VerticalDelivery(destination, "pending_review")

    def publish_instagram_reel(
        self,
        *,
        video_url: str,
        settings: MetaSettings,
        description: str,
    ) -> VerticalDelivery:
        destination: VerticalDestination = "instagram_reel"
        if not settings.token or not settings.instagram_user_id:
            return VerticalDelivery(destination, "not_configured")
        if not _validated_vertical_url(
            video_url,
            suffix=".mp4",
        ) or not _valid_description(description):
            return VerticalDelivery(destination, "media_invalid")
        try:
            created = self._post(
                meta_graph_url(settings, f"{settings.instagram_user_id}/media"),
                settings,
                {
                    "video_url": video_url,
                    "media_type": "REELS",
                    "share_to_feed": "true",
                    "caption": description,
                },
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
        except Exception:
            return VerticalDelivery(destination, "delivery_failed")
        try:
            published = self._post(
                meta_graph_url(settings, f"{settings.instagram_user_id}/media_publish"),
                settings,
                {"creation_id": container},
            )
        except Exception:
            return VerticalDelivery(destination, "pending_review")
        try:
            receipt = _required_publish_id(published, destination=destination)
            if isinstance(receipt, VerticalDelivery):
                return receipt
            return VerticalDelivery(destination, "success", receipt)
        except Exception:
            return VerticalDelivery(destination, "pending_review")

    def publish_facebook_reel(
        self,
        *,
        mp4: bytes,
        settings: MetaSettings,
        description: str,
    ) -> VerticalDelivery:
        destination: VerticalDestination = "facebook_reel"
        if not settings.token or not settings.facebook_page_id:
            return VerticalDelivery(destination, "not_configured")
        if not _valid_mp4(mp4) or not _valid_description(description):
            return VerticalDelivery(destination, "media_invalid")
        stage = "page_token"
        try:
            page_token = self._resolve_page_token(settings)
            if isinstance(page_token, VerticalDelivery):
                return page_token
            stage = "start"
            start_response = cast(
                MetaResponse,
                self._session.post(
                    meta_graph_url(
                        settings,
                        f"{settings.facebook_page_id}/video_reels",
                    ),
                    headers=meta_auth_headers(page_token),
                    data={"upload_phase": "start"},
                    timeout=30,
                    stream=True,
                    allow_redirects=False,
                ),
            )
            start_status, start_payload = read_meta_json(start_response)
            failure = _meta_failure(destination, start_status, start_payload)
            if failure is not None:
                _log_meta_failure(
                    destination,
                    stage=stage,
                    status=start_status,
                    payload=start_payload,
                    reason="http_failure",
                )
                return failure
            start = _safe_reel_start(start_payload)
            if start is None:
                _log_meta_failure(
                    destination,
                    stage=stage,
                    status=start_status,
                    payload=start_payload,
                    reason="response_shape",
                )
                return VerticalDelivery(destination, "delivery_failed")
            video_id, upload_url = start
            if not _exact_rupload_url(
                upload_url,
                video_id=video_id,
                version=settings.graph_version,
            ):
                _log_meta_failure(
                    destination,
                    stage=stage,
                    status=start_status,
                    payload=start_payload,
                    reason="upload_url",
                )
                return VerticalDelivery(destination, "delivery_failed")
            stage = "upload"
            upload_response = cast(
                MetaResponse,
                self._session.post(
                    upload_url,
                    headers={
                        "Authorization": f"OAuth {page_token}",
                        "offset": "0",
                        "file_size": str(len(mp4)),
                        "Content-Type": "application/octet-stream",
                        "Accept-Encoding": "identity",
                    },
                    data=mp4,
                    timeout=90,
                    stream=True,
                    allow_redirects=False,
                ),
            )
            upload_status, upload_payload = read_meta_json(upload_response)
            if (
                upload_status < 200
                or upload_status >= 300
                or not _safe_upload_success(upload_payload)
            ):
                _log_meta_failure(
                    destination,
                    stage=stage,
                    status=upload_status,
                    payload=upload_payload,
                    reason="upload_failed",
                )
                return VerticalDelivery(destination, "delivery_failed")
            stage = "finish"
            finish_response = cast(
                MetaResponse,
                self._session.post(
                    meta_graph_url(
                        settings,
                        f"{settings.facebook_page_id}/video_reels",
                    ),
                    headers=meta_auth_headers(page_token),
                    data={
                        "upload_phase": "finish",
                        "video_id": video_id,
                        "video_state": "PUBLISHED",
                        "description": description,
                    },
                    timeout=30,
                    stream=True,
                    allow_redirects=False,
                ),
            )
            finish_status, finish_payload = read_meta_json(finish_response)
        except Exception as exc:
            LOGGER.warning(
                "vertical meta status=ambiguous destination=%s stage=%s "
                "exception=%s",
                destination,
                stage,
                type(exc).__name__,
            )
            return VerticalDelivery(destination, "pending_review")
        if meta_token_invalid(finish_payload):
            _log_meta_failure(
                destination,
                stage="finish",
                status=finish_status,
                payload=finish_payload,
                reason="token_invalid",
            )
            return VerticalDelivery(destination, "token_invalid")
        if finish_status < 200 or finish_status >= 300:
            _log_meta_failure(
                destination,
                stage="finish",
                status=finish_status,
                payload=finish_payload,
                reason="http_failure",
            )
            return VerticalDelivery(
                destination,
                "delivery_failed" if finish_status < 500 else "pending_review",
            )
        if finish_payload != {"success": True}:
            _log_meta_failure(
                destination,
                stage="finish",
                status=finish_status,
                payload=finish_payload,
                reason="response_shape",
            )
            return VerticalDelivery(destination, "pending_review")
        return VerticalDelivery(destination, "success", video_id)

    def _resolve_page_token(
        self,
        settings: MetaSettings,
    ) -> str | VerticalDelivery:
        destination: VerticalDestination = "facebook_reel"
        response = cast(
            MetaResponse,
            self._session.get(
                meta_graph_url(
                    settings,
                    f"{settings.facebook_page_id}?fields=access_token",
                ),
                headers=meta_auth_headers(settings.token),
                timeout=30,
                stream=True,
                allow_redirects=False,
            ),
        )
        status, payload = read_meta_json(response)
        failure = _meta_failure(destination, status, payload)
        if failure is not None:
            _log_meta_failure(
                destination,
                stage="page_token",
                status=status,
                payload=payload,
                reason="http_failure",
            )
            return failure
        if (
            not isinstance(payload, Mapping)
            or "access_token" not in payload
            or not set(payload).issubset({"access_token", "id"})
        ):
            _log_meta_failure(
                destination,
                stage="page_token",
                status=status,
                payload=payload,
                reason="response_shape",
            )
            return VerticalDelivery(destination, "delivery_failed")
        returned_page_id = payload.get("id")
        if returned_page_id is not None and returned_page_id != settings.facebook_page_id:
            _log_meta_failure(
                destination,
                stage="page_token",
                status=status,
                payload=payload,
                reason="page_mismatch",
            )
            return VerticalDelivery(destination, "delivery_failed")
        value = payload["access_token"]
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value) > 4096
            or any(unicode_category(char) in {"Cc", "Cf"} for char in value)
        ):
            _log_meta_failure(
                destination,
                stage="page_token",
                status=status,
                payload=payload,
                reason="token_shape",
            )
            return VerticalDelivery(destination, "delivery_failed")
        return value


def _log_meta_failure(
    destination: VerticalDestination,
    *,
    stage: str,
    status: int,
    payload: object,
    reason: str,
) -> None:
    error_code = "none"
    error_subcode = "none"
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            code = error.get("code")
            subcode = error.get("error_subcode")
            if type(code) is int and 0 <= code <= 2_147_483_647:
                error_code = str(code)
            if type(subcode) is int and 0 <= subcode <= 2_147_483_647:
                error_subcode = str(subcode)
    LOGGER.warning(
        "vertical meta status=failed destination=%s stage=%s http_status=%s "
        "error_code=%s error_subcode=%s reason=%s",
        destination,
        stage,
        status,
        error_code,
        error_subcode,
        reason,
    )


def _safe_upload_success(payload: object) -> bool:
    if (
        not isinstance(payload, Mapping)
        or payload.get("success") is not True
        or not set(payload).issubset({"success", "h"})
    ):
        return False
    upload_hash = payload.get("h")
    return upload_hash is None or bool(
        isinstance(upload_hash, str)
        and 1 <= len(upload_hash) <= 1024
        and all(
            unicode_category(character) not in {"Cc", "Cf"}
            for character in upload_hash
        )
    )


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


def _required_publish_id(
    response: tuple[int, object], *, destination: VerticalDestination
) -> str | VerticalDelivery:
    status, payload = response
    if meta_token_invalid(payload):
        return VerticalDelivery(destination, "token_invalid")
    if 400 <= status < 500:
        return VerticalDelivery(destination, "delivery_failed")
    if status < 200 or status >= 300:
        return VerticalDelivery(destination, "pending_review")
    receipt = safe_meta_id(payload)
    if receipt is None:
        return VerticalDelivery(destination, "pending_review")
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


def _valid_mp4(value: object) -> bool:
    return bool(
        isinstance(value, bytes)
        and 12 <= len(value) <= 50 * 1024 * 1024
        and value[4:8] == b"ftyp"
    )


def _valid_description(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value
        and value == value.strip()
        and len(value) <= 2200
        and all(
            character in {"\n", "\t"}
            or unicode_category(character) not in {"Cc", "Cf"}
            for character in value
        )
    )


def _safe_reel_start(payload: object) -> tuple[str, str] | None:
    if not isinstance(payload, Mapping) or set(payload) != {"video_id", "upload_url"}:
        return None
    video_id = payload["video_id"]
    upload_url = payload["upload_url"]
    if (
        not isinstance(video_id, str)
        or _SAFE_RECEIPT.fullmatch(video_id) is None
        or not isinstance(upload_url, str)
    ):
        return None
    return video_id, upload_url


def _exact_rupload_url(
    value: str,
    *,
    video_id: str,
    version: str,
) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (AttributeError, ValueError):
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname == "rupload.facebook.com"
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path == f"/video-upload/{version}/{video_id}"
        and not parsed.query
        and not parsed.fragment
    )

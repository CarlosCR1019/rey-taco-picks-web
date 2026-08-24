"""Publish one exact audited public pick through the Meta Graph API."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import logging
import math
import os
from pathlib import Path
import re
import time
from typing import Literal, Protocol, cast
from unicodedata import category as unicode_category
from urllib.parse import urlsplit
import warnings
from uuid import uuid4

from dotenv import dotenv_values
from PIL import Image, UnidentifiedImageError
import requests

from backend.render_html_banner import render_social_jpeg
from backend.social_background import CloudflareBackgroundProvider
from backend.social_content import SocialCaptions, SocialContent, build_fallback_captions
from backend.social_copy import (
    CaptionProvider,
    GroqCopyProvider,
    validate_social_captions,
)
from backend.social_repository import MetaSocialBatch, SocialRepository, SupabaseSocialRepository


LOGGER = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parent
_GRAPH_VERSION = re.compile(r"^v[0-9]+[.][0-9]+$")
_ASCII_ID = re.compile(r"^[0-9]+$")
_SAFE_RECEIPT = re.compile(r"^[A-Za-z0-9_:-]{1,200}$")
_MAX_META_RESPONSE_BYTES = 256 * 1024
_META_RESPONSE_CHUNK_BYTES = 64 * 1024

MetaStatus = Literal[
    "success", "skipped", "not_configured", "token_invalid", "delivery_failed"
]
Destination = Literal["facebook", "instagram"]


@dataclass(frozen=True, slots=True)
class MetaDelivery:
    destination: Destination
    status: MetaStatus
    receipt: str = ""

    def __post_init__(self) -> None:
        if self.destination not in {"facebook", "instagram"}:
            raise ValueError("invalid Meta destination")
        if self.status not in {
            "success", "skipped", "not_configured", "token_invalid", "delivery_failed"
        }:
            raise ValueError("invalid Meta status")
        if not isinstance(self.receipt, str):
            raise ValueError("receipt must be a string")
        if self.status == "success" and _SAFE_RECEIPT.fullmatch(self.receipt) is None:
            raise ValueError("success requires a safe receipt")
        if self.status == "skipped":
            if self.receipt and _SAFE_RECEIPT.fullmatch(self.receipt) is None:
                raise ValueError("skipped receipt must be safe")
        elif self.status != "success" and self.receipt:
            raise ValueError("failed delivery cannot contain a receipt")

    @property
    def success(self) -> bool:
        return self.status in {"success", "skipped"}


@dataclass(frozen=True, slots=True)
class MetaSettings:
    token: str = field(repr=False)
    facebook_page_id: str
    instagram_user_id: str
    graph_version: str = "v26.0"
    dry_run: bool = False
    dry_run_output: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.token, str):
            raise ValueError("META_SYSTEM_USER_ACCESS_TOKEN must be a string")
        if not isinstance(self.facebook_page_id, str):
            raise ValueError("FB_PAGE_ID must contain ASCII digits")
        if not isinstance(self.instagram_user_id, str):
            raise ValueError("IG_USER_ID must contain ASCII digits")
        _optional_secret(self.token)
        _optional_id(self.facebook_page_id, field="FB_PAGE_ID")
        _optional_id(self.instagram_user_id, field="IG_USER_ID")
        if (
            not isinstance(self.graph_version, str)
            or _GRAPH_VERSION.fullmatch(self.graph_version) is None
        ):
            raise ValueError("META_GRAPH_VERSION must use v<major>.<minor>")
        if type(self.dry_run) is not bool:
            raise ValueError("META_DRY_RUN must be true or false")
        if (
            not isinstance(self.dry_run_output, str)
            or _has_forbidden_control(self.dry_run_output)
            or self.dry_run_output != self.dry_run_output.strip()
        ):
            raise ValueError("META_DRY_RUN_OUTPUT must be a safe path")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "MetaSettings":
        token = _optional_secret(values.get("META_SYSTEM_USER_ACCESS_TOKEN"))
        facebook_page_id = _optional_id(values.get("FB_PAGE_ID"), field="FB_PAGE_ID")
        instagram_user_id = _optional_id(values.get("IG_USER_ID"), field="IG_USER_ID")
        raw_version = values.get("META_GRAPH_VERSION", "v26.0")
        if not isinstance(raw_version, str) or _GRAPH_VERSION.fullmatch(raw_version) is None:
            raise ValueError("META_GRAPH_VERSION must use v<major>.<minor>")
        dry_run = _parse_boolean(values.get("META_DRY_RUN"), field="META_DRY_RUN")
        raw_output = values.get("META_DRY_RUN_OUTPUT", "")
        if raw_output is None:
            raw_output = ""
        if (
            not isinstance(raw_output, str)
            or _has_forbidden_control(raw_output)
            or raw_output != raw_output.strip()
        ):
            raise ValueError("META_DRY_RUN_OUTPUT must be a safe path")
        return cls(
            token=token,
            facebook_page_id=facebook_page_id,
            instagram_user_id=instagram_user_id,
            graph_version=raw_version,
            dry_run=dry_run,
            dry_run_output=raw_output,
        )


def _optional_secret(value: object) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError("META_SYSTEM_USER_ACCESS_TOKEN must be a string")
    if not value.strip():
        return ""
    if value != value.strip() or _has_forbidden_control(value):
        raise ValueError("META_SYSTEM_USER_ACCESS_TOKEN is unsafe")
    return value


def _optional_id(value: object, *, field: str) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must contain ASCII digits")
    if not value.strip():
        return ""
    if value != value.strip() or _ASCII_ID.fullmatch(value) is None:
        raise ValueError(f"{field} must contain ASCII digits")
    return value


def _parse_boolean(value: object, *, field: str) -> bool:
    if value is None or value == "" or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, str):
        folded = value.casefold()
        if folded in {"true", "1", "yes"}:
            return True
        if folded in {"false", "0", "no"}:
            return False
    raise ValueError(f"{field} must be true or false")


def _has_forbidden_control(value: str, *, allow_newline: bool = False) -> bool:
    return any(
        unicode_category(character) in {"Cc", "Cf"}
        and not (allow_newline and character == "\n")
        for character in value
    )


class _HttpResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def iter_content(self, chunk_size: int) -> Iterable[bytes]: ...

    def close(self) -> None: ...


class _HttpSession(Protocol):
    def post(self, url: str, **kwargs: object) -> object: ...

    def get(self, url: str, **kwargs: object) -> object: ...


class MetaHttpTransport:
    """Small injectable and sanitized Meta Graph transport."""

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
            raise ValueError("poll_interval must be finite, positive, and at most 60")
        self._session = (
            session if session is not None else cast(_HttpSession, requests.Session())
        )
        self._sleep = sleep
        self._poll_interval = float(poll_interval)

    def publish_facebook(
        self, *, jpeg: bytes, caption: str, settings: MetaSettings
    ) -> MetaDelivery:
        destination: Destination = "facebook"
        if not settings.token or not settings.facebook_page_id:
            return self._result(destination, "not_configured")
        if not isinstance(jpeg, bytes) or not jpeg or not _valid_caption(caption):
            return self._result(destination, "delivery_failed")
        try:
            response = cast(
                _HttpResponse,
                self._session.post(
                    self._graph_url(settings, f"{settings.facebook_page_id}/photos"),
                    headers=self._headers(settings),
                    data={"message": caption},
                    files={"source": ("rey-taco-pick.jpg", jpeg, "image/jpeg")},
                    timeout=30,
                    stream=True,
                ),
            )
            status, payload = _response_payload(response)
            if status < 200 or status >= 300:
                _log_meta_http_failure(destination, status=status, payload=payload)
            if _is_token_invalid(payload):
                return self._result(destination, "token_invalid")
            if status < 200 or status >= 300:
                return self._result(destination, "delivery_failed")
            receipt = _safe_id(payload)
            if receipt is None:
                return self._result(destination, "delivery_failed")
            return self._result(destination, "success", receipt=receipt)
        except Exception as exc:
            return self._result(destination, "delivery_failed", exception=type(exc).__name__)

    def publish_instagram(
        self, *, image_url: str, caption: str, settings: MetaSettings
    ) -> MetaDelivery:
        destination: Destination = "instagram"
        if not settings.token or not settings.instagram_user_id:
            return self._result(destination, "not_configured")
        if not _is_public_jpeg_url(image_url) or not _valid_caption(caption):
            return self._result(destination, "delivery_failed")
        try:
            create_response = cast(
                _HttpResponse,
                self._session.post(
                    self._graph_url(settings, f"{settings.instagram_user_id}/media"),
                    headers=self._headers(settings),
                    data={"image_url": image_url, "caption": caption},
                    timeout=30,
                    stream=True,
                ),
            )
            status, payload = _response_payload(create_response)
            failed = self._http_failure(destination, status=status, payload=payload)
            if failed is not None:
                return failed
            container_id = _safe_id(payload)
            if container_id is None:
                return self._result(destination, "delivery_failed")

            for poll_index in range(5):
                poll_response = cast(
                    _HttpResponse,
                    self._session.get(
                        self._graph_url(settings, f"{container_id}?fields=status_code"),
                        headers=self._headers(settings),
                        timeout=30,
                        stream=True,
                    ),
                )
                poll_status, poll_payload = _response_payload(poll_response)
                failed = self._http_failure(
                    destination, status=poll_status, payload=poll_payload
                )
                if failed is not None:
                    return failed
                media_status = (
                    poll_payload.get("status_code")
                    if isinstance(poll_payload, Mapping)
                    else None
                )
                if media_status == "FINISHED":
                    break
                if media_status != "IN_PROGRESS":
                    return self._result(destination, "delivery_failed")
                if poll_index == 4:
                    return self._result(destination, "delivery_failed")
                self._sleep(self._poll_interval)

            publish_response = cast(
                _HttpResponse,
                self._session.post(
                    self._graph_url(settings, f"{settings.instagram_user_id}/media_publish"),
                    headers=self._headers(settings),
                    data={"creation_id": container_id},
                    timeout=30,
                    stream=True,
                ),
            )
            publish_status, publish_payload = _response_payload(publish_response)
            failed = self._http_failure(
                destination, status=publish_status, payload=publish_payload
            )
            if failed is not None:
                return failed
            receipt = _safe_id(publish_payload)
            if receipt is None:
                return self._result(destination, "delivery_failed")
            return self._result(destination, "success", receipt=receipt)
        except Exception as exc:
            return self._result(destination, "delivery_failed", exception=type(exc).__name__)

    @staticmethod
    def _headers(settings: MetaSettings) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.token}",
            # iter_content yields decoded bytes; identity keeps Content-Length
            # comparable to the bytes counted by the bounded parser.
            "Accept-Encoding": "identity",
        }

    @staticmethod
    def _graph_url(settings: MetaSettings, path: str) -> str:
        return f"https://graph.facebook.com/{settings.graph_version}/{path}"

    def _http_failure(
        self, destination: Destination, *, status: int, payload: object
    ) -> MetaDelivery | None:
        if status < 200 or status >= 300:
            _log_meta_http_failure(destination, status=status, payload=payload)
        if _is_token_invalid(payload):
            return self._result(destination, "token_invalid")
        if status < 200 or status >= 300:
            return self._result(destination, "delivery_failed")
        return None

    @staticmethod
    def _result(
        destination: Destination,
        status: MetaStatus,
        *,
        receipt: str = "",
        exception: str = "",
    ) -> MetaDelivery:
        result = MetaDelivery(destination, status, receipt)
        if status == "success":
            LOGGER.info("meta destination=%s status=success receipt=%s", destination, receipt)
        elif exception:
            LOGGER.info(
                "meta destination=%s status=%s exception=%s",
                destination,
                status,
                exception,
            )
        else:
            LOGGER.info("meta destination=%s status=%s", destination, status)
        return result


def _response_payload(response: _HttpResponse) -> tuple[int, object]:
    try:
        status = response.status_code
        if type(status) is not int:
            raise ValueError("invalid HTTP status")
        headers = response.headers
        if not isinstance(headers, Mapping):
            raise ValueError("invalid response headers")
        declared_text = headers.get("Content-Length")
        declared_length: int | None = None
        if declared_text is not None:
            if (
                not isinstance(declared_text, str)
                or re.fullmatch(r"(?:0|[1-9][0-9]*)", declared_text) is None
            ):
                raise ValueError("invalid Content-Length")
            declared_length = int(declared_text)
            if declared_length > _MAX_META_RESPONSE_BYTES:
                raise ValueError("Meta response body is oversized")
        body = bytearray()
        chunks = response.iter_content(chunk_size=_META_RESPONSE_CHUNK_BYTES)
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise ValueError("invalid Meta response chunk")
            if not chunk:
                continue
            remaining = _MAX_META_RESPONSE_BYTES - len(body)
            if declared_length is not None:
                remaining = min(remaining, declared_length - len(body))
            if len(chunk) > remaining:
                raise ValueError("Meta response body is oversized")
            body.extend(chunk)
        if declared_length is not None and len(body) != declared_length:
            raise ValueError("Meta response Content-Length mismatch")
        payload = json.loads(bytes(body).decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("invalid JSON response")
        return status, payload
    finally:
        response.close()


def _is_token_invalid(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return False
    return error.get("code") == 190


def _log_meta_http_failure(
    destination: Destination, *, status: int, payload: object
) -> None:
    error_code: int | str = "unknown"
    error_subcode: int | str = "unknown"
    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            raw_code = error.get("code")
            raw_subcode = error.get("error_subcode")
            if type(raw_code) is int:
                error_code = raw_code
            if type(raw_subcode) is int:
                error_subcode = raw_subcode
    LOGGER.info(
        "meta destination=%s http_status=%s error_code=%s error_subcode=%s",
        destination,
        status,
        error_code,
        error_subcode,
    )


def _safe_id(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("id")
    if not isinstance(value, str) or _SAFE_RECEIPT.fullmatch(value) is None:
        return None
    return value


def _valid_caption(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value == value.strip()
        and not _has_forbidden_control(value, allow_newline=True)
    )


def _is_public_jpeg_url(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or _has_forbidden_control(value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
        and parsed.path.endswith(".jpg")
        and not parsed.query
        and not parsed.fragment
    )


def _is_deterministic_public_url(value: object, *, object_key: str) -> bool:
    if not _is_public_jpeg_url(value) or not isinstance(value, str):
        return False
    return urlsplit(value).path.endswith(f"/{object_key}")


def _ledger_skip(batch: MetaSocialBatch, destination: Destination) -> MetaDelivery | None:
    entry = batch.delivery_status.get(destination)
    if not isinstance(entry, Mapping) or entry.get("success") is not True:
        return None
    receipt = entry.get("receipt")
    if not isinstance(receipt, str) or _SAFE_RECEIPT.fullmatch(receipt) is None:
        return None
    return MetaDelivery(destination, "skipped", receipt)


def _configured(settings: MetaSettings, destination: Destination) -> bool:
    return bool(
        settings.token
        and (
            settings.facebook_page_id
            if destination == "facebook"
            else settings.instagram_user_id
        )
    )


def _validate_rendered_jpeg(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) > 5 * 1024 * 1024:
        raise ValueError("renderer returned invalid JPEG")
    if not value.startswith(b"\xff\xd8") or not value.endswith(b"\xff\xd9"):
        raise ValueError("renderer returned invalid JPEG")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(value)) as image:
                image.load()
                if image.format != "JPEG" or image.mode != "RGB" or image.size != (1080, 1080):
                    raise ValueError("renderer returned invalid JPEG")
    except (
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ValueError("renderer returned invalid JPEG") from None
    return value


def _safe_captions(provider: CaptionProvider, content: SocialContent) -> SocialCaptions:
    fallback = build_fallback_captions(content)
    try:
        candidate = provider.captions(content)
        return validate_social_captions(candidate, content)
    except Exception as exc:
        LOGGER.info("meta copy=fallback exception=%s", type(exc).__name__)
        return fallback


def _safe_background(provider: object | None) -> bytes | None:
    if provider is None:
        return None
    try:
        create = getattr(provider, "create")
        result = create()
        return result if isinstance(result, bytes) else None
    except Exception as exc:
        LOGGER.info("meta background=fallback exception=%s", type(exc).__name__)
        return None


def _claim_destination(
    repository: SocialRepository,
    *,
    run_id: str,
    destination: Destination,
) -> tuple[MetaDelivery | None, str | None]:
    """Claim immediately before Meta delivery or terminal ledger completion."""

    attempt_id = str(uuid4())
    lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=9)
    try:
        claimed = repository.claim_destination(
            run_id=run_id,
            destination=destination,
            attempt_id=attempt_id,
            lease_expires_at=lease_expires_at,
        )
        if type(claimed) is not bool:
            raise ValueError("claim returned an invalid result")
    except Exception as exc:
        LOGGER.info(
            "meta destination=%s claim=delivery_failed exception=%s",
            destination,
            type(exc).__name__,
        )
        return MetaDelivery(destination, "delivery_failed"), None
    if not claimed:
        LOGGER.info("meta destination=%s claim=skipped", destination)
        return MetaDelivery(destination, "skipped"), None
    return None, attempt_id


def _complete_claim(
    repository: SocialRepository,
    *,
    run_id: str,
    result: MetaDelivery,
    attempt_id: str,
) -> MetaDelivery:
    """Persist one claimed outcome without blocking the sibling destination."""

    try:
        repository.record_delivery(
            run_id=run_id,
            result=result,
            attempt_id=attempt_id,
        )
    except Exception as exc:
        LOGGER.info(
            "meta destination=%s ledger=delivery_failed exception=%s",
            result.destination,
            type(exc).__name__,
        )
        return MetaDelivery(result.destination, "delivery_failed")
    return result


def _claim_and_complete(
    repository: SocialRepository,
    *,
    run_id: str,
    result: MetaDelivery,
) -> MetaDelivery:
    claim_result, attempt_id = _claim_destination(
        repository,
        run_id=run_id,
        destination=result.destination,
    )
    if claim_result is not None:
        return claim_result
    if attempt_id is None:
        return MetaDelivery(result.destination, "delivery_failed")
    return _complete_claim(
        repository,
        run_id=run_id,
        result=result,
        attempt_id=attempt_id,
    )


def publish_meta(
    *,
    run_key: str,
    reference_at: datetime,
    settings: MetaSettings,
    repository: SocialRepository,
    transport: MetaHttpTransport,
    copy_provider: CaptionProvider,
    background_provider: object | None,
) -> tuple[MetaDelivery, MetaDelivery]:
    """Publish or skip both destinations for one exact persisted run."""

    exact_batch = repository.get_batch(run_key=run_key, reference_at=reference_at)
    if exact_batch is None:
        LOGGER.info("meta batch=no_batch")
        return MetaDelivery("facebook", "skipped"), MetaDelivery("instagram", "skipped")

    destinations: tuple[Destination, Destination] = ("facebook", "instagram")
    results: dict[Destination, MetaDelivery] = {}
    for destination in destinations:
        prior = _ledger_skip(exact_batch, destination)
        if prior is not None:
            results[destination] = prior
    if len(results) == 2 and not settings.dry_run:
        return results["facebook"], results["instagram"]

    if exact_batch.content.is_demo:
        for destination in destinations:
            if destination in results:
                continue
            failure = MetaDelivery(destination, "delivery_failed")
            if not settings.dry_run:
                failure = _claim_and_complete(
                    repository,
                    run_id=exact_batch.run_id,
                    result=failure,
                )
            results[destination] = failure
        return results["facebook"], results["instagram"]

    if not settings.dry_run:
        for destination in destinations:
            if destination in results or _configured(settings, destination):
                continue
            missing = MetaDelivery(destination, "not_configured")
            results[destination] = _claim_and_complete(
                repository,
                run_id=exact_batch.run_id,
                result=missing,
            )
        if len(results) == 2:
            return results["facebook"], results["instagram"]

    try:
        captions = _safe_captions(copy_provider, exact_batch.content)
    except Exception as exc:
        LOGGER.info("meta copy=status_failed exception=%s", type(exc).__name__)
        for destination in destinations:
            if destination in results:
                continue
            failure = MetaDelivery(destination, "delivery_failed")
            if not settings.dry_run:
                failure = _claim_and_complete(
                    repository,
                    run_id=exact_batch.run_id,
                    result=failure,
                )
            results[destination] = failure
        return results["facebook"], results["instagram"]

    background = _safe_background(background_provider)
    try:
        jpeg = _validate_rendered_jpeg(
            render_social_jpeg(
                exact_batch.content,
                generated_at=reference_at,
                background_bytes=background,
            )
        )
    except Exception as exc:
        LOGGER.info("meta render=status_failed exception=%s", type(exc).__name__)
        for destination in destinations:
            if destination in results:
                continue
            failure = MetaDelivery(destination, "delivery_failed")
            if not settings.dry_run:
                failure = _claim_and_complete(
                    repository,
                    run_id=exact_batch.run_id,
                    result=failure,
                )
            results[destination] = failure
        return results["facebook"], results["instagram"]

    if settings.dry_run:
        if settings.dry_run_output:
            Path(settings.dry_run_output).write_bytes(jpeg)
        LOGGER.info("meta dry_run=ready")
        return (
            results.get("facebook", MetaDelivery("facebook", "skipped")),
            results.get("instagram", MetaDelivery("instagram", "skipped")),
        )

    if "facebook" not in results:
        claim_result, attempt_id = _claim_destination(
            repository, run_id=exact_batch.run_id, destination="facebook"
        )
        if claim_result is not None or attempt_id is None:
            results["facebook"] = claim_result or MetaDelivery(
                "facebook", "delivery_failed"
            )
        else:
            try:
                facebook = transport.publish_facebook(
                    jpeg=jpeg, caption=captions.facebook, settings=settings
                )
                if facebook.destination != "facebook":
                    raise ValueError("transport returned wrong destination")
            except Exception as exc:
                LOGGER.info(
                    "meta destination=facebook status=delivery_failed exception=%s",
                    type(exc).__name__,
                )
                facebook = MetaDelivery("facebook", "delivery_failed")
            results["facebook"] = _complete_claim(
                repository,
                run_id=exact_batch.run_id,
                result=facebook,
                attempt_id=attempt_id,
            )

    if "instagram" not in results:
        try:
            image_url = repository.upload_jpeg(batch=exact_batch, jpeg=jpeg)
            object_key = exact_batch.content.object_key(batch_id=exact_batch.batch_id)
            if not _is_deterministic_public_url(image_url, object_key=object_key):
                raise ValueError("storage returned a non-deterministic URL")
        except Exception as exc:
            LOGGER.info(
                "meta destination=instagram status=delivery_failed exception=%s",
                type(exc).__name__,
            )
            instagram = MetaDelivery("instagram", "delivery_failed")
            results["instagram"] = _claim_and_complete(
                repository,
                run_id=exact_batch.run_id,
                result=instagram,
            )
        else:
            claim_result, attempt_id = _claim_destination(
                repository, run_id=exact_batch.run_id, destination="instagram"
            )
            if claim_result is not None or attempt_id is None:
                results["instagram"] = claim_result or MetaDelivery(
                    "instagram", "delivery_failed"
                )
            else:
                try:
                    instagram = transport.publish_instagram(
                        image_url=image_url,
                        caption=captions.instagram,
                        settings=settings,
                    )
                    if instagram.destination != "instagram":
                        raise ValueError("transport returned wrong destination")
                except Exception as exc:
                    LOGGER.info(
                        "meta destination=instagram status=delivery_failed exception=%s",
                        type(exc).__name__,
                    )
                    instagram = MetaDelivery("instagram", "delivery_failed")
                results["instagram"] = _complete_claim(
                    repository,
                    run_id=exact_batch.run_id,
                    result=instagram,
                    attempt_id=attempt_id,
                )

    return results["facebook"], results["instagram"]


def exit_code_for(results: tuple[MetaDelivery, MetaDelivery]) -> int:
    return int(
        any(result.status in {"token_invalid", "delivery_failed"} for result in results)
    )


def resolve_run_key(values: Mapping[str, object]) -> str:
    explicit = values.get("SCRAPER_RUN_KEY")
    github_run_id = values.get("GITHUB_RUN_ID")
    for value, field_name in (
        (explicit, "SCRAPER_RUN_KEY"),
        (github_run_id, "GITHUB_RUN_ID"),
    ):
        if value is not None and (
            not isinstance(value, str)
            or value != value.strip()
            or _has_forbidden_control(value)
        ):
            raise ValueError(f"{field_name} is unsafe")
    if isinstance(explicit, str) and explicit:
        return explicit
    if isinstance(github_run_id, str) and github_run_id:
        return f"github-run:{github_run_id}"
    raise ValueError("exact run key is required")


def _runtime_values(environ: Mapping[str, str] | None) -> Mapping[str, object]:
    if environ is not None:
        return environ
    values: dict[str, object] = dict(dotenv_values(BACKEND_DIR / ".env"))
    values.update(os.environ)
    return values


def main(environ: Mapping[str, str] | None = None) -> int:
    """Build runtime adapters, execute the orchestrator, and return a process code."""

    try:
        values = _runtime_values(environ)
        settings = MetaSettings.from_mapping(values)
        run_key = resolve_run_key(values)
        supabase_url = values.get("SUPABASE_URL", "")
        service_role_key = values.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not isinstance(supabase_url, str) or not isinstance(service_role_key, str):
            raise ValueError("Supabase configuration is invalid")
        repository = SupabaseSocialRepository(
            supabase_url=supabase_url, service_role_key=service_role_key
        )
        groq_key = values.get("GROQ_API_KEY", "")
        groq_model = values.get("GROQ_CONTENT_MODEL", "openai/gpt-oss-20b")
        if not isinstance(groq_key, str) or not isinstance(groq_model, str):
            raise ValueError("Groq configuration is invalid")
        copy_provider = GroqCopyProvider(api_key=groq_key, model=groq_model)
        cf_account = values.get("CLOUDFLARE_ACCOUNT_ID", "")
        cf_token = values.get("CLOUDFLARE_AI_API_TOKEN", "")
        if not isinstance(cf_account, str) or not isinstance(cf_token, str):
            raise ValueError("Cloudflare configuration is invalid")
        background_provider: object | None = None
        if cf_account and cf_token:
            background_provider = CloudflareBackgroundProvider(
                account_id=cf_account,
                api_token=cf_token,
                session=requests.Session(),
            )
        results = publish_meta(
            run_key=run_key,
            reference_at=datetime.now(timezone.utc),
            settings=settings,
            repository=repository,
            transport=MetaHttpTransport(),
            copy_provider=copy_provider,
            background_provider=background_provider,
        )
        return exit_code_for(results)
    except Exception as exc:
        LOGGER.info("meta command=status_failed exception=%s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())

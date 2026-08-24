"""Idempotent multi-destination publishing for verified result reports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol
from urllib.parse import urlsplit

from backend.result_banner import render_result_jpeg
from backend.result_report_repository import Claim
from backend.result_reporting import ResultReport
from backend.social_poster import MetaDelivery, MetaSettings
from backend.telegram_publisher import TelegramDestination


ResultDestination = Literal["admin", "vip", "free", "facebook", "instagram"]


class ResultRepository(Protocol):
    def claim(self, **kwargs: object) -> Claim: ...

    def complete(self, **kwargs: object) -> None: ...


class TelegramTransport(Protocol):
    def __call__(self, destination: TelegramDestination, text: str) -> None: ...


class MetaTransport(Protocol):
    def publish_facebook(
        self,
        *,
        jpeg: bytes,
        caption: str,
        settings: MetaSettings,
    ) -> MetaDelivery: ...

    def publish_instagram(
        self,
        *,
        image_url: str,
        caption: str,
        settings: MetaSettings,
    ) -> MetaDelivery: ...


class ResultArtifactStore(Protocol):
    def upload(self, *, report: ResultReport, jpeg: bytes) -> str: ...


def destinations_for(kind: str) -> tuple[ResultDestination, ...]:
    if kind == "evening":
        return ("admin", "vip", "free")
    if kind == "final":
        return ("admin", "vip", "free", "facebook", "instagram")
    raise ValueError("result report kind must be evening or final")


def publish_result_report(
    report: ResultReport,
    *,
    repository: ResultRepository,
    telegram_transport: TelegramTransport | None,
    telegram_chats: Mapping[str, str],
    meta_transport: MetaTransport | None,
    meta_settings: MetaSettings | None,
    artifact_store: ResultArtifactStore | None,
) -> dict[str, str]:
    """Claim, deliver, and complete every destination independently."""
    if not isinstance(report, ResultReport) or not report.eligible:
        raise ValueError("one eligible result report is required")
    results: dict[str, str] = {}
    jpeg: bytes | None = None
    image_url: str | None = None

    for destination in destinations_for(report.kind):
        try:
            claim = repository.claim(
                batch_id=report.batch_id,
                portfolio_date=report.portfolio_date,
                report_kind=report.kind,
                destination=destination,
                report_digest=report.digest,
            )
        except Exception:
            results[destination] = "claim_failed"
            continue
        if claim.state != "claimed":
            results[destination] = claim.state
            continue
        if claim.attempt_id is None:
            results[destination] = "claim_failed"
            continue

        success = False
        receipt = ""
        error = "delivery_failed"
        try:
            if destination in {"admin", "vip", "free"}:
                chat_id = telegram_chats.get(destination, "").strip()
                if telegram_transport is None or not chat_id:
                    error = "not_configured"
                else:
                    telegram_transport(
                        TelegramDestination(destination, chat_id, "all"),
                        report.telegram,
                    )
                    success = True
                    receipt = f"telegram:{destination}"
            elif destination == "facebook":
                if meta_transport is None or meta_settings is None:
                    error = "not_configured"
                else:
                    jpeg = jpeg or render_result_jpeg(report)
                    delivery = meta_transport.publish_facebook(
                        jpeg=jpeg,
                        caption=report.facebook,
                        settings=meta_settings,
                    )
                    success, receipt, error = _meta_outcome(delivery)
            else:
                if (
                    meta_transport is None
                    or meta_settings is None
                    or artifact_store is None
                ):
                    error = "not_configured"
                else:
                    jpeg = jpeg or render_result_jpeg(report)
                    image_url = image_url or artifact_store.upload(
                        report=report,
                        jpeg=jpeg,
                    )
                    delivery = meta_transport.publish_instagram(
                        image_url=image_url,
                        caption=report.instagram,
                        settings=meta_settings,
                    )
                    success, receipt, error = _meta_outcome(delivery)
        except Exception:
            success = False
            receipt = ""
            error = "delivery_failed"

        try:
            repository.complete(
                batch_id=report.batch_id,
                report_kind=report.kind,
                destination=destination,
                report_digest=report.digest,
                attempt_id=claim.attempt_id,
                success=success,
                error="" if success else error,
                receipt=receipt if success else "",
            )
        except Exception:
            results[destination] = "completion_failed"
            continue
        results[destination] = "success" if success else error
    return results


def _meta_outcome(delivery: MetaDelivery) -> tuple[bool, str, str]:
    if not isinstance(delivery, MetaDelivery):
        return False, "", "delivery_failed"
    if delivery.status == "success":
        return True, delivery.receipt, ""
    if delivery.status in {"not_configured", "token_invalid", "delivery_failed"}:
        return False, "", delivery.status
    return False, "", "delivery_failed"


class SupabaseResultArtifactStore:
    """Upload one deterministic final JPEG to the existing public social bucket."""

    def __init__(self, *, client: object, supabase_url: str, bucket: str = "social-media") -> None:
        if not isinstance(supabase_url, str) or not supabase_url.startswith("https://"):
            raise ValueError("a secure Supabase URL is required")
        if not isinstance(bucket, str) or not bucket or not bucket.replace("-", "").isalnum():
            raise ValueError("a safe storage bucket is required")
        self._client = client
        self._supabase_url = supabase_url.rstrip("/")
        self._bucket = bucket

    def upload(self, *, report: ResultReport, jpeg: bytes) -> str:
        if report.kind != "final" or not report.terminal:
            raise ValueError("only final result reports may be uploaded")
        if not isinstance(jpeg, bytes) or not jpeg.startswith(b"\xff\xd8"):
            raise ValueError("result artifact must be a JPEG")
        object_key = (
            f"results/{report.portfolio_date}/{report.batch_id}-"
            f"{report.digest[:16]}.jpg"
        )
        try:
            storage = getattr(self._client, "storage")
            bucket = storage.from_(self._bucket)
            bucket.upload(
                path=object_key,
                file=jpeg,
                file_options={"content-type": "image/jpeg", "upsert": "true"},
            )
            raw_url = bucket.get_public_url(object_key)
        except Exception:
            raise RuntimeError("result artifact upload failed") from None
        if isinstance(raw_url, Mapping):
            raw_url = raw_url.get("publicUrl") or raw_url.get("public_url")
        if not isinstance(raw_url, str):
            raise RuntimeError("result artifact URL was invalid")
        parsed = urlsplit(raw_url)
        expected = urlsplit(self._supabase_url)
        expected_path = f"/storage/v1/object/public/{self._bucket}/{object_key}"
        if (
            parsed.scheme != "https"
            or parsed.netloc != expected.netloc
            or parsed.path != expected_path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("result artifact URL was invalid")
        return raw_url

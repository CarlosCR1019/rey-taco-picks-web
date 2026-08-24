from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.result_report_publisher import (
    destinations_for,
    publish_result_report,
    require_healthy_result_reports,
)
from backend.result_report_repository import Claim
from backend.result_reporting import build_result_report
from backend.social_poster import MetaDelivery, MetaSettings
from backend.telegram_publisher import TelegramDestination
from tests.test_result_reporting import rows_with_states


def report(kind: str = "final"):
    states = ["ganado"] * 6 if kind == "final" else [
        "ganado",
        "perdido",
        "pendiente",
        "pendiente",
        "pendiente",
        "pendiente",
    ]
    return build_result_report(rows_with_states(*states), kind=kind)  # type: ignore[arg-type]


class FakeRepository:
    def __init__(self, claims: dict[str, Claim] | None = None) -> None:
        self.claims = claims or {}
        self.claim_calls: list[str] = []
        self.complete_calls: list[dict[str, object]] = []

    def claim(self, **kwargs: object) -> Claim:
        destination = str(kwargs["destination"])
        self.claim_calls.append(destination)
        return self.claims.get(
            destination,
            Claim("claimed", f"12345678-1234-4234-8234-{len(self.claim_calls):012d}"),
        )

    def complete(self, **kwargs: object) -> None:
        self.complete_calls.append(kwargs)


class FakeTelegram:
    def __init__(self, fail: str = "") -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def __call__(self, destination: TelegramDestination, text: str) -> None:
        self.calls.append((destination.name, text))
        if destination.name == self.fail:
            raise RuntimeError("remote body")


class FakeMeta:
    def __init__(self) -> None:
        self.facebook_calls: list[dict[str, object]] = []
        self.instagram_calls: list[dict[str, object]] = []

    def publish_facebook(self, **kwargs: object) -> MetaDelivery:
        self.facebook_calls.append(kwargs)
        return MetaDelivery("facebook", "success", "fb_123")

    def publish_instagram(self, **kwargs: object) -> MetaDelivery:
        self.instagram_calls.append(kwargs)
        return MetaDelivery("instagram", "success", "ig_123")


@dataclass
class FakeArtifacts:
    calls: int = 0

    def upload(self, *, report: object, jpeg: bytes) -> str:
        self.calls += 1
        assert jpeg.startswith(b"\xff\xd8")
        return "https://project.supabase.co/storage/v1/object/public/social-media/results/final.jpg"


SETTINGS = MetaSettings(
    token="token",
    facebook_page_id="123",
    instagram_user_id="456",
)
CHATS = {"admin": "admin-id", "vip": "vip-id", "free": "free-id"}


def test_destinations_separate_partial_telegram_from_final_meta():
    assert destinations_for("evening") == ("admin", "vip", "free")
    assert destinations_for("final") == (
        "admin",
        "vip",
        "free",
        "facebook",
        "instagram",
    )


def test_result_report_health_accepts_success_and_complete():
    require_healthy_result_reports(
        {
            "12345678-1234-4234-8234-123456789012:evening": {
                "admin": "success",
                "vip": "complete",
                "free": "success",
            }
        }
    )


@pytest.mark.parametrize(
    "status",
    [
        "claim_failed",
        "ambiguous",
        "not_configured",
        "token_invalid",
        "delivery_failed",
        "completion_failed",
    ],
)
def test_result_report_health_rejects_unconfirmed_outcomes(status):
    outcomes = {
        "admin": "success",
        "vip": status,
        "free": "success",
    }

    with pytest.raises(RuntimeError, match=rf"vip={status}"):
        require_healthy_result_reports(
            {"12345678-1234-4234-8234-123456789012:evening": outcomes}
        )


def test_result_report_health_rejects_missing_required_destination_safely():
    with pytest.raises(RuntimeError, match=r"free=missing"):
        require_healthy_result_reports(
            {
                "12345678-1234-4234-8234-123456789012:evening": {
                    "admin": "success",
                    "vip": "success",
                }
            }
        )


def test_evening_report_never_calls_meta_or_artifact_storage():
    repository = FakeRepository()
    telegram = FakeTelegram()
    meta = FakeMeta()
    artifacts = FakeArtifacts()

    results = publish_result_report(
        report("evening"),
        repository=repository,
        telegram_transport=telegram,
        telegram_chats=CHATS,
        meta_transport=meta,
        meta_settings=SETTINGS,
        artifact_store=artifacts,
    )

    assert results == {"admin": "success", "vip": "success", "free": "success"}
    assert [name for name, _ in telegram.calls] == ["admin", "vip", "free"]
    assert meta.facebook_calls == []
    assert meta.instagram_calls == []
    assert artifacts.calls == 0


def test_final_report_publishes_every_destination_independently():
    repository = FakeRepository()
    telegram = FakeTelegram(fail="vip")
    meta = FakeMeta()
    artifacts = FakeArtifacts()

    results = publish_result_report(
        report("final"),
        repository=repository,
        telegram_transport=telegram,
        telegram_chats=CHATS,
        meta_transport=meta,
        meta_settings=SETTINGS,
        artifact_store=artifacts,
    )

    assert results["admin"] == "success"
    assert results["vip"] == "delivery_failed"
    assert results["free"] == "success"
    assert results["facebook"] == "success"
    assert results["instagram"] == "success"
    assert len(meta.facebook_calls) == 1
    assert len(meta.instagram_calls) == 1
    assert artifacts.calls == 1
    completed = {str(call["destination"]): call for call in repository.complete_calls}
    assert completed["vip"]["success"] is False
    assert completed["facebook"]["receipt"] == "fb_123"


def test_complete_or_ambiguous_claims_skip_external_transports():
    repository = FakeRepository(
        {
            "admin": Claim("complete", None),
            "vip": Claim("ambiguous", None),
        }
    )
    telegram = FakeTelegram()

    results = publish_result_report(
        report("evening"),
        repository=repository,
        telegram_transport=telegram,
        telegram_chats=CHATS,
        meta_transport=FakeMeta(),
        meta_settings=SETTINGS,
        artifact_store=FakeArtifacts(),
    )

    assert results["admin"] == "complete"
    assert results["vip"] == "ambiguous"
    assert [name for name, _ in telegram.calls] == ["free"]

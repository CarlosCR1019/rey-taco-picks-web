from __future__ import annotations

import pytest

import backend.verificar_resultados as verifier
from tests.test_result_reporting import rows_with_states


class FakeBatchRepository:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def batches(self):
        return (tuple(rows_with_states(*(["ganado"] * 6))),)


def test_verifier_fails_when_supabase_is_not_configured(monkeypatch, capsys):
    monkeypatch.setattr(verifier, "supabase", None)

    assert verifier.verificar_picks() == 1

    assert "Supabase" in capsys.readouterr().out


def test_verifier_fails_when_reading_pending_picks_fails(monkeypatch, capsys):
    monkeypatch.setattr(verifier, "supabase", object())
    monkeypatch.setattr(
        verifier,
        "load_active_pending_picks",
        lambda _client: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    assert verifier.verificar_picks() == 1

    assert "Error leyendo picks" in capsys.readouterr().out


def configure_report_run(monkeypatch, outcomes):
    monkeypatch.setenv("RESULT_REPORT_MODE", "final_only")
    monkeypatch.setattr(verifier, "SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setattr(verifier, "SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setattr(verifier, "supabase", object())
    monkeypatch.setattr(
        verifier,
        "SupabaseResultReportRepository",
        FakeBatchRepository,
    )
    monkeypatch.setattr(
        verifier,
        "publish_result_report",
        lambda *_args, **_kwargs: dict(outcomes),
    )
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda _report: {},
    )


def test_verifier_rejects_report_after_collecting_all_destination_outcomes(
    monkeypatch,
):
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "completion_failed",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)

    with pytest.raises(RuntimeError, match=r"facebook=completion_failed"):
        verifier.publish_available_result_reports()


def test_verifier_accepts_idempotent_complete_outcomes(monkeypatch):
    outcomes = {
        "admin": "complete",
        "vip": "complete",
        "free": "complete",
        "facebook": "complete",
        "instagram": "complete",
    }
    configure_report_run(monkeypatch, outcomes)

    assert verifier.publish_available_result_reports()


def test_verifier_dry_run_never_constructs_a_result_report(monkeypatch):
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "success",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)
    monkeypatch.setenv("RESULT_VERIFIER_DRY_RUN", "true")
    monkeypatch.setattr(
        verifier,
        "publish_result_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run attempted a result report")
        ),
    )

    assert verifier.publish_available_result_reports() == {}


def test_verifier_attempts_vertical_after_existing_five_destinations(monkeypatch):
    order: list[str] = []
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "success",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)
    monkeypatch.setattr(
        verifier,
        "publish_result_report",
        lambda *_args, **_kwargs: order.append("report") or outcomes,
    )
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda report: order.append("vertical") or {},
    )

    verifier.publish_available_result_reports()

    assert order == ["report", "vertical"]


def test_configured_vertical_failure_is_rejected_after_healthy_report(
    monkeypatch,
):
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "success",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)
    monkeypatch.setenv("META_SYSTEM_USER_ACCESS_TOKEN", "safe-token")
    monkeypatch.setenv("IG_USER_ID", "123456789")
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda _report: {"final_results_story": "delivery_failed"},
    )

    with pytest.raises(RuntimeError, match="final_results_story=delivery_failed"):
        verifier.publish_available_result_reports()


def test_unconfigured_vertical_failure_does_not_weaken_five_report_destinations(
    monkeypatch,
):
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "success",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)
    monkeypatch.delenv("META_SYSTEM_USER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("IG_USER_ID", raising=False)
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda _report: {"final_results_story": "not_configured"},
    )

    assert verifier.publish_available_result_reports()


def test_vertical_runtime_exception_is_sanitized_and_checked_after_report(
    monkeypatch,
):
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "success",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)
    monkeypatch.setenv("META_SYSTEM_USER_ACCESS_TOKEN", "safe-token")
    monkeypatch.setenv("IG_USER_ID", "123456789")
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda _report: (_ for _ in ()).throw(RuntimeError("raw secret")),
    )

    with pytest.raises(RuntimeError, match="final_results_story=delivery_failed") as raised:
        verifier.publish_available_result_reports()

    assert "raw secret" not in str(raised.value)

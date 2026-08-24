from __future__ import annotations

import pytest

import backend.verificar_resultados as verifier
from tests.test_result_reporting import rows_with_states


class FakeBatchRepository:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def batches(self):
        return (tuple(rows_with_states(*(["ganado"] * 6))),)


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

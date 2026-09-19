from __future__ import annotations

import pytest

import backend.verificar_resultados as verifier
from tests.test_result_reporting import rows_with_states


class FakeBatchRepository:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def batches(self):
        return (tuple(rows_with_states(*(["ganado"] * 6))),)


class EmptyBatchRepository:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def batches(self):
        return ()


def test_verifier_fails_when_supabase_is_not_configured(monkeypatch, capsys):
    monkeypatch.setattr(verifier, "supabase", None)

    assert verifier.verificar_picks() == 1

    assert "Supabase" in capsys.readouterr().out


def test_verifier_fails_when_reading_pending_picks_fails(monkeypatch, capsys):
    monkeypatch.setattr(verifier, "supabase", object())
    monkeypatch.setattr(
        verifier,
        "_validate_live_publication_configuration",
        lambda _mode: None,
    )
    monkeypatch.setattr(verifier, "_load_result_report_batches", lambda: (object(), ()))
    monkeypatch.setattr(
        verifier,
        "load_active_pending_picks",
        lambda _client: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )

    assert verifier.verificar_picks() == 1

    assert "Error leyendo picks" in capsys.readouterr().out


def configure_report_run(monkeypatch, outcomes):
    monkeypatch.setenv("RESULT_REPORT_MODE", "final_only")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "safe-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "100")
    monkeypatch.setenv("TELEGRAM_VIP_CHANNEL_ID", "200")
    monkeypatch.setenv("TELEGRAM_FREE_CHANNEL_ID", "300")
    monkeypatch.setenv("META_SYSTEM_USER_ACCESS_TOKEN", "safe-meta-token")
    monkeypatch.setenv("FB_PAGE_ID", "400")
    monkeypatch.setenv("IG_USER_ID", "500")
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
        lambda _report: {
            "final_results_story": "complete",
            "instagram_reel": "complete",
            "facebook_reel": "complete",
        },
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


def test_verifier_dry_run_never_constructs_a_result_report(monkeypatch, tmp_path):
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "success",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)
    monkeypatch.setenv("RESULT_VERIFIER_DRY_RUN", "true")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(
        verifier,
        "publish_result_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dry-run attempted a result report")
        ),
    )

    assert verifier.publish_available_result_reports() == {}
    assert not output.exists()


def test_verifier_accepts_healthy_final_report_with_vertical_media(monkeypatch):
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "success",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)
    assert verifier.publish_available_result_reports()


def test_verifier_publishes_vertical_for_the_exact_healthy_report(monkeypatch):
    order: list[object] = []
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
        lambda report, **_kwargs: order.append(("report", report.batch_id))
        or outcomes,
    )
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda report: order.append(("vertical", report.batch_id))
        or {"final_results_story": "complete"},
    )

    verifier.publish_available_result_reports()

    assert len(order) == 2
    assert order[0][0] == "report"
    assert order[1] == ("vertical", order[0][1])


def test_unhealthy_result_report_never_starts_vertical(monkeypatch):
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "delivery_failed",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda _report: (_ for _ in ()).throw(
            AssertionError("unhealthy report started vertical publication")
        ),
    )

    with pytest.raises(RuntimeError, match="facebook=delivery_failed"):
        verifier.publish_available_result_reports()


def test_unhealthy_report_does_not_prevent_later_exact_report_attempts(monkeypatch):
    second_rows = rows_with_states(*(["perdido"] * 6))
    second_batch_id = "87654321-4321-4321-8321-cba987654321"
    for index, row in enumerate(second_rows, start=11):
        row["id"] = index
        row["batch_id"] = second_batch_id

    class TwoBatchRepository(FakeBatchRepository):
        def batches(self):
            return (
                tuple(rows_with_states(*(["ganado"] * 6))),
                tuple(second_rows),
            )

    healthy = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "success",
        "instagram": "success",
    }
    unhealthy = dict(healthy, facebook="delivery_failed")
    attempted: list[str] = []
    vertical: list[str] = []
    configure_report_run(monkeypatch, healthy)
    monkeypatch.setattr(
        verifier,
        "SupabaseResultReportRepository",
        TwoBatchRepository,
    )
    monkeypatch.setattr(
        verifier,
        "publish_result_report",
        lambda report, **_kwargs: attempted.append(report.batch_id)
        or (unhealthy if report.batch_id != second_batch_id else healthy),
    )
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda report: vertical.append(report.batch_id)
        or {"final_results_story": "complete"},
    )

    with pytest.raises(RuntimeError, match="facebook=delivery_failed"):
        verifier.publish_available_result_reports()

    assert attempted == [
        "12345678-1234-4234-8234-123456789abc",
        second_batch_id,
    ]
    assert vertical == [second_batch_id]


def test_vertical_runtime_failure_is_sanitized_after_healthy_exact_report(
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
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda _report: (_ for _ in ()).throw(RuntimeError("raw secret")),
    )

    with pytest.raises(RuntimeError, match="final_results_story=delivery_failed") as raised:
        verifier.publish_available_result_reports()

    assert "raw secret" not in str(raised.value)


def test_verifier_marks_no_final_batch_without_sending_to_publishers(
    monkeypatch,
):
    configure_report_run(monkeypatch, {})
    monkeypatch.setattr(verifier, "SupabaseResultReportRepository", EmptyBatchRepository)
    monkeypatch.setattr(
        verifier,
        "publish_result_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no batch attempted a result publication")
        ),
    )
    monkeypatch.setattr(
        verifier,
        "publish_final_stories_from_runtime",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no batch attempted a vertical publication")
        ),
    )

    assert verifier.publish_available_result_reports() == {}


def test_report_repository_failure_is_fatal_and_sanitized(
    monkeypatch,
    capsys,
):
    class BrokenRepository:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def batches(self):
            raise RuntimeError("raw secret")

    configure_report_run(monkeypatch, {})
    monkeypatch.setattr(verifier, "SupabaseResultReportRepository", BrokenRepository)

    with pytest.raises(RuntimeError, match="result report batches unavailable") as raised:
        verifier.publish_available_result_reports()

    assert "raw secret" not in str(raised.value)
    assert "raw secret" not in capsys.readouterr().out


def test_live_verifier_preflights_report_repository_before_reading_picks(
    monkeypatch,
    capsys,
):
    class BrokenRepository:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def batches(self):
            raise RuntimeError("raw secret")

    configure_report_run(monkeypatch, {})
    monkeypatch.setattr(verifier, "SupabaseResultReportRepository", BrokenRepository)
    monkeypatch.setattr(
        verifier,
        "load_active_pending_picks",
        lambda _client: (_ for _ in ()).throw(
            AssertionError("pending picks read before report preflight")
        ),
    )

    assert verifier.verificar_picks() == 1

    captured = capsys.readouterr().out
    assert "No se pudo autorizar el repositorio de reportes" in captured
    assert "raw secret" not in captured


def test_live_verifier_rejects_invalid_mode_before_reading_picks(
    monkeypatch,
    capsys,
):
    configure_report_run(monkeypatch, {})
    monkeypatch.setenv("RESULT_REPORT_MODE", "unsafe")
    monkeypatch.setattr(
        verifier,
        "load_active_pending_picks",
        lambda _client: (_ for _ in ()).throw(
            AssertionError("pending picks read before mode preflight")
        ),
    )

    assert verifier.verificar_picks() == 1
    assert "configuración de publicación" in capsys.readouterr().out

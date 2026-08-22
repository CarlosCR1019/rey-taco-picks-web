from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.scraper as scraper
from backend.pick_publisher import PERSISTED_PICK_COLUMNS
from backend.scraper import ExitCode, LegacyPipeline, PipelineResult, run_main
from backend.scraper_config import ScraperSettings


SCRAPER_SOURCE = Path(scraper.__file__)


class FakePipeline:
    def __init__(self, result: PipelineResult | None = None, error: Exception | None = None):
        self.result = result or PipelineResult(2, 1, False, ())
        self.error = error
        self.runs = 0
        self.publications = 0
        self.deliveries = 0

    def run(self) -> PipelineResult:
        self.runs += 1
        if self.error is not None:
            raise self.error
        return self.result


def settings(tmp_path, *, dry_run: bool) -> ScraperSettings:
    return ScraperSettings(
        dry_run=dry_run,
        run_key="" if dry_run else "test-run",
        supabase_url="" if dry_run else "https://example.supabase.co",
        service_role_key="" if dry_run else "service-role-secret",
        groq_api_key="groq",
        odds_api_key="odds",
        telegram_token="telegram",
        telegram_admin_id="admin",
        telegram_vip_id="vip",
        telegram_free_id="free",
        public_picks_path=tmp_path / "picks.json",
        queue_path=tmp_path / "unused.json",
    )


def test_exit_codes_are_stable():
    assert dict(ExitCode.__members__) == {
        "SUCCESS": ExitCode(0),
        "CONFIGURATION": ExitCode(2),
        "NO_EVENTS": ExitCode(3),
        "NO_CANDIDATES": ExitCode(4),
        "PERSISTENCE": ExitCode(5),
        "DELIVERY": ExitCode(6),
        "UNEXPECTED": ExitCode(10),
    }


def test_command_source_is_python_311_compatible_and_exits_with_run_main():
    source = SCRAPER_SOURCE.read_text(encoding="utf-8")
    ast.parse(source, filename=str(SCRAPER_SOURCE), feature_version=(3, 11))
    assert 'raise SystemExit(run_main())' in source


def test_configuration_failure_returns_nonzero_before_pipeline_build(monkeypatch):
    builds = []
    monkeypatch.setattr(scraper, "build_pipeline", lambda _settings: builds.append(True))

    assert run_main([], values={}) == ExitCode.CONFIGURATION
    assert builds == []


def test_missing_run_key_fails_before_pipeline_or_chrome(monkeypatch):
    builds = []
    chrome = []
    monkeypatch.setattr(scraper, "build_pipeline", lambda _settings: builds.append(True))
    monkeypatch.setattr(scraper, "get_chrome_driver", lambda: chrome.append(True))

    code = run_main(
        [],
        values={
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
        },
    )

    assert code == ExitCode.CONFIGURATION
    assert builds == []
    assert chrome == []


def test_dry_run_skips_writes_and_returns_success():
    fake_pipeline = FakePipeline()

    code = run_main(["--dry-run"], values={}, pipeline=fake_pipeline)

    assert code == ExitCode.SUCCESS
    assert fake_pipeline.runs == 1
    assert fake_pipeline.publications == 0
    assert fake_pipeline.deliveries == 0


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (PipelineResult(0, 0, False, ()), ExitCode.NO_EVENTS),
        (PipelineResult(2, 0, False, ()), ExitCode.NO_CANDIDATES),
        (PipelineResult(2, 1, False, ()), ExitCode.PERSISTENCE),
        (PipelineResult(2, 1, True, ("vip",)), ExitCode.DELIVERY),
        (PipelineResult(2, 1, True, ()), ExitCode.SUCCESS),
    ],
)
def test_production_results_map_to_truthful_exit_codes(result, expected):
    values = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
        "SCRAPER_RUN_KEY": "test-run",
    }
    assert run_main([], values=values, pipeline=FakePipeline(result)) == expected


def test_unexpected_errors_are_nonzero_and_do_not_leak_provider_details(capsys):
    secret = "service-role-secret"
    code = run_main(
        ["--dry-run"],
        values={},
        pipeline=FakePipeline(error=RuntimeError(f"provider failed with {secret}")),
    )

    assert code == ExitCode.UNEXPECTED
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert secret not in output
    assert "provider failed" not in output


def test_configuration_errors_from_dependencies_do_not_leak_details(capsys):
    secret = "service-role-secret"
    code = run_main(
        ["--dry-run"],
        values={},
        pipeline=FakePipeline(error=scraper.ConfigError(f"provider {secret}")),
    )

    assert code == ExitCode.CONFIGURATION
    output = capsys.readouterr().out
    assert "invalid scraper configuration" in output
    assert secret not in output
    assert "provider" not in output


def test_legacy_provider_errors_are_logged_by_type_without_secrets(
    monkeypatch, capsys
):
    secret = "odds-api-secret"
    monkeypatch.setattr(
        scraper.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(f"provider body contains {secret}")
        ),
    )

    assert scraper.fase2_comparacion_mercado([], odds_api_key=secret) == {}

    output = capsys.readouterr().out
    assert "failure=RuntimeError" in output
    assert secret not in output
    assert "provider body" not in output


def test_unknown_cli_arguments_are_rejected():
    with pytest.raises(SystemExit) as captured:
        run_main(["--publish-anyway"], values={})
    assert captured.value.code == 2


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(event_count=True, pick_count=0, persisted=False, failed_deliveries=()),
        SimpleNamespace(event_count=-1, pick_count=0, persisted=False, failed_deliveries=()),
        SimpleNamespace(event_count=1.0, pick_count=0, persisted=False, failed_deliveries=()),
        SimpleNamespace(event_count=1, pick_count=True, persisted=False, failed_deliveries=()),
        SimpleNamespace(event_count=1, pick_count=-1, persisted=False, failed_deliveries=()),
        SimpleNamespace(event_count=1, pick_count=1, persisted=1, failed_deliveries=()),
        SimpleNamespace(event_count=1, pick_count=1, persisted=True, failed_deliveries="vip"),
        SimpleNamespace(event_count=1, pick_count=1, persisted=True, failed_deliveries=("",)),
        SimpleNamespace(event_count=1, pick_count=1, persisted=True, failed_deliveries=("VIP!",)),
        SimpleNamespace(event_count=0, pick_count=1, persisted=False, failed_deliveries=()),
        SimpleNamespace(event_count=1, pick_count=0, persisted=True, failed_deliveries=()),
        SimpleNamespace(event_count=1, pick_count=0, persisted=False, failed_deliveries=("vip",)),
        SimpleNamespace(event_count=1, pick_count=1, persisted=False, failed_deliveries=("vip",)),
    ],
)
def test_impossible_or_ill_typed_pipeline_results_are_unexpected(result, capsys):
    code = run_main(["--dry-run"], values={}, pipeline=FakePipeline(result))

    assert code == ExitCode.UNEXPECTED
    assert "unexpected_error=" in capsys.readouterr().out


def test_pipeline_result_normalizes_safe_delivery_sequences_to_an_immutable_tuple():
    result = PipelineResult(2, 1, True, ["vip"])  # type: ignore[arg-type]

    assert result.failed_deliveries == ("vip",)
    assert isinstance(result.failed_deliveries, tuple)

    assert (
        run_main([], values=production_values(), pipeline=FakePipeline(result))
        == ExitCode.DELIVERY
    )


class FakeRpcCall:
    def __init__(self, data=None, error: Exception | None = None):
        self.data = data
        self.error = error

    def execute(self):
        if self.error is not None:
            raise self.error
        return self


class FakeSupabase:
    def __init__(self, status=None, error: Exception | None = None):
        self.status = status
        self.error = error
        self.calls = []

    def rpc(self, name, arguments):
        self.calls.append((name, arguments))
        return FakeRpcCall(self.status, self.error)


def test_schema_probe_is_read_only_and_builds_pipeline_before_chrome(tmp_path):
    client = FakeSupabase(
        {
            "public_picks": True,
            "publish_pick_batch": True,
            "resume_pick_batch": True,
            "source_audit": True,
            "version": 2,
        }
    )
    driver_calls = []
    pipeline = scraper.build_pipeline(
        settings(tmp_path, dry_run=False),
        client_factory=lambda _url, _key: client,
        driver_factory=lambda: driver_calls.append(True),
    )

    assert isinstance(pipeline, LegacyPipeline)
    assert client.calls == [("scraper_schema_status", {})]
    assert driver_calls == []


@pytest.mark.parametrize(
    "status",
    [
        None,
        {},
        {"public_picks": True, "publish_pick_batch": True},
        {"public_picks": True, "publish_pick_batch": True, "version": False},
        {"public_picks": True, "publish_pick_batch": True, "version": "1"},
        {"public_picks": True, "publish_pick_batch": True, "version": 0},
        {"public_picks": True, "publish_pick_batch": True, "version": 2},
        {
            "public_picks": True,
            "publish_pick_batch": True,
            "resume_pick_batch": True,
            "source_audit": False,
            "version": 2,
        },
        {
            "public_picks": True,
            "publish_pick_batch": True,
            "resume_pick_batch": False,
            "source_audit": True,
            "version": 2,
        },
        {"public_picks": False, "publish_pick_batch": True, "version": 1},
        {"public_picks": True, "publish_pick_batch": False, "version": 1},
    ],
)
def test_missing_secure_schema_fails_closed_before_chrome(tmp_path, status):
    client = FakeSupabase(status)
    driver_calls = []

    with pytest.raises(
        scraper.ConfigError,
        match="secure Supabase scraper migration is not applied",
    ):
        scraper.build_pipeline(
            settings(tmp_path, dry_run=False),
            client_factory=lambda _url, _key: client,
            driver_factory=lambda: driver_calls.append(True),
        )

    assert driver_calls == []


def test_schema_provider_error_is_replaced_with_token_safe_configuration_error(tmp_path):
    client = FakeSupabase(error=RuntimeError("404 service-role-secret provider body"))

    with pytest.raises(scraper.ConfigError) as captured:
        scraper.build_pipeline(
            settings(tmp_path, dry_run=False),
            client_factory=lambda _url, _key: client,
        )

    assert str(captured.value) == "secure Supabase scraper migration is not applied"


def test_dry_run_build_does_not_create_client_or_probe_schema(tmp_path):
    client_calls = []

    pipeline = scraper.build_pipeline(
        settings(tmp_path, dry_run=True),
        client_factory=lambda _url, _key: client_calls.append(True),
    )

    assert isinstance(pipeline, LegacyPipeline)
    assert client_calls == []


class FakeDriver:
    def __init__(self):
        self.quit_calls = 0

    def quit(self):
        self.quit_calls += 1


class Chrome:
    """UC-like fake: upstream destructor invokes the public quit method again."""

    __module__ = "undetected_chromedriver"

    def __init__(self, *, fail_cleanup=False):
        self.quit_calls = 0
        self.fail_cleanup = fail_cleanup

    def quit(self):
        self.quit_calls += 1
        if self.fail_cleanup:
            raise OSError("WinError 6")

    def __del__(self):
        self.quit()


def test_uc_cleanup_neutralizes_the_upstream_destructor_double_quit():
    driver = Chrome()

    scraper._cleanup_chrome_driver(driver)
    driver.__del__()

    assert driver.quit_calls == 1


def test_generic_driver_cleanup_is_not_overridden():
    driver = FakeDriver()

    scraper._cleanup_chrome_driver(driver)

    assert driver.quit_calls == 1
    assert "quit" not in driver.__dict__


def test_uc_cleanup_reports_the_first_failure_but_neutralizes_destructor():
    driver = Chrome(fail_cleanup=True)

    with pytest.raises(OSError, match="WinError 6"):
        scraper._cleanup_chrome_driver(driver)
    driver.__del__()

    assert driver.quit_calls == 1


def stub_successful_legacy_phases(monkeypatch, picks=None):
    selected = picks or [
        {
            "partido": "Pumas vs Atlas",
            "pick": "Pumas gana",
            "cuota": "1.80",
            "confianza": "85%",
            "razonamiento": "Análisis privado",
            "es_parlay": False,
            "source": "the-odds-api",
            "source_event_id": "event-pumas-atlas",
            "source_market_key": "h2h|full_time|",
            "source_selection_key": "home",
            "source_observed_at": "2026-08-20T20:00:00Z",
        }
    ]
    monkeypatch.setattr(scraper, "fase1_escaneo_superficie", lambda _driver, **_kw: ["event"])
    monkeypatch.setattr(scraper, "fase2_comparacion_mercado", lambda *_a, **_kw: {})
    monkeypatch.setattr(scraper, "fase3_filtro_inteligente", lambda *_a, **_kw: ["target"])
    monkeypatch.setattr(scraper, "fase4_inmersion", lambda *_a, **_kw: ["deep"])
    monkeypatch.setattr(scraper, "fase5_memoria_historica", lambda *_a, **_kw: "history")
    monkeypatch.setattr(scraper, "fase6_analisis_final", lambda *_a, **_kw: selected)


def production_values():
    return {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
        "SCRAPER_RUN_KEY": "test-run",
    }


class PublishFailureRepository:
    def resume(self, _run_key):
        return None

    def publish(self, _run_key, _source_hash, _picks):
        raise RuntimeError("database provider leaked service-role-secret")

    def record_delivery(self, *_args, **_kwargs):
        raise AssertionError("delivery must not run after persistence failure")


def test_real_phase7_persistence_failure_maps_to_exit_5_without_leaking(
    tmp_path, monkeypatch, capsys
):
    stub_successful_legacy_phases(monkeypatch)
    driver = FakeDriver()
    pipeline = LegacyPipeline(
        settings(tmp_path, dry_run=False),
        repository=PublishFailureRepository(),
        history_client=object(),
        driver_factory=lambda: driver,
    )

    code = run_main([], values=production_values(), pipeline=pipeline)

    assert code == ExitCode.PERSISTENCE
    output = capsys.readouterr().out
    assert "service-role-secret" not in output
    assert "database provider" not in output
    assert driver.quit_calls == 1


class DeliveryRecordFailureRepository:
    def resume(self, _run_key):
        return None

    def publish(self, _run_key, _source_hash, picks):
        stored = []
        for index, pick in enumerate(picks, start=1):
            row = {column: pick.get(column) for column in PERSISTED_PICK_COLUMNS}
            row["id"] = index
            if row["visibility"] == "public":
                row["razonamiento"] = None
            stored.append(row)
        return {
            "run_id": "run-1",
            "batch_id": "batch-1",
            "created": True,
            "delivery_status": {},
            "picks": stored,
        }

    def record_delivery(self, *_args, **_kwargs):
        raise RuntimeError("delivery provider leaked telegram-secret")


class ResumeRepository:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.resume_calls = []
        self.delivery_calls = []

    def resume(self, run_key):
        self.resume_calls.append(run_key)
        if self.error is not None:
            raise self.error
        return self.response

    def publish(self, *_args, **_kwargs):
        raise AssertionError("a resumed run must not publish a new batch")

    def record_delivery(self, run_id, destination, success, error=""):
        self.delivery_calls.append((run_id, destination, success, error))


def resumed_response(*, delivery_status):
    source = {
        "partido": "Pumas vs Atlas",
        "pick": "Pumas gana (persistido)",
        "cuota": 1.8,
        "confianza": "85% respaldo de datos",
        "razonamiento": None,
        "es_parlay": False,
        "visibility": "public",
        "source": "the-odds-api",
        "source_event_id": "event-pumas-atlas",
        "source_market_key": "h2h|full_time|",
        "source_selection_key": "home",
        "source_observed_at": "2026-08-20T20:00:00Z",
    }
    row = {column: source.get(column) for column in PERSISTED_PICK_COLUMNS}
    row["id"] = 77
    return {
        "run_id": "run-resumed",
        "batch_id": "batch-resumed",
        "created": False,
        "delivery_status": delivery_status,
        "picks": [row],
    }


def test_production_resumes_before_driver_and_sends_only_missing_persisted_delivery(
    tmp_path, monkeypatch, capsys
):
    repository = ResumeRepository(
        resumed_response(
            delivery_status={
                "admin": {"success": True},
                "free": {"success": True},
                "vip": {"success": False},
            }
        )
    )
    sent = []
    monkeypatch.setattr(
        scraper,
        "TelegramHttpTransport",
        lambda _token: lambda destination, text: sent.append((destination.name, text)),
    )

    result = LegacyPipeline(
        settings(tmp_path, dry_run=False),
        repository=repository,
        history_client=object(),
        driver_factory=lambda: (_ for _ in ()).throw(
            AssertionError("driver must not start for resume")
        ),
    ).run()

    assert result.persisted is True
    assert result.event_count == result.pick_count == 1
    assert result.failed_deliveries == ()
    assert result.picks[0]["pick"] == "Pumas gana (persistido)"
    assert [name for name, _text in sent] == ["vip"]
    assert "Pumas gana (persistido)" in sent[0][1]
    assert repository.resume_calls == ["test-run"]
    assert repository.delivery_calls == [("run-resumed", "vip", True, "")]
    assert "resume_only=true" in capsys.readouterr().out


def test_production_resume_with_all_deliveries_complete_sends_nothing(
    tmp_path, monkeypatch
):
    repository = ResumeRepository(
        resumed_response(
            delivery_status={
                name: {"success": True} for name in ("admin", "vip", "free")
            }
        )
    )
    transports = []
    monkeypatch.setattr(
        scraper,
        "TelegramHttpTransport",
        lambda _token: transports.append(True),
    )

    result = LegacyPipeline(
        settings(tmp_path, dry_run=False),
        repository=repository,
        driver_factory=lambda: (_ for _ in ()).throw(
            AssertionError("driver must not start for resume")
        ),
    ).run()

    assert result.persisted is True
    assert result.failed_deliveries == ()
    assert transports == []
    assert repository.delivery_calls == []


def test_absent_resume_continues_normal_scrape(tmp_path, monkeypatch):
    repository = ResumeRepository(None)
    driver = FakeDriver()
    stub_successful_legacy_phases(monkeypatch)
    monkeypatch.setattr(
        scraper,
        "fase7_guardar_y_notificar",
        lambda *_a, **_kw: (FakePublication("fresh-run"), {}),
    )

    result = LegacyPipeline(
        settings(tmp_path, dry_run=False),
        repository=repository,
        history_client=object(),
        driver_factory=lambda: driver,
    ).run()

    assert repository.resume_calls == ["test-run"]
    assert result.persisted is True
    assert driver.quit_calls == 1


def test_inactive_or_malformed_resume_fails_before_driver_file_or_delivery(
    tmp_path, monkeypatch
):
    destination = tmp_path / "picks.json"
    destination.write_text('[{"pick":"existing"}]', encoding="utf-8")
    repository = ResumeRepository(
        error=RuntimeError("scraper run batch is inactive or superseded provider-secret")
    )
    monkeypatch.setattr(
        scraper,
        "TelegramHttpTransport",
        lambda _token: (_ for _ in ()).throw(
            AssertionError("delivery must not start")
        ),
    )

    with pytest.raises(scraper.PersistenceFailure, match="scraper batch persistence failed"):
        LegacyPipeline(
            settings(tmp_path, dry_run=False),
            repository=repository,
            driver_factory=lambda: (_ for _ in ()).throw(
                AssertionError("driver must not start")
            ),
        ).run()

    assert destination.read_text(encoding="utf-8") == '[{"pick":"existing"}]'
    assert repository.delivery_calls == []


def test_legacy_dry_run_never_calls_repository_resume(tmp_path, monkeypatch):
    repository = ResumeRepository(
        error=AssertionError("dry-run must not query resume")
    )
    driver = FakeDriver()
    stub_successful_legacy_phases(monkeypatch)

    result = LegacyPipeline(
        settings(tmp_path, dry_run=True),
        repository=repository,
        driver_factory=lambda: driver,
    ).run()

    assert result.persisted is False
    assert repository.resume_calls == []


def test_real_delivery_record_failure_maps_to_exit_6_without_leaking(
    tmp_path, monkeypatch, capsys
):
    stub_successful_legacy_phases(monkeypatch)
    monkeypatch.setattr(
        scraper,
        "TelegramHttpTransport",
        lambda _token: (lambda _destination, _text: None),
    )
    driver = FakeDriver()
    pipeline = LegacyPipeline(
        settings(tmp_path, dry_run=False),
        repository=DeliveryRecordFailureRepository(),
        history_client=object(),
        driver_factory=lambda: driver,
    )

    code = run_main([], values=production_values(), pipeline=pipeline)

    assert code == ExitCode.DELIVERY
    output = capsys.readouterr().out
    assert "telegram-secret" not in output
    assert "delivery provider" not in output
    assert driver.quit_calls == 1


def test_legacy_dry_run_executes_phases_but_never_publishes_or_delivers(
    tmp_path, monkeypatch
):
    driver = FakeDriver()
    phase7_calls = []
    monkeypatch.setattr(scraper, "fase1_escaneo_superficie", lambda _driver, **_kw: ["event"])
    monkeypatch.setattr(scraper, "fase2_comparacion_mercado", lambda *_a, **_kw: {})
    monkeypatch.setattr(scraper, "fase3_filtro_inteligente", lambda *_a, **_kw: ["target"])
    monkeypatch.setattr(scraper, "fase4_inmersion", lambda *_a, **_kw: ["deep"])
    monkeypatch.setattr(scraper, "fase5_memoria_historica", lambda *_a, **_kw: "history")
    monkeypatch.setattr(scraper, "fase6_analisis_final", lambda *_a, **_kw: [{"pick": "x"}])
    monkeypatch.setattr(
        scraper, "fase7_guardar_y_notificar", lambda *_a, **_kw: phase7_calls.append(True)
    )

    result = LegacyPipeline(
        settings(tmp_path, dry_run=True),
        driver_factory=lambda: driver,
    ).run()

    assert result == PipelineResult(1, 1, False, ())
    assert phase7_calls == []
    assert driver.quit_calls == 1


@dataclass(frozen=True)
class FakePublication:
    run_id: str | None


@dataclass(frozen=True)
class FakeDelivery:
    success: bool


def test_legacy_production_maps_publication_and_failed_deliveries(tmp_path, monkeypatch):
    driver = FakeDriver()
    repository = ResumeRepository(None)
    monkeypatch.setattr(scraper, "fase1_escaneo_superficie", lambda _driver, **_kw: ["event"])
    monkeypatch.setattr(scraper, "fase2_comparacion_mercado", lambda *_a, **_kw: {})
    monkeypatch.setattr(scraper, "fase3_filtro_inteligente", lambda *_a, **_kw: ["target"])
    monkeypatch.setattr(scraper, "fase4_inmersion", lambda *_a, **_kw: ["deep"])
    monkeypatch.setattr(scraper, "fase5_memoria_historica", lambda *_a, **_kw: "history")
    monkeypatch.setattr(scraper, "fase6_analisis_final", lambda *_a, **_kw: [{"pick": "x"}])

    def publish(picks, **kwargs):
        assert picks == [{"pick": "x"}]
        assert kwargs["repository"] is repository
        assert kwargs["run_key"] == "test-run"
        return FakePublication("run-1"), {
            "admin": FakeDelivery(True),
            "vip": FakeDelivery(False),
        }

    monkeypatch.setattr(scraper, "fase7_guardar_y_notificar", publish)

    result = LegacyPipeline(
        settings(tmp_path, dry_run=False),
        repository=repository,
        history_client=object(),
        driver_factory=lambda: driver,
    ).run()

    assert result == PipelineResult(1, 1, True, ("vip",))
    assert driver.quit_calls == 1


def test_legacy_pipeline_always_quits_driver_on_failure(tmp_path, monkeypatch):
    driver = FakeDriver()
    monkeypatch.setattr(
        scraper,
        "fase1_escaneo_superficie",
        lambda _driver, **_kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        LegacyPipeline(
            settings(tmp_path, dry_run=True),
            driver_factory=lambda: driver,
        ).run()

    assert driver.quit_calls == 1

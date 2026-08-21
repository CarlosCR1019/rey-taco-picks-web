from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

import backend.scraper as scraper
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
        {"public_picks": True, "publish_pick_batch": True, "version": 1}
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
    repository = object()
    monkeypatch.setattr(scraper, "fase1_escaneo_superficie", lambda _driver, **_kw: ["event"])
    monkeypatch.setattr(scraper, "fase2_comparacion_mercado", lambda *_a, **_kw: {})
    monkeypatch.setattr(scraper, "fase3_filtro_inteligente", lambda *_a, **_kw: ["target"])
    monkeypatch.setattr(scraper, "fase4_inmersion", lambda *_a, **_kw: ["deep"])
    monkeypatch.setattr(scraper, "fase5_memoria_historica", lambda *_a, **_kw: "history")
    monkeypatch.setattr(scraper, "fase6_analisis_final", lambda *_a, **_kw: [{"pick": "x"}])

    def publish(picks, **kwargs):
        assert picks == [{"pick": "x"}]
        assert kwargs["repository"] is repository
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

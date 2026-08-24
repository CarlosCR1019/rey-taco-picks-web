from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.scraper as scraper
from backend.pick_publisher import PERSISTED_PICK_COLUMNS
from backend.scraper import ExitCode, LegacyPipeline, PipelineResult, run_main
from backend.scraper_config import ScraperSettings
from backend.scraper_domain import Event, Market, Outcome
from backend.lineup_source import LineupResolver


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


class ModePipeline:
    def __init__(self, result: PipelineResult):
        self.result = result
        self.calls = []

    def run(self, *, collect_only=False, deliver_only=False) -> PipelineResult:
        self.calls.append((collect_only, deliver_only))
        return self.result


def settings(tmp_path, *, dry_run: bool) -> ScraperSettings:
    return ScraperSettings(
        dry_run=dry_run,
        run_key="" if dry_run else "test-run",
        supabase_url="" if dry_run else "https://example.supabase.co",
        service_role_key="" if dry_run else "service-role-secret",
        groq_api_key="groq",
        odds_api_key="odds",
        api_football_key="",
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
        "SOURCE": ExitCode(7),
        "UNEXPECTED": ExitCode(10),
    }


def test_verified_market_coverage_counts_each_event_once_per_market(event_fixture):
    record = scraper._legacy_odds_projection(event_fixture)
    candidates = record[scraper._VERIFIED_CANDIDATES_FIELD]
    record[scraper._VERIFIED_CANDIDATES_FIELD] = (
        *candidates,
        candidates[0],
    )

    assert scraper._verified_market_coverage([record]) == {
        "h2h": 1,
        "totals": 0,
        "spreads": 0,
        "source_markets": 0,
    }


def test_playdoit_projection_resolves_lineup_before_building_candidates():
    observed = datetime(2026, 8, 23, 18, tzinfo=timezone.utc)
    prop = Market(
        "playdoit_market:shots-1",
        "source_unspecified",
        None,
        (
            Outcome(
                "playdoit_odd:shots-over",
                "Más de 0.5",
                1.8,
                source_id="shots-over",
                competitor_id="player-7",
            ),
        ),
        bookmaker_key="playdoit",
        name="Remates a Puerta - Cole Palmer",
        source_id="shots-1",
        scope="player",
        participant_id="player-7",
        offer_kind="standard",
        source_selection_ids=("shots-over",),
    )
    event = Event(
        source="playdoit",
        source_event_id="event-1",
        sport="soccer",
        league="Premier League",
        home_team="Fulham",
        away_team="Chelsea",
        starts_at=observed + timedelta(minutes=55),
        observed_at=observed,
        markets=(prop,),
    )

    class Resolver:
        def resolve(self, received):
            return replace(
                received,
                markets=(
                    replace(received.markets[0], lineup_confirmed=True),
                ),
            )

    record = scraper._legacy_odds_projection(
        event, lineup_resolver=Resolver()
    )

    candidates = record[scraper._VERIFIED_CANDIDATES_FIELD]
    assert len(candidates) == 1
    assert candidates[0].lineup_confirmed is True


def test_verified_market_coverage_counts_generic_source_markets():
    from backend.pick_selection import build_candidates
    from backend.scraper_domain import Event, Market, Outcome

    observed = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    event = Event(
        source="playdoit",
        source_event_id="event-corners-1",
        sport="soccer",
        league="Liga MX",
        home_team="América",
        away_team="Tigres",
        starts_at=observed + timedelta(hours=4),
        observed_at=observed,
        markets=(
            Market(
                "playdoit_market:corners-1",
                "source_unspecified",
                None,
                (
                    Outcome(
                        "playdoit_odd:corners-over",
                        "Más de 8.5",
                        1.85,
                        source_id="corners-over",
                    ),
                ),
                bookmaker_key="playdoit",
                name="Total de tiros de esquina",
                source_id="corners-1",
                scope="event",
                offer_kind="standard",
                source_selection_ids=("corners-over",),
            ),
        ),
    )
    record = {
        scraper._VERIFIED_CANDIDATES_FIELD: tuple(build_candidates([event]))
    }

    assert scraper._verified_market_coverage([record]) == {
        "h2h": 0,
        "totals": 0,
        "spreads": 0,
        "source_markets": 1,
    }


def test_generic_market_uses_official_display_and_source_ids_in_projection():
    from backend.pick_selection import (
        EvidenceScore,
        RankedPick,
        build_candidates,
    )
    from backend.scraper_domain import Event, Market, Outcome

    observed = datetime(2026, 8, 23, 12, tzinfo=timezone.utc)
    event = Event(
        source="playdoit",
        source_event_id="event-props-1",
        sport="soccer",
        league="Premier League",
        home_team="Fulham",
        away_team="Chelsea",
        starts_at=observed + timedelta(hours=4),
        observed_at=observed,
        markets=(
            Market(
                "playdoit_market:player-shots-1",
                "source_unspecified",
                None,
                (
                    Outcome(
                        "playdoit_odd:shots-over-05",
                        "Más de 0.5",
                        80.0,
                        source_id="shots-over-05",
                    ),
                ),
                bookmaker_key="playdoit",
                name="Remates a Puerta - Cole Palmer",
                source_id="player-shots-1",
                scope="player",
                participant_id="cole-palmer",
                offer_kind="standard",
                source_selection_ids=("shots-over-05",),
                lineup_confirmed=True,
            ),
        ),
    )
    candidate = build_candidates([event])[0]

    prompt_row = scraper._candidate_prompt_row(candidate)
    projected = scraper._legacy_ranked_pick_projection(
        RankedPick(candidate, "Selección oficial con línea verificada."),
        EvidenceScore(65, "Datos limitados", False),
    )
    audit_identity = json.loads(
        projected["source_market_key"].removeprefix("market:v1:")
    )

    assert prompt_row["market_name"] == "Remates a Puerta - Cole Palmer"
    assert prompt_row["source_market_id"] == "player-shots-1"
    assert prompt_row["source_selection_id"] == "shots-over-05"
    assert prompt_row["market_scope"] == "player"
    assert prompt_row["participant_id"] == "cole-palmer"
    assert prompt_row["lineup_confirmed"] is True
    assert projected["mercado"] == "Remates a Puerta - Cole Palmer"
    assert projected["source_selection_key"] == "shots-over-05"
    assert audit_identity[-2] == "player-shots-1"
    assert audit_identity[-1]["scope"] == "player"
    assert audit_identity[-1]["lineup_confirmed"] is True
    assert scraper._valid_source_audit_row(
        projected,
        reference_at=observed,
    ) is True


def test_source_failure_is_recoverable_and_sanitized(capsys):
    code = run_main(
        ["--dry-run"],
        values={},
        pipeline=FakePipeline(error=scraper.PlaydoitSourceBlocked()),
    )

    assert code == ExitCode.SOURCE
    assert capsys.readouterr().out.strip() == "source_error=source_blocked"


def test_surface_scan_rejects_blocked_source_before_decimal_interaction(monkeypatch):
    decimal_calls = []

    class BlockedDriver:
        title = "Acceso bloqueado"
        page_source = "<html><body>Solicitud detenida</body></html>"

        def get(self, _url):
            return None

        def find_element(self, by, value):
            assert (by, value) == ("tag name", "body")
            return SimpleNamespace(text="RAY ID abc123 TU IP 203.0.113.4")

    monkeypatch.setattr(scraper.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        scraper, "click_decimal_toggle", lambda _driver: decimal_calls.append(True)
    )

    with pytest.raises(scraper.PlaydoitSourceBlocked):
        scraper.fase1_escaneo_superficie(BlockedDriver())

    assert decimal_calls == []


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


def test_cli_dry_run_does_not_load_dotenv_or_ambient_secrets(tmp_path, monkeypatch):
    received_values = []

    def fake_load_settings(values, *, dry_run):
        received_values.append(values)
        return settings(tmp_path, dry_run=dry_run)

    monkeypatch.setattr(scraper, "load_settings", fake_load_settings)

    code = run_main(["--dry-run"], values=None, pipeline=FakePipeline())

    assert code == ExitCode.SUCCESS
    assert received_values == [{}]


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


def test_runtime_modes_are_mutually_exclusive():
    with pytest.raises(SystemExit) as captured:
        run_main(["--collect-only", "--deliver-only"], values={})
    assert captured.value.code == 2


def test_deliver_only_absent_batch_is_safe_success(capsys):
    pipeline = ModePipeline(PipelineResult(0, 0, False, ()))

    code = run_main(
        ["--deliver-only"],
        values=production_values(),
        pipeline=pipeline,
    )

    assert code == ExitCode.SUCCESS
    assert pipeline.calls == [(False, True)]
    assert "deliver_only=no_batch" in capsys.readouterr().out


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
    def __init__(
        self,
        status=None,
        error: Exception | None = None,
        *,
        policy_status=True,
        daily_status=True,
    ):
        self.status = status
        self.policy_status = policy_status
        self.daily_status = daily_status
        self.error = error
        self.calls = []

    def rpc(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "picks_policy_allowlist_status":
            data = self.policy_status
        elif name == "daily_pick_schema_status":
            data = self.daily_status
        else:
            data = self.status
        return FakeRpcCall(data, self.error)


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
    assert client.calls == [
        ("scraper_schema_status", {}),
        ("picks_policy_allowlist_status", {}),
    ]
    assert driver_calls == []


def test_build_pipeline_configures_shared_lineup_resolver_when_key_exists(
    tmp_path,
):
    client = FakeSupabase({
        "public_picks": True,
        "publish_pick_batch": True,
        "resume_pick_batch": True,
        "source_audit": True,
        "version": 2,
    })
    configured = replace(
        settings(tmp_path, dry_run=False),
        api_football_key="lineup-secret",
    )

    pipeline = scraper.build_pipeline(
        configured,
        client_factory=lambda _url, _key: client,
    )

    assert isinstance(pipeline.lineup_resolver, LineupResolver)


def test_daily_pipeline_requires_daily_schema_before_runner_or_chrome(tmp_path):
    status = {
        "public_picks": True,
        "publish_pick_batch": True,
        "resume_pick_batch": True,
        "source_audit": True,
        "version": 2,
    }
    configured = replace(
        settings(tmp_path, dry_run=False),
        daily_portfolio_enabled=True,
        daily_portfolio_date="2026-08-23",
    )
    ready = FakeSupabase(status, daily_status=True)

    pipeline = scraper.build_pipeline(
        configured,
        client_factory=lambda _url, _key: ready,
    )

    assert isinstance(pipeline, LegacyPipeline)
    assert ready.calls[-1] == ("daily_pick_schema_status", {})

    missing = FakeSupabase(status, daily_status=False)
    with pytest.raises(scraper.ConfigError, match="daily portfolio migration"):
        scraper.build_pipeline(
            configured,
            client_factory=lambda _url, _key: missing,
        )


def test_schema_probe_rejects_an_unsafe_policy_allowlist_before_chrome(tmp_path):
    client = FakeSupabase(
        {
            "public_picks": True,
            "publish_pick_batch": True,
            "resume_pick_batch": True,
            "source_audit": True,
            "version": 2,
        },
        policy_status=False,
    )
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

    assert client.calls == [
        ("scraper_schema_status", {}),
        ("picks_policy_allowlist_status", {}),
    ]
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
            "source_starts_at": "2099-08-21T01:00:00Z",
        }
    ]
    surface_event = {
        "source": "playdoit",
        "source_event_id": "event-pumas-atlas",
        "sport": "soccer",
        "observed_at": "2026-08-20T20:00:00Z",
        "starts_at": "2099-08-21T01:00:00Z",
    }
    monkeypatch.setattr(
        scraper,
        "fase1_escaneo_superficie",
        lambda _driver, **_kw: [surface_event],
    )
    monkeypatch.setattr(scraper, "fase2_comparacion_mercado", lambda *_a, **_kw: {})
    monkeypatch.setattr(scraper, "fase3_filtro_inteligente", lambda *_a, **_kw: ["target"])
    monkeypatch.setattr(scraper, "fase4_inmersion", lambda *_a, **_kw: ["deep"])
    monkeypatch.setattr(scraper, "fase5_memoria_historica", lambda *_a, **_kw: "history")
    monkeypatch.setattr(scraper, "fase6_analisis_final", lambda *_a, **_kw: selected)


def test_prepared_daily_rows_include_cross_source_physical_identity():
    base = {
        "pick": "Local gana",
        "partido": "América vs Pumas",
        "cuota": 1.8,
        "es_parlay": False,
        "source": "playdoit",
        "source_event_id": "event-1",
        "source_market_key": "h2h|full_time|",
        "source_selection_key": "home",
    }
    mirror = {
        **base,
        "partido": "Pumas contra America",
        "source": "the-odds-api",
        "source_event_id": "provider-event-99",
    }

    first = scraper._prepare_persisted_pick_rows([base], generated_date="2026-08-23")
    second = scraper._prepare_persisted_pick_rows([mirror], generated_date="2026-08-23")

    assert first[0]["physical_event_key"] == second[0]["physical_event_key"]


def test_prepared_daily_rows_never_trust_a_supplied_physical_identity():
    row = {
        "pick": "Local gana",
        "partido": "América vs Pumas",
        "cuota": 1.8,
        "es_parlay": False,
        "physical_event_key": "attacker-controlled-key",
    }

    prepared = scraper._prepare_persisted_pick_rows(
        [row], generated_date="2026-08-23"
    )

    assert prepared[0]["physical_event_key"].startswith("physical:v1:")
    assert prepared[0]["physical_event_key"] != "attacker-controlled-key"


def test_prepared_daily_rows_reject_missing_parlay_flag():
    with pytest.raises(ValueError, match="es_parlay"):
        scraper._prepare_persisted_pick_rows(
            [{"partido": "América vs Pumas"}], generated_date="2026-08-23"
        )


def test_residential_event_watch_rows_are_playdoit_only_utc_and_deduplicated():
    rows = scraper._residential_event_watch_rows([
        {
            "source": "playdoit",
            "source_event_id": "event-1",
            "sport": "soccer",
            "observed_at": "2026-08-23T12:00:00-06:00",
            "starts_at": "2026-08-23T14:00:00-06:00",
        },
        {
            "source": "playdoit",
            "source_event_id": "event-1",
            "sport": "soccer",
            "observed_at": "2026-08-23T12:00:00-06:00",
            "starts_at": "2026-08-23T14:00:00-06:00",
        },
        {
            "source": "the-odds-api",
            "source_event_id": "external-1",
            "sport": "soccer",
            "observed_at": "2026-08-23T18:00:00Z",
            "starts_at": "2026-08-23T20:00:00Z",
        },
    ])

    assert rows == ({
        "source": "playdoit",
        "source_event_id": "event-1",
        "sport": "soccer",
        "source_observed_at": "2026-08-23T18:00:00Z",
        "source_starts_at": "2026-08-23T20:00:00Z",
    },)


def test_residential_event_watch_rows_fail_on_conflicting_duplicate():
    first = {
        "source": "playdoit",
        "source_event_id": "event-1",
        "sport": "soccer",
        "observed_at": "2026-08-23T18:00:00Z",
        "starts_at": "2026-08-23T20:00:00Z",
    }
    with pytest.raises(ValueError, match="conflicting"):
        scraper._residential_event_watch_rows([
            first,
            {**first, "starts_at": "2026-08-23T21:00:00Z"},
        ])


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


def test_collect_only_persists_without_delivery_or_public_file(
    tmp_path, monkeypatch
):
    stub_successful_legacy_phases(monkeypatch)
    repository = DeliveryRecordFailureRepository()
    driver = FakeDriver()
    transport_calls = []
    monkeypatch.setattr(
        scraper,
        "TelegramHttpTransport",
        lambda _token: transport_calls.append(True),
    )

    result = LegacyPipeline(
        settings(tmp_path, dry_run=False),
        repository=repository,
        history_client=object(),
        driver_factory=lambda: driver,
    ).run(collect_only=True)

    assert result.persisted is True
    assert result.failed_deliveries == ()
    assert transport_calls == []
    assert driver.quit_calls == 1
    assert not settings(tmp_path, dry_run=False).public_picks_path.exists()


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


class DailyRepository:
    def __init__(self, *, release_response=None, resume_response=None):
        self.release_response = release_response
        self.resume_response = resume_response
        self.stage_calls = []
        self.release_calls = []
        self.resume_daily_calls = []
        self.delivery_calls = []
        self.event_watch_calls = []

    def resume(self, *_args):
        raise AssertionError("daily mode must not use the legacy resume RPC")

    def publish(self, *_args):
        raise AssertionError("daily mode must not use the legacy publish RPC")

    def stage_daily(self, run_key, portfolio_date, source_hash, picks):
        self.stage_calls.append((run_key, portfolio_date, source_hash, picks))
        return {
            "scan_id": "scan-1",
            "portfolio_date": portfolio_date,
            "revision": 1,
            "created": True,
        }

    def release_daily(self, run_key, portfolio_date):
        self.release_calls.append((run_key, portfolio_date))
        return self.release_response

    def resume_daily(self, run_key):
        self.resume_daily_calls.append(run_key)
        return self.resume_response

    def record_delivery(self, run_id, destination, success, error=""):
        self.delivery_calls.append((run_id, destination, success, error))

    def record_residential_events(self, events):
        self.event_watch_calls.append(events)
        return len(events)


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
        "source_starts_at": "2099-08-21T01:00:00Z",
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


def daily_release_response(*, delivery_status=None, created=True):
    public_source = {
        "partido": "Pumas vs Atlas",
        "pick": "Pumas gana",
        "cuota": 1.8,
        "confianza": "Respaldo alto",
        "razonamiento": None,
        "es_parlay": False,
        "visibility": "public",
        "source": "playdoit",
        "source_event_id": "event-public",
        "source_market_key": "market-public",
        "source_selection_key": "home",
        "source_observed_at": "2026-08-20T20:00:00Z",
        "source_starts_at": "2099-08-21T01:00:00Z",
    }
    premium_source = {
        **public_source,
        "partido": "América vs Tigres",
        "pick": "Más de 2.5",
        "razonamiento": "Datos oficiales completos",
        "visibility": "premium",
        "source_event_id": "event-premium",
        "source_market_key": "market-premium",
        "source_selection_key": "over",
    }
    rows = []
    for index, source in enumerate((public_source, premium_source), start=1):
        row = {column: source.get(column) for column in PERSISTED_PICK_COLUMNS}
        row["id"] = index
        rows.append(row)
    return {
        "run_id": "run-daily",
        "batch_id": "batch-daily",
        "created": created,
        "delivery_status": {} if delivery_status is None else delivery_status,
        "portfolio_date": "2026-08-23",
        "revision": 2,
        "feed_eligible": False,
        "picks": rows,
        "delivery_picks": [rows[1]],
    }


def test_daily_collect_only_stages_private_draft_without_delivery_or_public_file(
    tmp_path, monkeypatch
):
    stub_successful_legacy_phases(monkeypatch)
    repository = DailyRepository()
    driver = FakeDriver()
    daily_settings = replace(
        settings(tmp_path, dry_run=False),
        daily_portfolio_enabled=True,
        daily_portfolio_date="2026-08-23",
    )

    result = LegacyPipeline(
        daily_settings,
        repository=repository,
        history_client=object(),
        driver_factory=lambda: driver,
        clock=lambda: datetime(2026, 8, 24, 4, 30, tzinfo=timezone.utc),
    ).run(collect_only=True)

    assert result.persisted is True
    assert result.failed_deliveries == ()
    assert len(repository.stage_calls) == 1
    assert repository.stage_calls[0][:2] == ("test-run", "2026-08-23")
    assert repository.release_calls == []
    assert len(repository.event_watch_calls) == 1
    assert repository.event_watch_calls[0][0]["source_event_id"] == (
        "event-pumas-atlas"
    )
    assert repository.delivery_calls == []
    assert driver.quit_calls == 1
    assert not daily_settings.public_picks_path.exists()


def test_daily_deliver_only_releases_delta_without_starting_chrome(
    tmp_path, monkeypatch
):
    repository = DailyRepository(release_response=daily_release_response())
    sent = []
    monkeypatch.setattr(
        scraper,
        "TelegramHttpTransport",
        lambda _token: lambda destination, text: sent.append(
            (destination.name, text)
        ),
    )
    daily_settings = replace(
        settings(tmp_path, dry_run=False),
        daily_portfolio_enabled=True,
        daily_portfolio_date="2026-08-23",
    )

    result = LegacyPipeline(
        daily_settings,
        repository=repository,
        history_client=object(),
        driver_factory=lambda: (_ for _ in ()).throw(
            AssertionError("driver must not start in daily delivery-only mode")
        ),
        clock=lambda: datetime(2026, 8, 23, 18, tzinfo=timezone.utc),
    ).run(deliver_only=True)

    assert result.persisted is True
    assert repository.resume_daily_calls == ["test-run"]
    assert repository.release_calls == [("test-run", "2026-08-23")]
    assert [name for name, _text in sent] == ["admin", "vip"]
    assert all("Más de 2.5" in text for _name, text in sent)
    assert repository.delivery_calls == [
        ("run-daily", "admin", True, ""),
        ("run-daily", "vip", True, ""),
    ]
    public_payload = json.loads(daily_settings.public_picks_path.read_text("utf-8"))
    assert [row["pick"] for row in public_payload] == ["Pumas gana"]


def test_daily_deliver_only_resumes_exact_release_without_creating_another(
    tmp_path, monkeypatch
):
    response = daily_release_response(created=False)
    repository = DailyRepository(resume_response=response)
    monkeypatch.setattr(
        scraper,
        "TelegramHttpTransport",
        lambda _token: lambda _destination, _text: None,
    )
    daily_settings = replace(
        settings(tmp_path, dry_run=False),
        daily_portfolio_enabled=True,
        daily_portfolio_date="2026-08-23",
    )

    result = LegacyPipeline(
        daily_settings,
        repository=repository,
        driver_factory=lambda: (_ for _ in ()).throw(
            AssertionError("driver must not start")
        ),
        clock=lambda: datetime(2026, 8, 23, 18, tzinfo=timezone.utc),
    ).run(deliver_only=True)

    assert result.persisted is True
    assert repository.resume_daily_calls == ["test-run"]
    assert repository.release_calls == []


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


def test_deliver_only_never_starts_chrome_and_sends_missing_destination(
    tmp_path, monkeypatch
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
        lambda _token: lambda destination, _text: sent.append(destination.name),
    )

    result = LegacyPipeline(
        settings(tmp_path, dry_run=False),
        repository=repository,
        history_client=object(),
        driver_factory=lambda: (_ for _ in ()).throw(
            AssertionError("driver must not start in delivery-only mode")
        ),
    ).run(deliver_only=True)

    assert result.persisted is True
    assert result.failed_deliveries == ()
    assert sent == ["vip"]
    assert repository.resume_calls == ["test-run"]


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


def test_resume_expiring_between_rpc_and_delivery_removes_file_and_sends_nothing(
    tmp_path, monkeypatch
):
    response = resumed_response(delivery_status={})
    response["picks"][0]["source_starts_at"] = "2026-08-21T01:00:00Z"
    repository = ResumeRepository(response)
    sent = []
    moments = iter(
        (
            datetime(2026, 8, 21, 0, 59, 59, tzinfo=timezone.utc),
            datetime(2026, 8, 21, 1, 0, 0, tzinfo=timezone.utc),
        )
    )
    monkeypatch.setattr(
        scraper,
        "TelegramHttpTransport",
        lambda _token: lambda destination, text: sent.append((destination, text)),
    )

    with pytest.raises(scraper.PersistenceFailure, match="stale persisted picks"):
        LegacyPipeline(
            settings(tmp_path, dry_run=False),
            repository=repository,
            driver_factory=lambda: (_ for _ in ()).throw(
                AssertionError("driver must not start")
            ),
            clock=lambda: next(moments),
        ).run()

    assert not settings(tmp_path, dry_run=False).public_picks_path.exists()
    assert sent == []
    assert repository.delivery_calls == []


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

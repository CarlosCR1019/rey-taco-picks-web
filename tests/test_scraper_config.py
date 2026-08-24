from pathlib import Path

import pytest

import backend.scraper_config as scraper_config
from backend.scraper_config import BACKEND_DIR, ConfigError, REPO_ROOT, load_settings


def test_paths_are_repository_anchored_when_cwd_changes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    settings = load_settings({}, dry_run=True)

    assert settings.public_picks_path == REPO_ROOT / "frontend" / "public" / "picks.json"
    assert settings.queue_path == REPO_ROOT / "backend" / "channel_queue.json"


def test_production_requires_supabase_write_credentials():
    with pytest.raises(ConfigError, match="SUPABASE_URL.*SUPABASE_SERVICE_ROLE_KEY"):
        load_settings({}, dry_run=False)


def test_production_requires_a_stable_run_key_before_dependencies_are_built():
    with pytest.raises(ConfigError, match="SCRAPER_RUN_KEY.*GITHUB_RUN_ID"):
        load_settings(
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "service-role",
            },
            dry_run=False,
        )


def test_run_key_prefers_explicit_value_then_github_run_id():
    explicit = load_settings(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role",
            "SCRAPER_RUN_KEY": "scheduled-window",
            "GITHUB_RUN_ID": "4242",
        },
        dry_run=False,
    )
    github = load_settings(
        {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role",
            "GITHUB_RUN_ID": "4242",
        },
        dry_run=False,
    )

    assert explicit.run_key == "scheduled-window"
    assert github.run_key == "github-run:4242"


def test_dry_run_allows_missing_supabase_write_credentials():
    settings = load_settings({}, dry_run=True)

    assert settings.supabase_url == ""
    assert settings.service_role_key == ""


def test_api_football_key_is_optional_and_trimmed():
    missing = load_settings({}, dry_run=True)
    configured = load_settings(
        {"API_FOOTBALL_KEY": " lineup-secret "}, dry_run=True
    )

    assert missing.api_football_key == ""
    assert configured.api_football_key == "lineup-secret"


def test_injected_mapping_does_not_read_dotenv(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "ambient-url")
    settings = load_settings({"SUPABASE_URL": "injected-url"}, dry_run=True)

    assert settings.supabase_url == "injected-url"


def test_telegram_canonical_values_and_compatibility_fallbacks():
    settings = load_settings(
        {
            "TELEGRAM_ADMIN_ID": "admin",
            "TELEGRAM_CHAT_ID": "legacy-admin",
            "TELEGRAM_VIP_CHANNEL_ID": "vip",
            "TELEGRAM_CHANNEL_ID": "legacy-channel",
            "TELEGRAM_FREE_CHANNEL_ID": "free",
        },
        dry_run=True,
    )
    assert settings.telegram_admin_id == "admin"
    assert settings.telegram_vip_id == "vip"
    assert settings.telegram_free_id == "free"

    fallback = load_settings(
        {"TELEGRAM_CHAT_ID": "legacy-admin", "TELEGRAM_CHANNEL_ID": "legacy-channel"},
        dry_run=True,
    )
    assert fallback.telegram_admin_id == "legacy-admin"
    assert fallback.telegram_vip_id == "legacy-channel"
    assert fallback.telegram_free_id == ""


def test_dotenv_path_is_module_relative_and_environment_overrides_file(monkeypatch):
    calls = []

    def fake_dotenv_values(path):
        calls.append(path)
        return {"SUPABASE_URL": "file-url"}

    monkeypatch.setattr(scraper_config, "dotenv_values", fake_dotenv_values)
    monkeypatch.setenv("SUPABASE_URL", "environment-url")
    monkeypatch.chdir(Path(__file__).parent)
    settings = load_settings(None, dry_run=True)

    assert calls == [BACKEND_DIR / ".env"]
    assert settings.supabase_url == "environment-url"


def test_daily_portfolio_mode_is_explicit_and_defaults_off():
    assert load_settings({}, dry_run=True).daily_portfolio_enabled is False
    assert load_settings(
        {"DAILY_PORTFOLIO_ENABLED": "true"}, dry_run=True
    ).daily_portfolio_enabled is True


def test_production_daily_mode_requires_one_stable_iso_date():
    base = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "SCRAPER_RUN_KEY": "run-1",
        "DAILY_PORTFOLIO_ENABLED": "true",
    }
    with pytest.raises(ConfigError, match="DAILY_PORTFOLIO_DATE"):
        load_settings(base, dry_run=False)
    configured = load_settings(
        {**base, "DAILY_PORTFOLIO_DATE": "2026-08-23"},
        dry_run=False,
    )
    assert configured.daily_portfolio_date == "2026-08-23"


@pytest.mark.parametrize("value", ["2026-8-23", "2026-08-23 ", "bad-date"])
def test_daily_portfolio_date_rejects_noncanonical_values(value):
    base = {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "SCRAPER_RUN_KEY": "run-1",
        "DAILY_PORTFOLIO_ENABLED": "true",
        "DAILY_PORTFOLIO_DATE": value,
    }
    with pytest.raises(ConfigError, match="DAILY_PORTFOLIO_DATE"):
        load_settings(base, dry_run=False)


@pytest.mark.parametrize("value", ["1", "yes", "TRUE ", "false "])
def test_daily_portfolio_mode_rejects_ambiguous_values(value):
    with pytest.raises(ConfigError, match="DAILY_PORTFOLIO_ENABLED"):
        load_settings({"DAILY_PORTFOLIO_ENABLED": value}, dry_run=True)

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


def test_dry_run_allows_missing_supabase_write_credentials():
    settings = load_settings({}, dry_run=True)

    assert settings.supabase_url == ""
    assert settings.service_role_key == ""


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

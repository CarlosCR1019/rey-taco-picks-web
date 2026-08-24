"""Runtime configuration for the scraper and its publishing paths."""

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

from dotenv import dotenv_values


BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent


class ConfigError(RuntimeError):
    """Raised when required scraper configuration is not available."""


@dataclass(frozen=True)
class ScraperSettings:
    dry_run: bool
    run_key: str
    supabase_url: str
    service_role_key: str
    groq_api_key: str
    odds_api_key: str
    telegram_token: str
    telegram_admin_id: str
    telegram_vip_id: str
    telegram_free_id: str
    public_picks_path: Path
    queue_path: Path
    api_football_key: str = ""


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    value = value.strip()
    return value


def _settings_values(values: Mapping[str, str | None] | None) -> Mapping[str, str | None]:
    if values is not None:
        return values

    # Resolve explicitly from this module so invocation cwd has no effect.
    file_values = dict(dotenv_values(BACKEND_DIR / ".env"))
    # Environment variables are the runtime override for dotenv defaults.
    file_values.update(os.environ)
    return file_values


def load_settings(
    values: Mapping[str, str | None] | None = None, *, dry_run: bool
) -> ScraperSettings:
    """Load and validate scraper settings from an injected mapping or backend/.env."""
    source = _settings_values(values)
    supabase_url = _clean(source.get("SUPABASE_URL"))
    service_role_key = _clean(source.get("SUPABASE_SERVICE_ROLE_KEY"))
    explicit_run_key = _clean(source.get("SCRAPER_RUN_KEY"))
    github_run_id = _clean(source.get("GITHUB_RUN_ID"))
    run_key = explicit_run_key or (
        f"github-run:{github_run_id}" if github_run_id else ""
    )

    if not dry_run:
        missing = [
            key
            for key, value in (
                ("SUPABASE_URL", supabase_url),
                ("SUPABASE_SERVICE_ROLE_KEY", service_role_key),
            )
            if not value
        ]
        if not run_key:
            missing.append("SCRAPER_RUN_KEY or GITHUB_RUN_ID")
        if missing:
            raise ConfigError(f"Required scraper configuration missing: {', '.join(missing)}")

    return ScraperSettings(
        dry_run=dry_run,
        run_key=run_key,
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        groq_api_key=_clean(source.get("GROQ_API_KEY")),
        odds_api_key=_clean(source.get("ODDS_API_KEY")),
        api_football_key=_clean(source.get("API_FOOTBALL_KEY")),
        telegram_token=_clean(source.get("TELEGRAM_BOT_TOKEN")),
        telegram_admin_id=_clean(source.get("TELEGRAM_ADMIN_ID"))
        or _clean(source.get("TELEGRAM_CHAT_ID")),
        telegram_vip_id=_clean(source.get("TELEGRAM_VIP_CHANNEL_ID"))
        or _clean(source.get("TELEGRAM_CHANNEL_ID")),
        telegram_free_id=_clean(source.get("TELEGRAM_FREE_CHANNEL_ID")),
        public_picks_path=REPO_ROOT / "frontend" / "public" / "picks.json",
        queue_path=BACKEND_DIR / "channel_queue.json",
    )

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
    supabase_url: str | None
    service_role_key: str | None
    groq_api_key: str | None
    odds_api_key: str | None
    telegram_token: str | None
    telegram_admin_id: str | None
    telegram_vip_id: str | None
    telegram_free_id: str | None
    public_picks_path: Path
    queue_path: Path


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _settings_values(values: Mapping[str, str | None] | None) -> Mapping[str, str | None]:
    if values is not None:
        return values

    # Resolve explicitly from this module so invocation cwd has no effect.
    file_values = dict(dotenv_values(BACKEND_DIR / ".env"))
    for key, value in os.environ.items():
        file_values.setdefault(key, value)
    return file_values


def load_settings(
    values: Mapping[str, str | None] | None = None, *, dry_run: bool
) -> ScraperSettings:
    """Load and validate scraper settings from an injected mapping or backend/.env."""
    source = _settings_values(values)
    supabase_url = _clean(source.get("SUPABASE_URL"))
    service_role_key = _clean(source.get("SUPABASE_SERVICE_ROLE_KEY"))

    if not dry_run:
        missing = [
            key
            for key, value in (
                ("SUPABASE_URL", supabase_url),
                ("SUPABASE_SERVICE_ROLE_KEY", service_role_key),
            )
            if value is None
        ]
        if missing:
            raise ConfigError(f"Required scraper configuration missing: {', '.join(missing)}")

    return ScraperSettings(
        dry_run=dry_run,
        supabase_url=supabase_url,
        service_role_key=service_role_key,
        groq_api_key=_clean(source.get("GROQ_API_KEY")),
        odds_api_key=_clean(source.get("ODDS_API_KEY")),
        telegram_token=_clean(source.get("TELEGRAM_BOT_TOKEN")),
        telegram_admin_id=_clean(source.get("TELEGRAM_ADMIN_ID"))
        or _clean(source.get("TELEGRAM_CHAT_ID")),
        telegram_vip_id=_clean(source.get("TELEGRAM_VIP_CHANNEL_ID"))
        or _clean(source.get("TELEGRAM_CHANNEL_ID")),
        telegram_free_id=_clean(source.get("TELEGRAM_FREE_CHANNEL_ID")),
        public_picks_path=REPO_ROOT / "frontend" / "public" / "picks.json",
        queue_path=BACKEND_DIR / "channel_queue.json",
    )

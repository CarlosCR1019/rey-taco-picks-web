from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_telegram_mini_app_uses_telegram_hmac_instead_of_gateway_jwt():
    config = tomllib.loads(
        (ROOT / "supabase" / "config.toml").read_text(encoding="utf-8")
    )

    assert config["functions"]["telegram-mini-app"]["verify_jwt"] is False

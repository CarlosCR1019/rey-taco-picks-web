from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "telegram-mini-app.yml"


def test_telegram_mini_app_deploy_is_manual_scoped_and_safe_by_default():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in text
    assert "default: false" in text
    assert "contents: read" in text
    assert "deno@2.4.4 test --node-modules-dir=auto" in text
    assert "functions deploy telegram-mini-app" in text
    assert "--no-verify-jwt" in text
    assert "secrets set" in text
    assert 'TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN"' in text
    assert 'SITE_URL="$SITE_URL"' in text
    assert "Validate signed Mini App request" in text
    assert "setChatMenuButton" in text
    assert "getChatMenuButton" in text
    assert "sendMessage" not in text
    assert "backend/scraper.py" not in text
    assert "pick-release" not in text
    assert "database password" not in text.lower()

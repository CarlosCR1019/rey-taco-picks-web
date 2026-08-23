from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_SCRIPTS = ROOT / "scripts" / "windows"
INSTALLER = WINDOWS_SCRIPTS / "Install-ReyTacoRunner.ps1"
PYTHON_BOOTSTRAP = WINDOWS_SCRIPTS / "Initialize-ReyTacoPythonToolcache.ps1"
DRY_RUN = WINDOWS_SCRIPTS / "Invoke-ReyTacoDryRun.ps1"
RUNBOOK = ROOT / "docs" / "operations" / "windows-runners.md"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_installer_requires_admin_private_repo_and_official_runner():
    text = source(INSTALLER)
    assert "WindowsPrincipal" in text
    assert "RepositoryIsPrivate" in text
    assert "https://github.com/CarlosCR1019/rey-taco-picks" in text
    assert "https://github.com/actions/runner/releases/download/" in text
    assert "RunnerSha256" in text
    assert "Get-FileHash" in text
    assert "Read-Host -AsSecureString" in text
    assert "playdoit-residential" in text
    assert "--runasservice" in text
    assert "C:\\actions-runner" in text


def test_installer_never_persists_tokens_or_accepts_production_secrets():
    text = source(INSTALLER)
    forbidden_commands = ("Set-Content", "Add-Content", "Out-File", "Start-Transcript")
    forbidden_secrets = (
        "SUPABASE_SERVICE_ROLE_KEY",
        "TELEGRAM_BOT_TOKEN",
        "META_SYSTEM_USER_ACCESS_TOKEN",
    )
    assert not any(command in text for command in forbidden_commands)
    assert not any(secret in text for secret in forbidden_secrets)


def test_python_toolcache_bootstrap_is_admin_pinned_and_token_free():
    text = source(PYTHON_BOOTSTRAP)
    assert "WindowsPrincipal" in text
    assert "3.11.9-9947079978/python-3.11.9-win32-x64.zip" in text
    assert "C92A530D9AC9539FEEA075BB033E7E03580412999D2E2833B7B62D948DA60D03" in text
    assert "Get-FileHash" in text
    assert "AGENT_TOOLSDIRECTORY" in text
    assert "setup.ps1" in text
    assert "x64.complete" in text
    for secret in (
        "SUPABASE_SERVICE_ROLE_KEY",
        "TELEGRAM_BOT_TOKEN",
        "META_SYSTEM_USER_ACCESS_TOKEN",
    ):
        assert secret not in text


def test_runner_installer_warms_python_before_registering_service():
    text = source(INSTALLER)
    warm_index = text.index("Initialize-ReyTacoPythonToolcache.ps1")
    configure_index = text.index("& .\\config.cmd")
    assert warm_index < configure_index


def test_dry_run_finds_repository_and_cannot_publish():
    text = source(DRY_RUN)
    assert "$env:USERPROFILE" in text
    assert "Get-ChildItem" in text
    assert "backend\\scraper.py" in text
    assert "--dry-run" in text
    assert "New-Item" in text
    assert "Remove-Item" in text
    assert "dry_run=true" in text
    for forbidden in (
        "SUPABASE_SERVICE_ROLE_KEY",
        "TELEGRAM_BOT_TOKEN",
        "META_SYSTEM_USER_ACCESS_TOKEN",
    ):
        assert forbidden not in text
    for unsafe_marker in (
        "persistence=written",
        "telegram=sent",
        "meta=sent",
        "cookie",
        "token",
    ):
        assert unsafe_marker in text


def test_runbook_names_both_machines_and_preserves_user_control():
    text = source(RUNBOOK)
    assert "rey-taco-carlos" in text
    assert "rey-taco-respaldo" in text
    assert "privado" in text.lower()
    assert "token" in text.lower()
    assert "servicio" in text.lower()
    assert "no apaga" in text.lower()
    assert "Initialize-ReyTacoPythonToolcache.ps1" in text
    assert "Invoke-ReyTacoDryRun.ps1" in text

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_SCRIPTS = ROOT / "scripts" / "windows"
INSTALLER = WINDOWS_SCRIPTS / "Install-ReyTacoRunner.ps1"
PYTHON_BOOTSTRAP = WINDOWS_SCRIPTS / "Initialize-ReyTacoPythonToolcache.ps1"
DRY_RUN = WINDOWS_SCRIPTS / "Invoke-ReyTacoDryRun.ps1"
INTERACTIVE_LAUNCHER = WINDOWS_SCRIPTS / "Start-ReyTacoInteractiveRunner.ps1"
STARTUP_REGISTRAR = WINDOWS_SCRIPTS / "Register-ReyTacoInteractiveStartup.ps1"
INTERACTIVE_MIGRATOR = WINDOWS_SCRIPTS / "Convert-ReyTacoRunnerToInteractive.ps1"
SERVICE_ROLLBACK = WINDOWS_SCRIPTS / "Restore-ReyTacoRunnerService.ps1"
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
    assert '--labels "playdoit-residential,$RunnerName"' in text
    assert "--runasservice" not in text
    assert "Register-ReyTacoInteractiveStartup.ps1" in text
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
    assert "Push-Location -LiteralPath $ExtractDirectory" in text
    assert "Pop-Location" in text
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


def test_interactive_launcher_is_non_admin_hidden_and_token_free():
    text = source(INTERACTIVE_LAUNCHER)
    assert "REY_TACO_BROWSER_MODE" in text
    assert "interactive" in text
    assert "run.cmd" in text
    assert "WindowsPrincipal" not in text
    assert "SUPABASE_SERVICE_ROLE_KEY" not in text
    assert "TELEGRAM_BOT_TOKEN" not in text
    assert "META_SYSTEM_USER_ACCESS_TOKEN" not in text


def test_startup_task_is_interactive_limited_and_idempotent():
    text = source(STARTUP_REGISTRAR)
    assert "-LogonType Interactive" in text
    assert "-RunLevel Limited" in text
    assert "AtLogOn" in text
    assert "Register-ScheduledTask" in text
    assert "-Force" in text


def test_migration_preserves_registration_and_removes_only_service():
    text = source(INTERACTIVE_MIGRATOR)
    assert ".runner" in text
    assert ".service" in text
    assert "sc.exe delete" in text
    assert "svc.cmd" not in text
    assert "Remove-Item" not in text
    assert "config.cmd remove" not in text


def test_rollback_restores_service_without_deleting_runner_state():
    text = source(SERVICE_ROLLBACK)
    assert "Unregister-ScheduledTask" in text
    assert ".service" in text
    assert "RunnerService.exe" in text
    assert "sc.exe create" in text
    assert "sc.exe start" in text
    assert "sc.exe failure" in text
    assert "restart/0/restart/60000/restart/60000" in text
    assert "NT AUTHORITY\\NETWORK SERVICE" in text
    assert "svc.cmd" not in text
    assert "Remove-Item" not in text


def test_dry_run_finds_repository_and_cannot_publish():
    text = source(DRY_RUN)
    assert "$env:USERPROFILE" in text
    assert "Get-ChildItem" in text
    assert "backend\\scraper.py" in text
    assert "--dry-run" in text
    assert "New-Item" in text
    assert "Remove-Item" in text
    assert "dry_run=true" in text
    assert "C:\\actions-runner\\_work\\_tool\\Python\\3.11.9\\x64\\python.exe" in text
    assert "REY_TACO_BROWSER_MODE" in text
    assert "interactive" in text
    assert "browser_mode=interactive" in text
    assert "source_error=(source_blocked|source_invalid)" in text
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


def test_runbook_documents_interactive_migration_recovery_and_rollback():
    text = source(RUNBOOK)
    normalized = text.lower()
    assert "rey taco picks interactive runner" in normalized
    assert "convert-reytacorunnertointeractive.ps1" in normalized
    assert "restore-reytacorunnerservice.ps1" in normalized
    assert "pantalla bloqueada" in normalized
    assert "inicio de sesión natural" in normalized
    assert "pc opuesta" in normalized
    assert "rollback" in normalized
    assert "no fuerza" in normalized
    assert "reinicio" in normalized

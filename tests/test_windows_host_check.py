from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "windows" / "Test-ReyTacoRunnerHost.ps1"


def checker_source() -> str:
    return CHECKER.read_text(encoding="utf-8")


def test_checker_is_read_only_and_never_requests_secrets():
    source = checker_source()
    forbidden_commands = (
        "Set-Content",
        "Add-Content",
        "Out-File",
        "Remove-Item",
        "Set-ItemProperty",
        "Start-Transcript",
        "Read-Host",
    )
    assert not any(command in source for command in forbidden_commands)
    assert "SUPABASE_SERVICE_ROLE_KEY" not in source
    assert "TELEGRAM_BOT_TOKEN" not in source
    assert "FB_PAGE_ACCESS_TOKEN" not in source


def test_checker_covers_hard_compatibility_requirements():
    source = checker_source()
    assert "Win32_OperatingSystem" in source
    assert 'OSArchitecture -match "64"' in source
    assert '$env:PROCESSOR_ARCHITECTURE -eq "AMD64"' in source
    assert "Get-PSDrive -Name C" in source
    assert "5GB" in source
    assert 'Test-NetConnection -ComputerName $HostName -Port 443' in source
    assert '"github.com"' in source
    assert '"api.github.com"' in source
    assert '"www.playdoit.mx"' in source


def test_checker_reports_remediable_setup_without_changing_the_pc():
    source = checker_source()
    assert "WindowsPrincipal" in source
    assert "Google\\Chrome\\Application\\chrome.exe" in source
    assert 'Get-Command -Name "git"' in source
    assert 'Get-Command -Name "py"' in source
    assert 'Get-Command -Name "ffmpeg"' in source
    assert 'Get-Command -Name "ffprobe"' in source
    assert 'Get-Command -Name "tesseract"' in source
    assert 'Add-Check -Name "ffmpeg" -Class "SETUP"' in source
    assert 'Add-Check -Name "ffprobe" -Class "SETUP"' in source
    assert 'Add-Check -Name "tesseract" -Class "SETUP"' in source
    assert "powercfg.exe /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE" in source
    assert 'READY_WITH_SETUP' in source
    assert 'NOT_READY' in source
    assert 'READY' in source


def test_single_chrome_path_is_counted_as_a_collection():
    source = checker_source()
    assert '@($ChromeCandidates).Count -gt 0' in source


def test_python_probe_accepts_any_python_three_version_at_least_311():
    source = checker_source()
    assert '$PythonLauncher.Source -3 -c' in source
    assert '$PythonLauncher.Source -3.11 -c' not in source


def test_checker_emits_one_machine_readable_result_line():
    source = checker_source()
    assert 'Write-Output "RESULT=$Verdict"' in source
    assert 'Write-Output "CHECK=' in source

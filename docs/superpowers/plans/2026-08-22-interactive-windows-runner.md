# Interactive Windows Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace headless Windows-service collection with a safe interactive runner that starts at sign-in, keeps Chrome minimized, detects Playdoit blocks truthfully, and fails over to the other PC.

**Architecture:** Keep the existing hybrid boundary: a Windows runner performs `--collect-only`, while GitHub-hosted jobs resume the exact persisted batch for Telegram and Meta. Add focused browser-mode and source-health modules, run each Windows runner through an interactive Scheduled Task, and route recovery to the opposite named runner. Preserve the current runner registration and Python tool cache during migration.

**Tech Stack:** Python 3.11, Selenium/undetected-chromedriver, pytest, GitHub Actions YAML, PowerShell 5.1/7, Windows Task Scheduler, GitHub self-hosted runner.

---

## File Map

- Create `backend/playdoit_health.py`: classify valid, blocked, and invalid Playdoit pages without logging page contents.
- Create `backend/playdoit_browser.py`: resolve browser mode, construct Chrome options, and enforce the interactive minimization gate.
- Modify `backend/scraper.py`: use the focused runtime modules and map source failures to a stable recoverable exit code.
- Create `tests/test_playdoit_health.py`: source-health unit tests.
- Create `tests/test_playdoit_browser.py`: browser-mode and minimization unit tests.
- Modify `tests/test_scraper_cli.py`: stable exit-code and sanitized source-failure tests.
- Modify `.github/workflows/collector.yml`: interactive browser environment, unique labels, opposite-PC recovery.
- Modify `tests/test_scraper_workflow.py`: workflow routing and security contracts.
- Create `scripts/windows/Start-ReyTacoInteractiveRunner.ps1`: non-admin hidden launcher executed by Task Scheduler.
- Create `scripts/windows/Register-ReyTacoInteractiveStartup.ps1`: idempotent Scheduled Task registration.
- Create `scripts/windows/Convert-ReyTacoRunnerToInteractive.ps1`: one-time service-to-task migration preserving registration.
- Create `scripts/windows/Restore-ReyTacoRunnerService.ps1`: rollback to the existing service topology.
- Modify `scripts/windows/Install-ReyTacoRunner.ps1`: fresh PCs register interactive runners instead of services.
- Modify `scripts/windows/Invoke-ReyTacoDryRun.ps1`: use the runner tool cache and explicit interactive mode.
- Modify `tests/test_windows_runner_assets.py`: PowerShell contracts, labels, rollback, and no-secret checks.
- Modify `docs/operations/windows-runners.md`: interactive operation, migration, verification, and rollback instructions.

This plan does not consume credits, replace keys, or expand The Odds API. That
provider remains an optional later fallback after its quota is available; the
acceptance path here must succeed through a valid Playdoit catalog.

### Task 1: Truthful Playdoit source-health classification

**Files:**
- Create: `tests/test_playdoit_health.py`
- Create: `backend/playdoit_health.py`
- Modify: `backend/scraper.py:28-45, 800-881, 1783-1790, 2424-2467`
- Modify: `tests/test_scraper_cli.py:55-175`

- [ ] **Step 1: Write the failing source-health tests**

```python
from backend.playdoit_health import (
    PlaydoitSourceBlocked,
    PlaydoitSourceInvalid,
    assert_playdoit_source_healthy,
)


def test_block_page_is_recoverable_and_does_not_echo_ip_or_ray_id():
    title = "Acceso bloqueado"
    body = "Nuestro sistema detuvo la solicitud. RAY ID abc123 TU IP 203.0.113.4"

    try:
        assert_playdoit_source_healthy(title=title, body=body, source="<html></html>")
    except PlaydoitSourceBlocked as error:
        assert error.code == "source_blocked"
        assert "203.0.113.4" not in str(error)
        assert "abc123" not in str(error)
    else:
        raise AssertionError("blocked source was accepted")


def test_rendered_altenar_page_is_valid_even_before_event_filtering():
    assert_playdoit_source_healthy(
        title="Playdoit.mx",
        body="Deportes Liga MX",
        source='<div id="altenar"><div></div></div>',
    )


def test_unrendered_page_is_recoverable_source_invalid():
    try:
        assert_playdoit_source_healthy(
            title="Playdoit.mx", body="Menú", source="<html><body>Menú</body></html>"
        )
    except PlaydoitSourceInvalid as error:
        assert error.code == "source_invalid"
    else:
        raise AssertionError("invalid source was accepted")
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `python -m pytest tests/test_playdoit_health.py -q`

Expected: collection error because `backend.playdoit_health` does not exist.

- [ ] **Step 3: Implement the focused health module**

```python
from __future__ import annotations


class PlaydoitSourceError(RuntimeError):
    code = "source_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class PlaydoitSourceBlocked(PlaydoitSourceError):
    code = "source_blocked"


class PlaydoitSourceInvalid(PlaydoitSourceError):
    code = "source_invalid"


def assert_playdoit_source_healthy(*, title: str, body: str, source: str) -> None:
    normalized_title = title.casefold()
    normalized_body = body.casefold()
    normalized_source = source.casefold()
    blocked = "acceso bloqueado" in normalized_title or (
        "ray id" in normalized_body and "tu ip" in normalized_body
    )
    if blocked:
        raise PlaydoitSourceBlocked()
    if "altenar" not in normalized_source:
        raise PlaydoitSourceInvalid()
```

- [ ] **Step 4: Verify the health module tests pass**

Run: `python -m pytest tests/test_playdoit_health.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Add failing CLI and phase integration tests**

Extend `tests/test_scraper_cli.py` so `ExitCode.__members__` includes
`SOURCE: ExitCode(7)`, a fake pipeline raising `PlaydoitSourceBlocked` returns
`ExitCode.SOURCE`, and captured output equals `source_error=source_blocked`
without provider details. Add a phase test using a fake driver whose title/body
represent the blocked page and assert the phase raises before category parsing.

```python
def test_source_failure_is_recoverable_and_sanitized(capsys):
    code = run_main(
        ["--dry-run"],
        values={},
        pipeline=FakePipeline(error=scraper.PlaydoitSourceBlocked()),
    )
    assert code == ExitCode.SOURCE
    assert "source_error=source_blocked" in capsys.readouterr().out
```

- [ ] **Step 6: Run the focused integration tests and verify RED**

Run: `python -m pytest tests/test_scraper_cli.py -q`

Expected: failures because `ExitCode.SOURCE` and scraper integration are absent.

- [ ] **Step 7: Wire health checking and the recoverable exit code**

In `fase1_escaneo_superficie`, after the initial bounded page wait and before
decimal/category interaction, call:

```python
assert_playdoit_source_healthy(
    title=str(driver.title or ""),
    body=str(driver.find_element("tag name", "body").text or ""),
    source=str(driver.page_source or ""),
)
```

Do not swallow `PlaydoitSourceError` in the phase's broad exception:

```python
except PlaydoitSourceError:
    raise
except Exception as error:
    print(f"   ⚠️ Nota en escáner Playdoit; failure={type(error).__name__}")
```

Add `SOURCE = 7` to `ExitCode` and map it before the generic exception:

```python
except PlaydoitSourceError as error:
    print(f"source_error={error.code}")
    return ExitCode.SOURCE
```

- [ ] **Step 8: Run all health/CLI tests**

Run: `python -m pytest tests/test_playdoit_health.py tests/test_scraper_cli.py -q`

Expected: all tests pass and no real browser/network calls occur.

- [ ] **Step 9: Commit source-health classification**

```powershell
git add backend/playdoit_health.py backend/scraper.py tests/test_playdoit_health.py tests/test_scraper_cli.py
git commit -m "fix: classify blocked Playdoit sources"
```

### Task 2: Explicit interactive browser mode and minimization gate

**Files:**
- Create: `tests/test_playdoit_browser.py`
- Create: `backend/playdoit_browser.py`
- Modify: `backend/scraper.py:18-25, 370-412`

- [ ] **Step 1: Write failing browser-mode tests**

```python
import pytest

from backend.playdoit_browser import (
    BrowserMode,
    InteractiveBrowserUnavailable,
    configure_chrome_options,
    gate_interactive_driver,
    resolve_browser_mode,
)


class FakeOptions:
    def __init__(self):
        self.arguments = []

    def add_argument(self, value):
        self.arguments.append(value)


class FakeDriver:
    def __init__(self, hidden=True):
        self.hidden = hidden
        self.calls = []

    def minimize_window(self):
        self.calls.append("minimize")

    def execute_script(self, script):
        self.calls.append(script)
        return self.hidden

    def quit(self):
        self.calls.append("quit")


def test_interactive_override_wins_over_github_ci():
    mode = resolve_browser_mode(
        {"REY_TACO_BROWSER_MODE": "interactive", "GITHUB_ACTIONS": "true"}
    )
    assert mode is BrowserMode.INTERACTIVE


def test_interactive_options_start_minimized_without_headless():
    options = configure_chrome_options(FakeOptions(), BrowserMode.INTERACTIVE)
    assert "--start-minimized" in options.arguments
    assert "--headless=new" not in options.arguments


def test_interactive_gate_minimizes_and_requires_hidden_document():
    driver = FakeDriver(hidden=True)
    gate_interactive_driver(driver, BrowserMode.INTERACTIVE)
    assert driver.calls[:2] == ["minimize", "return document.hidden === true"]


def test_interactive_gate_closes_failed_window():
    driver = FakeDriver(hidden=False)
    with pytest.raises(InteractiveBrowserUnavailable):
        gate_interactive_driver(driver, BrowserMode.INTERACTIVE)
    assert driver.calls[-1] == "quit"
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_playdoit_browser.py -q`

Expected: collection error because `backend.playdoit_browser` does not exist.

- [ ] **Step 3: Implement browser-mode helpers**

```python
from __future__ import annotations

from collections.abc import Mapping
from enum import Enum


class BrowserMode(str, Enum):
    LOCAL = "local"
    INTERACTIVE = "interactive"
    HEADLESS = "headless"


class InteractiveBrowserUnavailable(RuntimeError):
    pass


def resolve_browser_mode(env: Mapping[str, str] | None = None) -> BrowserMode:
    source = dict(env or {})
    explicit = str(source.get("REY_TACO_BROWSER_MODE") or "").strip().lower()
    if explicit:
        try:
            return BrowserMode(explicit)
        except ValueError as error:
            raise InteractiveBrowserUnavailable("invalid browser mode") from error
    if source.get("CI") or source.get("GITHUB_ACTIONS"):
        return BrowserMode.HEADLESS
    return BrowserMode.LOCAL


def configure_chrome_options(options, mode: BrowserMode):
    for argument in (
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1920,1080",
        "--disable-gpu",
    ):
        options.add_argument(argument)
    if mode is BrowserMode.HEADLESS:
        options.add_argument("--headless=new")
    else:
        options.add_argument("--start-minimized")
    return options


def gate_interactive_driver(driver, mode: BrowserMode) -> None:
    if mode is not BrowserMode.INTERACTIVE:
        return
    driver.minimize_window()
    if driver.execute_script("return document.hidden === true") is not True:
        driver.quit()
        raise InteractiveBrowserUnavailable("interactive minimization failed")
```

- [ ] **Step 4: Verify browser helper tests pass**

Run: `python -m pytest tests/test_playdoit_browser.py -q`

Expected: `4 passed`.

- [ ] **Step 5: Add a failing scraper driver-factory contract test**

Add a test that injects a fake Chrome constructor, sets
`REY_TACO_BROWSER_MODE=interactive`, and asserts the minimization gate occurs
before the returned driver can receive `get()`.

- [ ] **Step 6: Run the contract test and verify RED**

Run: `python -m pytest tests/test_playdoit_browser.py -q`

Expected: the new integration test fails because `get_chrome_driver` still
infers headless from CI and never gates the driver.

- [ ] **Step 7: Refactor `get_chrome_driver` to use the helpers**

Resolve the mode once, build fresh options for each undetected-chromedriver
attempt, gate the successful driver before returning it, and log only one of:

```text
browser_mode=interactive
browser_mode=headless
browser_mode=local
```

Do not log environment variables. Preserve the existing version-pinned first
attempt and standard fallback behavior.

- [ ] **Step 8: Run browser, health, and CLI suites**

Run: `python -m pytest tests/test_playdoit_browser.py tests/test_playdoit_health.py tests/test_scraper_cli.py -q`

Expected: all pass with no Chrome process created by unit tests.

- [ ] **Step 9: Commit browser-mode support**

```powershell
git add backend/playdoit_browser.py backend/scraper.py tests/test_playdoit_browser.py
git commit -m "feat: add minimized interactive browser mode"
```

### Task 3: Opposite-PC workflow recovery

**Files:**
- Modify: `tests/test_scraper_workflow.py`
- Modify: `.github/workflows/collector.yml`

- [ ] **Step 1: Write failing workflow routing tests**

Add exact assertions that both collection jobs set
`REY_TACO_BROWSER_MODE: interactive`, the primary exposes
`recovery_label`, a step with `if: always()` maps each known runner name to the
other label, and recovery includes the expression in `runs-on`.

```python
def test_recovery_targets_the_opposite_interactive_runner():
    workflow = _workflow(COLLECTOR_WORKFLOW)
    primary = workflow["jobs"]["collect_primary"]
    recovery = workflow["jobs"]["collect_recovery"]

    assert primary["env"]["REY_TACO_BROWSER_MODE"] == "interactive"
    assert recovery["env"]["REY_TACO_BROWSER_MODE"] == "interactive"
    assert primary["outputs"]["recovery_label"] == (
        "${{ steps.recovery_route.outputs.recovery_label }}"
    )
    route = _step(primary, "Choose opposite recovery runner")
    assert route["if"] == "always()"
    assert "rey-taco-carlos" in route["run"]
    assert "rey-taco-respaldo" in route["run"]
    assert "${{ needs.collect_primary.outputs.recovery_label }}" in recovery["runs-on"]
```

- [ ] **Step 2: Run the workflow tests and verify RED**

Run: `python -m pytest tests/test_scraper_workflow.py -q`

Expected: failure because the current workflow has neither interactive mode nor
unique recovery routing.

- [ ] **Step 3: Implement primary output and recovery routing**

Add to `collect_primary`:

```yaml
outputs:
  recovery_label: ${{ steps.recovery_route.outputs.recovery_label }}
env:
  REY_TACO_BROWSER_MODE: interactive
```

Append an always-run PowerShell step:

```yaml
- name: Choose opposite recovery runner
  id: recovery_route
  if: always()
  shell: powershell
  run: |
    if ("${{ runner.name }}" -eq "rey-taco-carlos") {
      "recovery_label=rey-taco-respaldo" >> $env:GITHUB_OUTPUT
    } elseif ("${{ runner.name }}" -eq "rey-taco-respaldo") {
      "recovery_label=rey-taco-carlos" >> $env:GITHUB_OUTPUT
    } else {
      throw "Unknown residential runner name"
    }
```

Set the recovery `runs-on` list to include
`${{ needs.collect_primary.outputs.recovery_label }}` and add the same browser
mode. Preserve the shared run key, read-only permissions, pinned action SHAs,
and cloud job.

- [ ] **Step 4: Run workflow/security tests**

Run: `python -m pytest tests/test_scraper_workflow.py tests/test_source_security.py -q`

Expected: all pass.

- [ ] **Step 5: Commit workflow failover**

```powershell
git add .github/workflows/collector.yml tests/test_scraper_workflow.py
git commit -m "feat: route recovery to opposite Windows runner"
```

### Task 4: Hidden interactive startup, migration, and rollback scripts

**Files:**
- Create: `scripts/windows/Start-ReyTacoInteractiveRunner.ps1`
- Create: `scripts/windows/Register-ReyTacoInteractiveStartup.ps1`
- Create: `scripts/windows/Convert-ReyTacoRunnerToInteractive.ps1`
- Create: `scripts/windows/Restore-ReyTacoRunnerService.ps1`
- Modify: `scripts/windows/Install-ReyTacoRunner.ps1`
- Modify: `tests/test_windows_runner_assets.py`

- [ ] **Step 1: Write failing Windows asset tests**

Define constants for all four new scripts. Assert:

```python
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
    assert "InteractiveToken" in text
    assert "RunLevel Limited" in text
    assert "AtLogOn" in text
    assert "Register-ScheduledTask" in text
    assert "-Force" in text


def test_migration_preserves_registration_and_removes_only_service():
    text = source(INTERACTIVE_MIGRATOR)
    assert ".runner" in text
    assert "svc.cmd uninstall" in text
    assert "Remove-Item" not in text


def test_rollback_restores_service_without_deleting_runner_state():
    text = source(SERVICE_ROLLBACK)
    assert "Unregister-ScheduledTask" in text
    assert "svc.cmd install" in text
    assert "svc.cmd start" in text
    assert "Remove-Item" not in text
```

Update the installer assertion: it must not contain `--runasservice`; it must
register labels `playdoit-residential,$RunnerName` and call the startup
registrar after `config.cmd` succeeds.

- [ ] **Step 2: Run asset tests and verify RED**

Run: `python -m pytest tests/test_windows_runner_assets.py -q`

Expected: missing-file failures and the old `--runasservice` assertion failure.

- [ ] **Step 3: Create the non-admin launcher**

The complete behavior is:

```powershell
[CmdletBinding()]
param([string]$RunnerDirectory = "C:\actions-runner")
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RunCommand = Join-Path $RunnerDirectory "run.cmd"
$Registration = Join-Path $RunnerDirectory ".runner"
if (-not (Test-Path -LiteralPath $Registration)) { throw "Runner no registrado." }
if (-not (Test-Path -LiteralPath $RunCommand)) { throw "Falta run.cmd." }
$env:REY_TACO_BROWSER_MODE = "interactive"
Push-Location -LiteralPath $RunnerDirectory
try {
    & $RunCommand
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
```

Task Scheduler invokes this script with `powershell.exe -NoLogo -NoProfile
-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File ...`.

- [ ] **Step 4: Create the idempotent task registrar**

Require administrator only for registration. Use task name
`Rey Taco Picks Interactive Runner`, the current signed-in account,
`New-ScheduledTaskTrigger -AtLogOn -User $UserAccount`, and:

```powershell
$Principal = New-ScheduledTaskPrincipal -UserId $UserAccount `
    -LogonType InteractiveToken -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Force
```

Validate that the launcher and `.runner` exist before changing Task Scheduler.
Output only `RESULT=INTERACTIVE_STARTUP_REGISTERED TASK=<name> USER=<account>`.

- [ ] **Step 5: Create migration and rollback scripts**

Migration must verify exactly one `actions.runner.*` service belongs to
`C:\actions-runner`, stop it, run `svc.cmd uninstall`, register the task, start
the task manually, and verify its state is `Running` or GitHub Runner has a live
process. It must never call `config.cmd remove` or delete the runner directory.

Rollback must stop/unregister only `Rey Taco Picks Interactive Runner`, call
`svc.cmd install` and `svc.cmd start`, and verify one running
`actions.runner.*` service. Both scripts require an administrator session and
emit sanitized `RESULT=` lines.

- [ ] **Step 6: Modify the fresh installer**

Remove `--runasservice`, change labels to:

```powershell
--labels "playdoit-residential,$RunnerName"
```

After successful `config.cmd`, invoke
`Register-ReyTacoInteractiveStartup.ps1 -RunnerDirectory $RunnerDirectory`,
start the new Scheduled Task, and report
`RESULT=RUNNER_INSTALLED_INTERACTIVE NAME=<runner> TASK=<task>`.

- [ ] **Step 7: Run asset tests and PowerShell parsers**

```powershell
python -m pytest tests/test_windows_runner_assets.py -q
$files = Get-ChildItem scripts/windows -Filter *.ps1
foreach ($file in $files) {
  $tokens = $null; $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile(
    $file.FullName, [ref]$tokens, [ref]$errors
  )
  if ($errors.Count) { throw "PowerShell parse failure: $($file.Name)" }
}
```

Expected: tests pass and parser loop emits no error.

- [ ] **Step 8: Commit interactive Windows startup**

```powershell
git add scripts/windows tests/test_windows_runner_assets.py
git commit -m "feat: run Windows collectors interactively"
```

### Task 5: Safe headed probe and operations guide

**Files:**
- Modify: `scripts/windows/Invoke-ReyTacoDryRun.ps1`
- Modify: `docs/operations/windows-runners.md`
- Modify: `tests/test_windows_runner_assets.py`

- [ ] **Step 1: Write failing probe/runbook assertions**

Require the dry-run script to use the pinned runner Python at
`C:\actions-runner\_work\_tool\Python\3.11.9\x64\python.exe`, set
`REY_TACO_BROWSER_MODE=interactive`, require `browser_mode=interactive`, reject
`source_error=source_blocked` and `source_error=source_invalid`, and never print
or accept production secrets. Require the runbook to document task name,
migration, locked-screen behavior, natural-login verification, opposite-PC
recovery, and rollback.

- [ ] **Step 2: Run asset tests and verify RED**

Run: `python -m pytest tests/test_windows_runner_assets.py -q`

Expected: assertions fail against the old `py -3` probe and service runbook.

- [ ] **Step 3: Update the safe probe**

Use the pinned tool-cache Python, set the browser mode only for the child
process, retain `--dry-run`, and accept only exit codes `0`, `3`, or `4` when no
source error is present. Preserve current forbidden marker checks. Add:

```powershell
if ($OutputText -notmatch "browser_mode=interactive") {
    throw "Chrome no confirmó el modo interactivo minimizado."
}
if ($OutputText -match "source_error=(source_blocked|source_invalid)") {
    throw "Playdoit no entregó una fuente válida."
}
```

- [ ] **Step 4: Rewrite the operational sections that claim service/headless**

Document the exact safe order: validate host, initialize Python, install or
convert runner, manually start task, run safe probe, verify GitHub Idle, confirm
before a real workflow, observe next natural sign-in, then repeat on the backup
PC. State that no script forces sign-out/reboot or changes power settings.

- [ ] **Step 5: Run tests and parser checks**

Run: `python -m pytest tests/test_windows_runner_assets.py tests/test_windows_host_check.py -q`

Expected: all pass.

- [ ] **Step 6: Commit probe and documentation**

```powershell
git add scripts/windows/Invoke-ReyTacoDryRun.ps1 docs/operations/windows-runners.md tests/test_windows_runner_assets.py
git commit -m "docs: operate minimized interactive collectors"
```

### Task 6: Full offline verification and release package

**Files:**
- Verify all modified source files.
- Generate: `C:\Users\carlo\Desktop\Rey-Taco-Runner-Windows.zip`

- [ ] **Step 1: Run focused regression suites**

```powershell
python -m pytest tests/test_playdoit_browser.py tests/test_playdoit_health.py tests/test_scraper_cli.py tests/test_scraper_workflow.py tests/test_windows_runner_assets.py tests/test_windows_host_check.py tests/test_source_security.py -q
```

Expected: all pass with no external writes or browser launches.

- [ ] **Step 2: Run the complete Python suite**

Run: `python -m pytest -q`

Expected: all tests pass; no failed, errored, or skipped release-gate tests.

- [ ] **Step 3: Verify syntax and worktree integrity**

```powershell
python -m compileall -q backend tests
git diff --check
git status --short
```

Expected: compile and diff checks succeed; status contains only intended plan
implementation changes before their commits, then becomes clean.

- [ ] **Step 4: Build a recoverable desktop package**

Move any existing ZIP to a timestamped backup using explicit desktop paths,
then package the host check, Python initializer, fresh installer, launcher,
registrar, converter, rollback, dry-run script, and runbook. List archive entries
and calculate SHA-256. Do not include `.env`, `.runner`, `.credentials`, `_diag`,
repository files, or any token.

- [ ] **Step 5: Commit any verification-only corrections and push**

```powershell
git push origin master
git status --short
```

Expected: push succeeds and worktree is clean.

### Task 7: Migrate and prove Carlos's PC

**Files/State:**
- Modify external Windows state only after action-time confirmation.
- Use `C:\actions-runner` and Scheduled Task `Rey Taco Picks Interactive Runner`.

- [ ] **Step 1: Request immediate migration confirmation**

Explain that the next action stops/uninstalls only the current GitHub Runner
service, preserves its registration and files, and registers an interactive
sign-in task. Do not launch elevation before the user confirms.

- [ ] **Step 2: Capture read-only pre-migration evidence**

Verify `.runner`, Python marker, exact runner service name/account/state, current
runner process, Scheduled Task absence, and clean Git worktree. Do not print
credential files or secrets.

- [ ] **Step 3: Run the converter elevated**

Launch visible PowerShell with `-Verb RunAs` so the user can accept UAC. Capture
sanitized output to `C:\actions-runner\interactive-migration.log`; the script
itself must not record credentials. Require
`RESULT=RUNNER_CONVERTED_INTERACTIVE`.

- [ ] **Step 4: Verify runtime state**

Require no running `actions.runner.*` service, exactly one running Scheduled
Task/runner process under the signed-in non-admin user, browser mode environment
set only by the launcher, and GitHub UI showing `rey-taco-carlos` online/Idle.

- [ ] **Step 5: Run the safe minimized probe**

Run `Invoke-ReyTacoDryRun.ps1`. Observe that Chrome only appears minimized in
the taskbar, never becomes foreground, closes itself, reports
`browser_mode=interactive`, and extracts real events when Playdoit has a catalog.
Require `RESULT=DRY_RUN_SAFE`.

- [ ] **Step 6: Exercise rollback without leaving it active**

With immediate confirmation, run rollback, verify the original service returns,
then rerun the converter and reverify the interactive task. This proves recovery
without deleting registration.

### Task 8: Controlled production workflow and backup-PC handoff

**Files/State:**
- GitHub Actions workflow `collector.yml` on `master`.
- Girlfriend package `C:\Users\carlo\Desktop\Rey-Taco-Runner-Windows.zip`.

- [ ] **Step 1: Request immediate confirmation for the production workflow**

State that a valid batch may write Supabase, send Telegram, and publish the
exact persisted public pick to Facebook and Instagram. Do not click Run Workflow
until confirmed.

- [ ] **Step 2: Dispatch and monitor the exact commit**

Verify `collect_primary` runs on `rey-taco-carlos`, Setup Python passes, logs
`browser_mode=interactive`, source health is valid, and Chrome remains minimized.
If the source fails, confirm recovery targets `rey-taco-respaldo` rather than the
same runner. Do not treat `no_events` or `no_candidates` as infrastructure
failure.

- [ ] **Step 3: Verify cloud delivery truthfully**

If a batch exists, verify the persisted run key, Telegram receipts, Facebook
receipt, and Instagram receipt without exposing tokens. If no batch exists,
require `deliver_only=no_batch` and no external publication.

- [ ] **Step 4: Hand off the backup-PC package**

Provide the updated ZIP and SHA-256. The girlfriend runs the host check first.
Fresh registration requires a new, short-lived GitHub runner token entered only
on her PC after separate confirmation. Install with runner name
`rey-taco-respaldo`, run the minimized safe probe, and verify GitHub Idle.

- [ ] **Step 5: Observe automatic startup at the next natural Windows sign-in**

Do not force reboot or sign-out. At the next natural Windows sign-in on each PC,
verify the Scheduled Task starts the correct runner automatically. Mark the
two-PC migration complete only after both observations.

## Final Completion Gate

Before claiming completion, use `superpowers:verification-before-completion`.
Report exact test counts, the production workflow URL/status, whether a batch
was or was not published, the runner/task state on each PC, package SHA-256, and
the one remaining external limitation: Playdoit availability cannot be
guaranteed. Do not claim the backup PC complete until its natural-sign-in check
has actually occurred.

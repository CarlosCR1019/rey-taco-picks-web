# Hybrid Residential Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let either trusted Windows 11 PC collect and persist one audited batch while GitHub-hosted jobs deliver that exact batch without reopening Playdoit.

**Architecture:** Add explicit collection-only and delivery-only CLI modes around the existing idempotent run ledger. A new `collector.yml` sends collection only to repository-level Windows runners carrying `playdoit-residential`; a final `ubuntu-latest` job resumes the same `SCRAPER_RUN_KEY` and performs Telegram and Meta delivery. Installation and dry-run scripts never receive production delivery secrets.

**Tech Stack:** Python 3.11, pytest, GitHub Actions YAML, PowerShell 5.1+, Supabase RPCs, Windows actions runner.

---

### Task 1: Separate persistence from delivery in the scraper CLI

**Files:**
- Modify: `tests/test_scraper_cli.py`
- Modify: `backend/scraper.py`
- Modify: `backend/pick_publisher.py`
- Test: `tests/test_scraper_cli.py`

- [ ] **Step 1: Write failing CLI-mode tests**

Add tests that require the mutually exclusive flags `--collect-only` and `--deliver-only`. The collection test uses a real `LegacyPipeline` with stubbed phases and asserts that `repository.publish` is called, `record_delivery` is not called, the Chrome driver closes, and the public JSON file is not written. The delivery test returns one persisted response from `repository.resume`, asserts the driver factory is never called, and asserts only missing Telegram destinations are delivered. Add a no-batch delivery test expecting exit code `0` and `deliver_only=no_batch`.

```python
class ModePipeline:
    def __init__(self, result):
        self.result = result

    def run(self, *, collect_only=False, deliver_only=False):
        assert collect_only is False
        assert deliver_only is True
        return self.result


def test_collect_only_persists_without_delivery_or_public_file(tmp_path, monkeypatch):
    result = pipeline.run(collect_only=True)
    assert result.persisted is True
    assert repository.delivery_calls == []
    assert not settings.public_picks_path.exists()


def test_deliver_only_never_starts_chrome_and_sends_missing_destinations(
    tmp_path, monkeypatch
):
    result = pipeline.run(deliver_only=True)
    assert result.persisted is True
    assert sent == ["vip"]


def test_deliver_only_absent_batch_is_safe_success(capsys):
    pipeline = ModePipeline(PipelineResult(0, 0, False, ()))
    assert run_main(
        ["--deliver-only"], values=production_values(), pipeline=pipeline
    ) == ExitCode.SUCCESS
    assert "deliver_only=no_batch" in capsys.readouterr().out
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_scraper_cli.py -q`

Expected: FAIL because the new flags and mode arguments do not exist.

- [ ] **Step 3: Add a non-exposing publication option**

Extend `AuditedBatchPublisher.publish` and `publish_batch` with keyword `write_public: bool = True`. Validate it is a real boolean and skip `_write_public_payload` only when false. Existing callers retain the current default.

```python
def publish(self, picks, *, dry_run: bool, write_public: bool = True):
    return publish_batch(
        self.repository,
        picks,
        self.run_key,
        self.public_path,
        dry_run=dry_run,
        write_public=write_public,
        clock=self.clock,
    )
```

- [ ] **Step 4: Implement the two exclusive runtime modes**

Add both flags to one argparse mutually-exclusive group. `LegacyPipeline.run(*, collect_only=False, deliver_only=False)` must reject both flags together and reject either flag during dry-run. `deliver_only` calls `AuditedBatchPublisher.resume`, never creates a driver, and returns a safe empty result when no exact batch exists. `collect_only` resumes without delivery when the run already exists; otherwise it runs phases 1–6 and persists through phase 7 with `deliver=False` and `write_public=False`.

```python
group = parser.add_mutually_exclusive_group()
group.add_argument("--dry-run", action="store_true")
group.add_argument("--collect-only", action="store_true")
group.add_argument("--deliver-only", action="store_true")
```

`run_main` passes only the selected keyword to the pipeline and maps an absent exact batch in delivery-only mode to `ExitCode.SUCCESS`. Collection-only still reports truthful no-event/no-candidate/persistence failures.

- [ ] **Step 5: Verify GREEN and commit**

Run: `python -m pytest tests/test_scraper_cli.py tests/test_pick_publisher.py tests/test_scraper_structure.py -q`

Expected: all selected tests PASS.

Commit: `git commit -m "feat: split residential collection from cloud delivery"`

### Task 2: Route collection to either Windows runner

**Files:**
- Create: `.github/workflows/collector.yml`
- Modify: `.github/workflows/scraper.yml`
- Modify: `tests/test_scraper_workflow.py`
- Test: `tests/test_scraper_workflow.py`

- [ ] **Step 1: Write failing workflow contracts**

Parse both workflows with `yaml.BaseLoader` and assert:

```python
RESIDENTIAL = ["self-hosted", "Windows", "X64", "playdoit-residential"]
assert collector["jobs"]["collect_primary"]["runs-on"] == RESIDENTIAL
assert collector["jobs"]["collect_recovery"]["runs-on"] == RESIDENTIAL
assert collector["jobs"]["deliver_cloud"]["runs-on"] == "ubuntu-latest"
assert collector["jobs"]["collect_recovery"]["needs"] == "collect_primary"
assert collector["jobs"]["collect_recovery"]["if"] == "failure()"
assert collector["jobs"]["deliver_cloud"]["if"] == "always() && !cancelled()"
```

Also assert that no `pull_request` trigger exists, every checkout disables credential persistence, actions are pinned to full SHAs, all three jobs share `residential:${{ github.run_id }}`, collection jobs contain no Telegram/Meta secrets, and cloud jobs contain no Playdoit/Chrome step.

- [ ] **Step 2: Run workflow tests and verify RED**

Run: `python -m pytest tests/test_scraper_workflow.py -q`

Expected: FAIL because `collector.yml` does not exist.

- [ ] **Step 3: Create `collector.yml`**

Keep cron schedules `0 16 * * *`, `0 22 * * *`, and `0 5 * * *`, plus `workflow_dispatch`. Use read-only contents permission and concurrency `rey-taco-residential-${{ github.event.schedule || 'manual' }}`. Both Windows jobs use PowerShell, install Python dependencies, and execute `python backend/scraper.py --collect-only`; exit codes `3` and `4` become safe success while `5`, `6`, and `10` remain failures. Recovery runs only after primary failure and reuses the exact run key.

The cloud job has `needs: [collect_primary, collect_recovery]`, runs with `always() && !cancelled()`, executes `python backend/scraper.py --deliver-only`, then `python -m backend.social_poster` only when delivery succeeds. It receives Supabase, Telegram, Groq, Meta token and optional destination IDs solely from GitHub Actions secrets.

- [ ] **Step 4: Leave `scraper.yml` cloud-only**

Remove its Chrome/scraper job and retain result verification on `ubuntu-latest`. Schedule verification at `0 13 * * *` and `0 19 * * *` (07:00 and 13:00 Mexico City), with manual dispatch preserved.

- [ ] **Step 5: Verify GREEN and commit**

Run: `python -m pytest tests/test_scraper_workflow.py tests/test_scraper_cli.py tests/test_source_security.py -q`

Expected: all selected tests PASS.

Commit: `git commit -m "feat: add hybrid residential collector workflow"`

### Task 3: Finish safe Windows runner assets

**Files:**
- Create: `scripts/windows/Install-ReyTacoRunner.ps1`
- Create: `scripts/windows/Invoke-ReyTacoDryRun.ps1`
- Create: `tests/test_windows_runner_assets.py`
- Create: `docs/operations/windows-runners.md`
- Test: `tests/test_windows_runner_assets.py`

- [ ] **Step 1: Write failing static security tests**

Require the installer to validate an administrator session, the fixed private repository URL, the official runner download host, a caller-supplied 64-character SHA-256, `Read-Host -AsSecureString`, label `playdoit-residential`, `--runasservice`, and `C:\actions-runner`. Forbid `Set-Content`, `Add-Content`, `Out-File`, `Start-Transcript`, Supabase, Telegram and Meta secret names.

Require the dry-run script to locate the repository by searching beneath the current user's profile, create a temporary directory, invoke `backend/scraper.py --dry-run`, reject write/delivery markers, and remove its exact temporary directory in `finally`.

- [ ] **Step 2: Run asset tests and verify RED**

Run: `python -m pytest tests/test_windows_runner_assets.py -q`

Expected: FAIL because the installer, dry-run script and tests do not exist.

- [ ] **Step 3: Implement the secure installer**

The installer accepts `RunnerName`, mandatory `RepositoryIsPrivate`, `RunnerVersion`, and `RunnerSha256`. It downloads only `https://github.com/actions/runner/releases/download/v$RunnerVersion/actions-runner-win-x64-$RunnerVersion.zip`, verifies SHA-256 before extraction, asks for the short-lived registration token as `SecureString`, runs `config.cmd` unattended with the fixed repository, unique runner name, custom label and Windows service, clears temporary plaintext in `finally`, verifies one matching `actions.runner.*` service is running, and never changes power settings.

- [ ] **Step 4: Implement the no-secret dry run**

The script finds `rey-taco-picks` without requiring a path, confirms `backend/scraper.py` exists, clears production secret variables only in the child process environment, runs `py -3 backend/scraper.py --dry-run`, requires `dry_run=true`, rejects `persistence=written`, `telegram=sent`, `meta=sent`, `cookie`, or `token`, and always removes its temporary output.

- [ ] **Step 5: Write the two-machine runbook**

Document separate one-hour registration tokens and names `rey-taco-carlos` and `rey-taco-respaldo`; the repository must already be private; both PCs keep normal user control and are never powered off by automation; the runner is installed as a service; each PC runs the checker and dry-run before enabling schedules.

- [ ] **Step 6: Parse, test and commit**

Run the PowerShell parser over every `scripts/windows/*.ps1`, then run `python -m pytest tests/test_windows_host_check.py tests/test_windows_runner_assets.py -q`.

Expected: zero parser errors and all tests PASS.

Commit: `git commit -m "feat: add secure two-PC runner bootstrap"`

### Task 4: Offline release gate

**Files:**
- Modify: `README.md`
- Modify: `docs/operations/security-and-payments.md`

- [ ] **Step 1: Document the hybrid boundary**

State that collectors receive only Supabase/Groq/Odds configuration, delivery secrets remain cloud-only, neither PC is shut down or suspended, no pull-request workflow can reach a personal runner, and real publication remains a separate approved smoke test.

- [ ] **Step 2: Run complete local verification**

```powershell
python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
python -m pyflakes backend tests
git diff --check
```

Expected: all suites and build commands exit `0`. None of these commands contacts Playdoit, Supabase production, Telegram, Meta or runner registration.

- [ ] **Step 3: Push only after verification**

Review `git status --short`, `git diff --stat`, and `git log -4 --oneline`; then push `master` as explicitly authorized by Carlos. Do not dispatch `collector.yml` until at least one runner is registered and its dry-run passes.

## Completion boundary

This plan delivers tested code, workflows, scripts and runbooks. It does not register either PC, change sleep settings, dispatch production collection, publish Telegram/Meta, or create weekend reservations. The weekend reservation/release migration is the next independent plan after this collector foundation passes.

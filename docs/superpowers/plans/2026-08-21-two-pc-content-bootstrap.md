# Two-PC Collector and Content Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make either trusted Windows 11 computer able to run the residential Playdoit collector as a background service and produce one deterministic, source-backed public content package without publishing live during installation.

**Architecture:** Keep collection on repository-level self-hosted Windows runners selected by the shared `playdoit-residential` label, while all factual copy and visuals are derived from the exact persisted public pick. Add a typed Playdoit health boundary, a pure content-package builder, deterministic logo-palette rendering, structured Meta outcomes, and token-safe Windows bootstrap scripts. Weekend reservation/release and cloud result verification remain separate plans because they have independent database and scheduling boundaries.

**Tech Stack:** Python 3.11, pytest, Selenium/undetected-chromedriver, HTML/CSS, Meta Graph API, GitHub Actions, PowerShell 7/Windows PowerShell 5.1, Windows services.

---

## File map

- `backend/source_health.py`: typed, sanitized Playdoit attempt status and bounded retry policy.
- `backend/content_package.py`: pure construction of Telegram and Meta copy from one persisted public pick.
- `backend/render_html_banner.py`: deterministic 1080×1080 rendering from an explicit content package.
- `backend/banner_template.html`: logo-palette visual with one public pick and responsible-use footer.
- `backend/social_poster.py`: separate Facebook and Instagram delivery results with nonzero failure status.
- `backend/scraper.py`: integrates source health and exposes a sanitized machine-readable summary.
- `.github/workflows/collector.yml`: residential-only collection and one bounded recovery job.
- `scripts/windows/Test-ReyTacoRunnerHost.ps1`: read-only prerequisite and power-setting diagnosis.
- `scripts/windows/Install-ReyTacoRunner.ps1`: token-safe repository-runner service installation.
- `scripts/windows/Invoke-ReyTacoDryRun.ps1`: no-write/no-message collector probe.
- `docs/operations/windows-runners.md`: installation, verification, update, and removal runbook.
- `tests/test_source_health.py`: health classification and retry tests.
- `tests/test_content_package.py`: factual-copy and public-only tests.
- `tests/test_social_poster.py`: independent Meta delivery and exit-code tests.
- `tests/test_windows_runner_assets.py`: static security contracts for PowerShell assets.
- `tests/test_scraper_workflow.py`: runner labels, stable concurrency, failover, and secret-boundary tests.

### Task 1: Add the typed Playdoit health boundary

**Files:**
- Create: `backend/source_health.py`
- Create: `tests/test_source_health.py`

- [ ] **Step 1: Write the failing status, redaction, and retry tests**

```python
from backend.source_health import (
    SourceAttempt,
    SourceStatus,
    collect_with_recovery,
    sanitized_summary,
)


def attempt(status: SourceStatus, count: int = 0) -> SourceAttempt:
    return SourceAttempt(
        status=status,
        attempt=1,
        event_count=count,
        rejection_count=0,
        error_type="TimeoutException",
    )


def test_challenge_stops_without_a_second_attempt():
    calls = []

    def collect(number: int) -> SourceAttempt:
        calls.append(number)
        return attempt(SourceStatus.CHALLENGE)

    outcome = collect_with_recovery(collect, sleep=lambda _seconds: None)
    assert outcome.status is SourceStatus.CHALLENGE
    assert calls == [1]


def test_transient_dom_failure_retries_once_then_returns_ok():
    outcomes = iter(
        [attempt(SourceStatus.DOM_UNAVAILABLE), attempt(SourceStatus.OK, 4)]
    )
    calls = []

    def collect(number: int) -> SourceAttempt:
        calls.append(number)
        return next(outcomes)

    outcome = collect_with_recovery(collect, sleep=lambda _seconds: None)
    assert outcome.status is SourceStatus.OK
    assert outcome.event_count == 4
    assert calls == [1, 2]


def test_summary_contains_no_exception_text_or_credentials():
    row = attempt(SourceStatus.NAVIGATION_ERROR)
    summary = sanitized_summary(row)
    assert summary == (
        "source_health=playdoit status=navigation_error attempt=1 "
        "events=0 rejected=0 error=TimeoutException"
    )
    assert "cookie" not in summary.lower()
    assert "token" not in summary.lower()
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `python -m pytest tests/test_source_health.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.source_health'`.

- [ ] **Step 3: Implement the complete bounded policy**

```python
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
import time
from typing import Callable


class SourceStatus(StrEnum):
    OK = "ok"
    EMPTY_SCHEDULE = "empty_schedule"
    CHALLENGE = "challenge"
    DOM_UNAVAILABLE = "dom_unavailable"
    NAVIGATION_ERROR = "navigation_error"
    INVALID_EVENTS = "invalid_events"


@dataclass(frozen=True, slots=True)
class SourceAttempt:
    status: SourceStatus
    attempt: int
    event_count: int
    rejection_count: int
    error_type: str = ""

    def __post_init__(self) -> None:
        if self.attempt not in (1, 2):
            raise ValueError("attempt must be 1 or 2")
        if self.event_count < 0 or self.rejection_count < 0:
            raise ValueError("counts must not be negative")
        if self.error_type and not self.error_type.isidentifier():
            raise ValueError("error_type must be a class name")


_RETRYABLE = frozenset(
    {
        SourceStatus.DOM_UNAVAILABLE,
        SourceStatus.NAVIGATION_ERROR,
        SourceStatus.INVALID_EVENTS,
    }
)


def collect_with_recovery(
    collect: Callable[[int], SourceAttempt],
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> SourceAttempt:
    first = replace(collect(1), attempt=1)
    if first.status not in _RETRYABLE:
        return first
    sleep(2.0)
    return replace(collect(2), attempt=2)


def sanitized_summary(value: SourceAttempt) -> str:
    error = value.error_type or "none"
    return (
        f"source_health=playdoit status={value.status.value} "
        f"attempt={value.attempt} events={value.event_count} "
        f"rejected={value.rejection_count} error={error}"
    )
```

- [ ] **Step 4: Run the focused tests to verify GREEN**

Run: `python -m pytest tests/test_source_health.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the isolated boundary**

```powershell
git add -- backend/source_health.py tests/test_source_health.py
git commit -m "feat: classify Playdoit source health"
```

### Task 2: Integrate bounded collection without weakening market validation

**Files:**
- Modify: `backend/scraper.py`
- Modify: `tests/test_scraper_pipeline.py`
- Modify: `tests/test_scraper_cli.py`
- Modify: `tests/test_scraper_structure.py`

- [ ] **Step 1: Write failing integration tests**

```python
def test_legacy_pipeline_recreates_driver_once_after_dom_failure(
    settings, monkeypatch
):
    drivers = [FakeDriver(), FakeDriver()]
    factory_calls = []
    outcomes = iter(
        [
            (
                SourceAttempt(
                    SourceStatus.DOM_UNAVAILABLE,
                    1,
                    0,
                    0,
                    "TimeoutException",
                ),
                [],
            ),
            (SourceAttempt(SourceStatus.OK, 2, 2, 0), VERIFIED_EVENTS),
        ]
    )

    def factory():
        factory_calls.append(True)
        return drivers[len(factory_calls) - 1]

    monkeypatch.setattr(scraper, "collect_playdoit_attempt", lambda *_a, **_k: next(outcomes))
    result = LegacyPipeline(settings, driver_factory=factory).run()
    assert result.event_count == 2
    assert len(factory_calls) == 2
    assert [driver.quit_calls for driver in drivers] == [1, 1]


def test_challenge_returns_no_events_and_never_publishes(settings, monkeypatch):
    repository = RecordingRepository()
    monkeypatch.setattr(
        scraper,
        "collect_playdoit_attempt",
        lambda *_a, **_k: (
            SourceAttempt(SourceStatus.CHALLENGE, 1, 0, 0),
            [],
        ),
    )
    result = LegacyPipeline(
        settings, repository=repository, driver_factory=FakeDriver
    ).run()
    assert result.event_count == 0
    assert repository.publish_calls == []
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `python -m pytest tests/test_scraper_pipeline.py tests/test_scraper_cli.py tests/test_scraper_structure.py -q`

Expected: FAIL because `collect_playdoit_attempt` and typed retry integration do not exist.

- [ ] **Step 3: Add a narrow attempt adapter**

Add this adapter beside `fase1_escaneo_superficie`; it must call the existing extractor and validators rather than parse odds itself:

```python
def collect_playdoit_attempt(driver, *, attempt, odds_api_key=None):
    try:
        events = fase1_escaneo_superficie(
            driver,
            odds_api_key=odds_api_key,
        )
    except (TimeoutException, WebDriverException) as error:
        return SourceAttempt(
            SourceStatus.NAVIGATION_ERROR,
            attempt,
            0,
            0,
            type(error).__name__,
        ), []
    if events:
        return SourceAttempt(SourceStatus.OK, attempt, len(events), 0), events
    document_status = classify_playdoit_document(driver)
    return SourceAttempt(document_status, attempt, 0, 0), []
```

`classify_playdoit_document` may read only the document title, current URL host, and presence of the existing Altenar host/shadow-root selectors. Map recognized challenge titles to `CHALLENGE`, a rendered empty market shell to `EMPTY_SCHEDULE`, and a missing application root to `DOM_UNAVAILABLE`; never read or log cookies or full HTML.

- [ ] **Step 4: Rework browser ownership around two attempts**

Use `collect_with_recovery` from `backend.source_health` through this wrapper so the diagnostic remains scalar and sanitized while verified event dictionaries stay in memory only:

```python
def collect_playdoit_with_recovery(
    driver_factory,
    *,
    odds_api_key=None,
    sleep=time.sleep,
):
    verified_events = []

    def collect(attempt_number):
        nonlocal verified_events
        driver = driver_factory()
        try:
            outcome, events = collect_playdoit_attempt(
                driver,
                attempt=attempt_number,
                odds_api_key=odds_api_key,
            )
            verified_events = list(events) if outcome.status is SourceStatus.OK else []
            return outcome
        finally:
            _cleanup_chrome_driver(driver)

    outcome = collect_with_recovery(collect, sleep=sleep)
    print(sanitized_summary(outcome))
    return outcome, verified_events
```

The second attempt is created only for the three retryable statuses. Preserve the existing API fallback only after the Playdoit outcome contains fewer than the configured minimum verified events.

- [ ] **Step 5: Run focused and existing Playdoit tests**

Run: `python -m pytest tests/test_source_health.py tests/test_playdoit_source.py tests/test_scraper_pipeline.py tests/test_scraper_cli.py tests/test_scraper_structure.py -q`

Expected: PASS, including exactly-once driver cleanup and zero persistence on challenge/empty results.

- [ ] **Step 6: Commit integration**

```powershell
git add -- backend/scraper.py tests/test_scraper_pipeline.py tests/test_scraper_cli.py tests/test_scraper_structure.py
git commit -m "feat: add bounded Playdoit recovery"
```

### Task 3: Build one factual public content package

**Files:**
- Create: `backend/content_package.py`
- Create: `tests/test_content_package.py`
- Modify: `backend/telegram_publisher.py`

- [ ] **Step 1: Write failing public-only and factual-copy tests**

```python
from datetime import datetime, timezone

import pytest

from backend.content_package import build_public_content


PUBLIC_PICK = {
    "visibility": "public",
    "es_parlay": False,
    "categoria": "Liga MX",
    "partido": "América vs Tigres",
    "pick": "Más de 2.5 goles",
    "cuota": "1.80",
    "horario": "21 de agosto, 20:00 CDMX",
    "confianza": "65%",
    "source_observed_at": "2026-08-21T15:00:00+00:00",
}


def test_content_uses_exact_persisted_facts_and_responsible_notice():
    package = build_public_content(
        PUBLIC_PICK,
        generated_at=datetime(2026, 8, 21, 16, tzinfo=timezone.utc),
    )
    assert package.event == "América vs Tigres"
    assert package.selection == "Más de 2.5 goles"
    assert package.price == "1.80"
    assert "Observado: 21 ago 2026, 09:00 CDMX" in package.facebook_caption
    assert "Verifica el momio antes de participar" in package.instagram_caption
    assert "18+" in package.facebook_caption
    assert "garantizado" not in package.facebook_caption.lower()


@pytest.mark.parametrize(
    "change",
    [
        {"visibility": "premium"},
        {"es_parlay": True},
        {"source_observed_at": ""},
        {"cuota": ""},
    ],
)
def test_content_rejects_nonpublic_or_incomplete_rows(change):
    with pytest.raises(ValueError):
        build_public_content({**PUBLIC_PICK, **change})
```

- [ ] **Step 2: Run the focused test to verify RED**

Run: `python -m pytest tests/test_content_package.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'backend.content_package'`.

- [ ] **Step 3: Implement an immutable package**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.telegram_publisher import format_pick_block


CDMX = ZoneInfo("America/Mexico_City")
MONTHS = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)


@dataclass(frozen=True, slots=True)
class PublicContentPackage:
    event: str
    selection: str
    price: str
    schedule: str
    category: str
    observed_label: str
    telegram_text: str
    facebook_caption: str
    instagram_caption: str


def _required(row, name: str) -> str:
    value = str(row.get(name, "")).strip()
    if not value:
        raise ValueError(f"missing public content field: {name}")
    return value


def _observed_label(value: str) -> str:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("source_observed_at must include an offset")
    local = observed.astimezone(CDMX)
    return (
        f"{local.day:02d} {MONTHS[local.month - 1]} {local.year}, "
        f"{local:%H:%M} CDMX"
    )


def build_public_content(row, *, generated_at=None) -> PublicContentPackage:
    if row.get("visibility") != "public" or row.get("es_parlay") is True:
        raise ValueError("content requires one public non-parlay pick")
    event = _required(row, "partido")
    selection = _required(row, "pick")
    price = _required(row, "cuota")
    schedule = _required(row, "horario")
    category = _required(row, "categoria")
    observed = _observed_label(_required(row, "source_observed_at"))
    core = (
        "🌮 Pick público de Rey Taco Picks\n\n"
        f"{category} | {event}\n"
        f"Selección: {selection}\nMomio observado: {price}\n"
        f"Horario: {schedule}\nObservado: {observed}\n\n"
        "Verifica el momio antes de participar. Análisis informativo; "
        "no garantiza resultados. 18+."
    )
    instagram = f"{core}\n\n#ReyTacoPicks #AnalisisDeportivo #PronosticosDeportivos"
    return PublicContentPackage(
        event=event,
        selection=selection,
        price=price,
        schedule=schedule,
        category=category,
        observed_label=observed,
        telegram_text=(
            f"{format_pick_block(row, public=True)}\n"
            f"Observado: {observed}\n"
            "Verifica el momio antes de participar."
        ),
        facebook_caption=core,
        instagram_caption=instagram,
    )
```

- [ ] **Step 4: Run content and Telegram tests to verify GREEN**

Run: `python -m pytest tests/test_content_package.py tests/test_telegram_publisher.py -q`

Expected: PASS and public copy contains no rationale or premium selection.

- [ ] **Step 5: Commit the content boundary**

```powershell
git add -- backend/content_package.py backend/telegram_publisher.py tests/test_content_package.py
git commit -m "feat: build factual public content packages"
```

### Task 4: Render a deterministic logo-palette banner

**Files:**
- Modify: `backend/banner_template.html`
- Modify: `backend/render_html_banner.py`
- Modify: `backend/social_banner.py`
- Modify: `tests/test_render_html_banner.py`
- Modify: `tests/test_social_banner.py`

- [ ] **Step 1: Write failing visual-contract tests**

```python
def test_template_uses_logo_palette_and_one_public_card():
    template = (ROOT / "backend/banner_template.html").read_text("utf-8")
    assert "--wine: #7b1e2b" in template.lower()
    assert "--red: #c51c32" in template.lower()
    assert "--cream: #fff4df" in template.lower()
    assert "--gold: #d4a017" in template.lower()
    assert "18+" in template
    assert "Verifica el momio" in template
    assert "fonts.googleapis.com" not in template


def test_banner_rejects_zero_or_multiple_public_picks():
    with pytest.raises(ValueError):
        renderizar_banner_estudio(picks=[])
    with pytest.raises(ValueError):
        renderizar_banner_estudio(picks=[PUBLIC_PICK, PUBLIC_PICK])
```

- [ ] **Step 2: Run focused tests to verify RED**

Run: `python -m pytest tests/test_render_html_banner.py tests/test_social_banner.py -q`

Expected: FAIL because the template uses the old dark/blue palette, external fonts, and accepts zero or three cards.

- [ ] **Step 3: Replace remote visual dependencies with repository assets**

Define CSS variables exactly as asserted, use the existing `frontend/public/logo.jpg`, and size a single central card for a 1080×1080 image. Keep the visible fields to category, event, selection, observed price, event schedule, observation time, `reytacopicks.com`, and the responsible-use footer. Remove the Google Fonts import and disable the Pollinations background path for production content.

- [ ] **Step 4: Make the renderer consume an explicit package**

Change the production call to accept exactly one persisted public pick, call `build_public_content`, HTML-escape every field, write the temporary HTML under a newly created temporary directory, render, and delete that temporary directory in `finally`. Discover the installed Chrome major version instead of hardcoding `version_main=151`.

- [ ] **Step 5: Render and inspect the actual PNG**

Run:

```powershell
python -c "from backend.render_html_banner import renderizar_banner_estudio; from tests.test_content_package import PUBLIC_PICK; renderizar_banner_estudio([PUBLIC_PICK], 'banner_hoy.png')"
```

Expected: `banner_hoy.png` is 1080×1080, shows one public pick, uses the logo palette, and contains no clipped text. Inspect it with the image viewer before committing.

- [ ] **Step 6: Run focused tests and commit**

Run: `python -m pytest tests/test_render_html_banner.py tests/test_social_banner.py -q`

Expected: PASS.

```powershell
git add -- backend/banner_template.html backend/render_html_banner.py backend/social_banner.py tests/test_render_html_banner.py tests/test_social_banner.py
git commit -m "feat: render deterministic branded pick content"
```

### Task 5: Return independent Facebook and Instagram outcomes

**Files:**
- Modify: `backend/social_poster.py`
- Create: `tests/test_social_poster.py`

- [ ] **Step 1: Write failing delivery-boundary tests**

```python
from backend.social_poster import MetaDelivery, publish_meta


class FakeMetaTransport:
    def __init__(self, *, facebook_id="", instagram_id="", instagram_error=""):
        self.facebook_id = facebook_id
        self.instagram_id = instagram_id
        self.instagram_error = instagram_error

    def publish_facebook(self, image_path, caption):
        assert image_path.name == "pick.png"
        assert "América vs Tigres" in caption
        return self.facebook_id

    def publish_instagram(self, image_url, caption):
        assert image_url.startswith("https://")
        assert "América vs Tigres" in caption
        if self.instagram_error:
            raise RuntimeError(self.instagram_error)
        return self.instagram_id


def test_facebook_success_does_not_hide_instagram_failure(tmp_path):
    transport = FakeMetaTransport(facebook_id="fb-1", instagram_error="expired")
    result = publish_meta(
        PUBLIC_PICK,
        image_path=tmp_path / "pick.png",
        public_image_url="https://reytacopicks.com/social/pick.png",
        transport=transport,
    )
    assert result == {
        "facebook": MetaDelivery(True, "fb-1", ""),
        "instagram": MetaDelivery(False, "", "delivery_failed"),
    }


def test_main_returns_failure_when_any_configured_destination_fails(monkeypatch):
    monkeypatch.setattr(
        "backend.social_poster.ejecutar_auto_post_redes",
        lambda: {"facebook": MetaDelivery(False, "", "delivery_failed")},
    )
    assert main() == 1
```

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `python -m pytest tests/test_social_poster.py -q`

Expected: FAIL because the current module returns booleans, never invokes Instagram from the entry point, logs raw provider responses, and exits successfully on failure.

- [ ] **Step 3: Implement structured, sanitized Meta delivery**

```python
@dataclass(frozen=True, slots=True)
class MetaDelivery:
    success: bool
    remote_id: str = ""
    error: str = ""


def main() -> int:
    outcomes = ejecutar_auto_post_redes()
    return 0 if outcomes and all(row.success for row in outcomes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Inject a transport into `publish_meta`. Facebook receives the local PNG; Instagram receives only an HTTPS URL for the same PNG. Convert all HTTP, JSON, token, timeout, and Graph API failures to `delivery_failed`; logs may contain the destination and error class but never the token, request body, or raw response. Do not call a destination whose required ID/token is absent; return `not_configured` distinctly so the workflow can alert without pretending it posted.

- [ ] **Step 4: Run tests and commit**

Run: `python -m pytest tests/test_social_poster.py tests/test_render_html_banner.py tests/test_source_security.py -q`

Expected: PASS.

```powershell
git add -- backend/social_poster.py tests/test_social_poster.py
git commit -m "feat: report Meta deliveries independently"
```

### Task 6: Route collection to either residential runner with bounded recovery

**Files:**
- Create: `.github/workflows/collector.yml`
- Modify: `.github/workflows/scraper.yml`
- Modify: `tests/test_scraper_workflow.py`

- [ ] **Step 1: Write failing workflow contracts**

```python
def test_collector_jobs_use_only_residential_windows_runners():
    workflow = collector_workflow()
    assert workflow["jobs"]["collect_primary"]["runs-on"] == [
        "self-hosted", "Windows", "X64", "playdoit-residential"
    ]
    assert workflow["jobs"]["collect_recovery"]["runs-on"] == [
        "self-hosted", "Windows", "X64", "playdoit-residential"
    ]


def test_recovery_reuses_run_key_and_runs_only_after_primary_failure():
    workflow = collector_workflow()
    recovery = workflow["jobs"]["collect_recovery"]
    assert recovery["needs"] == "collect_primary"
    assert recovery["if"] == "failure()"
    assert "SCRAPER_RUN_KEY" in recovery["env"]
    assert recovery["env"]["SCRAPER_RUN_KEY"] == (
        workflow["jobs"]["collect_primary"]["env"]["SCRAPER_RUN_KEY"]
    )


def test_no_pull_request_event_can_reach_personal_computers():
    workflow = collector_workflow()
    assert "pull_request" not in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
```

- [ ] **Step 2: Run workflow tests to verify RED**

Run: `python -m pytest tests/test_scraper_workflow.py -q`

Expected: FAIL because collection still targets `ubuntu-latest` and no recovery job exists.

- [ ] **Step 3: Create the residential collector workflow**

Use the existing three cron expressions and `workflow_dispatch`. Set top-level concurrency to `rey-taco-residential-${{ github.event.schedule || 'manual' }}` with `cancel-in-progress: false`. Both jobs use the four labels asserted above, a 25-minute timeout, pinned checkout/setup-python actions, `persist-credentials: false`, and PowerShell commands. Set the same stable key in both jobs:

```yaml
env:
  SCRAPER_RUN_KEY: residential:${{ github.run_id }}
```

The primary job checks out, sets up Python 3.11, installs `backend/requirements.txt`, and runs `python backend/scraper.py`. The recovery job has `needs: collect_primary`, `if: failure()`, the same setup, the same run key, and the same command. A successful, no-event, or no-candidate run must not start recovery; only infrastructure/source execution failures eligible for a second attempt may do so, so map scraper exit codes 3 and 4 to a successful safe outcome in a small PowerShell wrapper while preserving exit codes 5, 6, and 10 as failures.

- [ ] **Step 4: Keep cloud jobs off residential machines**

Reduce `.github/workflows/scraper.yml` to cloud verification/status duties or rename it during the later control-workflow plan. Every remaining job uses `ubuntu-latest`; no cloud job may contain `playdoit-residential`.

- [ ] **Step 5: Run workflow tests and commit**

Run: `python -m pytest tests/test_scraper_workflow.py tests/test_scraper_cli.py tests/test_source_security.py -q`

Expected: PASS.

```powershell
git add -- .github/workflows/collector.yml .github/workflows/scraper.yml tests/test_scraper_workflow.py
git commit -m "feat: route collection to residential runners"
```

### Task 7: Add safe Windows 11 installation and dry-run tooling

**Files:**
- Create: `scripts/windows/Test-ReyTacoRunnerHost.ps1`
- Create: `scripts/windows/Install-ReyTacoRunner.ps1`
- Create: `scripts/windows/Invoke-ReyTacoDryRun.ps1`
- Create: `tests/test_windows_runner_assets.py`
- Create: `docs/operations/windows-runners.md`

- [ ] **Step 1: Write failing static security tests**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / "scripts" / "windows" / name).read_text("utf-8")


def test_installer_requires_admin_and_private_repo_confirmation():
    text = source("Install-ReyTacoRunner.ps1")
    assert "WindowsPrincipal" in text
    assert "-RepositoryIsPrivate" in text
    assert "playdoit-residential" in text
    assert "--runasservice" in text
    assert "C:\\actions-runner" in text


def test_installer_never_writes_registration_token():
    text = source("Install-ReyTacoRunner.ps1")
    forbidden = ("Set-Content", "Add-Content", "Out-File", "Start-Transcript")
    assert not any(command in text for command in forbidden)
    assert "Read-Host -AsSecureString" in text


def test_dry_run_cannot_receive_production_secrets():
    text = source("Invoke-ReyTacoDryRun.ps1")
    assert "--dry-run" in text
    assert "SUPABASE_SERVICE_ROLE_KEY" not in text
    assert "TELEGRAM_BOT_TOKEN" not in text
```

- [ ] **Step 2: Run the static tests to verify RED**

Run: `python -m pytest tests/test_windows_runner_assets.py -q`

Expected: FAIL because the scripts do not exist.

- [ ] **Step 3: Implement the read-only prerequisite checker**

The checker returns nonzero unless all of these are true: Windows 11 x64, administrator shell available for installation, outbound HTTPS to `github.com` and `api.github.com`, at least 5 GB free on `C:`, Chrome installed, Python 3.11+ available through `py -3.11`, Git available, and AC sleep set to `Never`. It prints only pass/fail labels and remediation commands; it changes no power, firewall, browser, or account setting.

- [ ] **Step 4: Implement the token-safe installer**

Parameters are `RunnerName`, mandatory switch `RepositoryIsPrivate`, `RepositoryUrl` fixed by validation to `https://github.com/CarlosCR1019/rey-taco-picks`, `RunnerVersion`, and `RunnerSha256`. The script requires an elevated PowerShell session, refuses an existing `.runner` file, downloads only `https://github.com/actions/runner/releases/download/v$RunnerVersion/actions-runner-win-x64-$RunnerVersion.zip`, verifies the supplied 64-character SHA-256, extracts to `C:\actions-runner`, reads the one-hour registration token with `Read-Host -AsSecureString`, converts it to plaintext only for the `config.cmd` process call, clears the temporary plaintext variable in `finally`, and invokes:

```powershell
& .\config.cmd `
  --url $RepositoryUrl `
  --token $PlainRegistrationToken `
  --name $RunnerName `
  --labels "playdoit-residential" `
  --work "_work" `
  --unattended `
  --replace `
  --runasservice
```

The script then verifies one `actions.runner.*` service is `Running` and prints the runner name. It must not set repository secrets, clone the repository, request a GitHub password, or enable interactive browser profiles.

- [ ] **Step 5: Implement the local dry-run probe**

The probe creates a temporary directory, invokes `python backend/scraper.py --dry-run`, captures sanitized output, requires one `source_health=playdoit` line, rejects any output containing `persistence=written`, `telegram=sent`, `cookie`, or `token`, and always deletes the temporary directory. It returns the scraper safe outcome without writing to Supabase, Telegram, Meta, or `frontend/public/picks.json`.

- [ ] **Step 6: Write the exact two-machine runbook**

Document this order:

1. Verify `CarlosCR1019/rey-taco-picks` is private and its Actions are enabled.
2. On Carlos's PC, run the prerequisite checker, obtain a fresh repository registration token, run the installer as Administrator with runner name `rey-taco-carlos`, and verify `Idle` in GitHub.
3. On the second PC, repeat with a new token and runner name `rey-taco-respaldo`; never reuse the first token or runner directory.
4. Run `Invoke-ReyTacoDryRun.ps1` separately on each PC.
5. Dispatch one controlled collector workflow with Supabase/Telegram/Meta delivery disabled and confirm exactly one runner accepts it.
6. Enable only the collector workflow after both probes pass.
7. To remove a PC, remove its runner in GitHub first, then run `config.cmd remove` with the generated removal token; do not delete `C:\actions-runner` before deregistration.

- [ ] **Step 7: Syntax-check scripts and run tests**

Run:

```powershell
$scripts = Get-ChildItem -LiteralPath scripts/windows -Filter *.ps1
foreach ($script in $scripts) {
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseFile(
    $script.FullName,
    [ref]$null,
    [ref]$errors
  )
  if ($errors.Count) { throw ($errors | Out-String) }
}
python -m pytest tests/test_windows_runner_assets.py tests/test_scraper_workflow.py -q
```

Expected: no PowerShell parser errors and all tests PASS.

- [ ] **Step 8: Commit installer assets**

```powershell
git add -- scripts/windows tests/test_windows_runner_assets.py docs/operations/windows-runners.md
git commit -m "feat: add secure Windows runner bootstrap"
```

### Task 8: Complete offline verification without external publication

**Files:**
- Modify: `README.md`
- Modify: `docs/operations/security-and-payments.md`

- [ ] **Step 1: Add documentation contracts**

Require both documents to state that the source repository must be private before runner registration, the registration token expires quickly and is never stored, content is built only from the persisted public row, Psalms/frontend/logo assets remain present, and no live collection or external delivery is part of the automated test gate.

- [ ] **Step 2: Run the complete local gate**

Run:

```powershell
python -m pytest tests -q
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
npx --yes deno test --allow-env supabase/functions
python -m pyflakes backend tests
git diff --check
```

Expected: all Python, frontend, Deno, typecheck, build, static-analysis, and diff checks PASS. No command contacts Playdoit, Supabase production, Telegram, Meta, or GitHub runner registration.

- [ ] **Step 3: Render one local fixture banner and inspect it**

Render from `PUBLIC_PICK` in `tests/test_content_package.py`. Confirm logo, wine/red/cream/gold palette, event, selection, price, event time, observation time, CTA, and 18+ notice are visible with no overflow. Delete the fixture output after inspection.

- [ ] **Step 4: Commit documentation and verification state**

```powershell
git add -- README.md docs/operations/security-and-payments.md
git commit -m "docs: add residential collector operations"
```

## Completion boundary

This plan ends with code, workflows, scripts, documentation, and offline tests ready. It does not change repository visibility, register either computer, apply remote migrations, dispatch GitHub Actions, scrape Playdoit live, or publish to Telegram/Meta. Each of those state-changing operations requires its own controlled rollout checkpoint.

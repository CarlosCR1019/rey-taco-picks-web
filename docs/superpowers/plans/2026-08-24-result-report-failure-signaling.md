# Result Report Failure Signaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Results Verifier workflow fail after attempting every required destination whenever any result-report delivery is not confirmed.

**Architecture:** Keep independent delivery and idempotency inside `backend/result_report_publisher.py`, then add a pure health gate that accepts only `success` and `complete`. `backend/verificar_resultados.py` will call the gate after collecting and printing every report outcome, so GitHub receives a non-zero exit without skipping later destinations.

**Tech Stack:** Python 3.11, pytest, GitHub Actions, existing Supabase delivery ledger.

---

### Task 1: Add a safe result-report health gate

**Files:**
- Modify: `tests/test_result_report_publisher.py`
- Modify: `backend/result_report_publisher.py`

- [ ] **Step 1: Write failing unit tests for healthy, unhealthy, and missing outcomes**

Add the import and tests below to `tests/test_result_report_publisher.py`:

```python
import pytest

from backend.result_report_publisher import (
    destinations_for,
    require_healthy_result_reports,
    publish_result_report,
)


def test_result_report_health_accepts_success_and_complete():
    require_healthy_result_reports(
        {
            "12345678-1234-4234-8234-123456789012:evening": {
                "admin": "success",
                "vip": "complete",
                "free": "success",
            }
        }
    )


@pytest.mark.parametrize(
    "status",
    [
        "claim_failed",
        "ambiguous",
        "not_configured",
        "token_invalid",
        "delivery_failed",
        "completion_failed",
    ],
)
def test_result_report_health_rejects_unconfirmed_outcomes(status):
    outcomes = {
        "admin": "success",
        "vip": status,
        "free": "success",
    }

    with pytest.raises(
        RuntimeError,
        match=rf"vip={status}",
    ):
        require_healthy_result_reports(
            {"12345678-1234-4234-8234-123456789012:evening": outcomes}
        )


def test_result_report_health_rejects_missing_required_destination_safely():
    with pytest.raises(RuntimeError, match=r"free=missing"):
        require_healthy_result_reports(
            {
                "12345678-1234-4234-8234-123456789012:evening": {
                    "admin": "success",
                    "vip": "success",
                }
            }
        )
```

- [ ] **Step 2: Run the new tests and verify the RED state**

Run:

```powershell
python -m pytest tests/test_result_report_publisher.py -q
```

Expected: collection fails because `require_healthy_result_reports` does not exist.

- [ ] **Step 3: Implement the minimal safe health gate**

Add this code to `backend/result_report_publisher.py` after `destinations_for`:

```python
HEALTHY_RESULT_OUTCOMES = frozenset({"success", "complete"})
KNOWN_RESULT_OUTCOMES = frozenset(
    {
        "success",
        "complete",
        "claim_failed",
        "ambiguous",
        "not_configured",
        "token_invalid",
        "delivery_failed",
        "completion_failed",
    }
)


def require_healthy_result_reports(
    published: Mapping[str, Mapping[str, str]],
) -> None:
    failures: list[str] = []
    for report_key in sorted(published):
        batch_id, separator, kind = report_key.rpartition(":")
        if not separator or not batch_id or kind not in {"evening", "final"}:
            failures.append("invalid_report:invalid=invalid")
            continue
        outcomes = published[report_key]
        for destination in destinations_for(kind):
            raw_status = outcomes.get(destination, "missing")
            status = (
                raw_status
                if raw_status in KNOWN_RESULT_OUTCOMES
                else "missing" if raw_status == "missing" else "invalid"
            )
            if status not in HEALTHY_RESULT_OUTCOMES:
                failures.append(f"{report_key}:{destination}={status}")
    if failures:
        raise RuntimeError(
            "result report delivery incomplete: " + ", ".join(failures)
        )
```

The allowlist ensures the exception cannot echo credentials or remote response bodies.

- [ ] **Step 4: Run the publisher tests and verify the GREEN state**

Run:

```powershell
python -m pytest tests/test_result_report_publisher.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the health gate**

```powershell
git add -- backend/result_report_publisher.py tests/test_result_report_publisher.py
git commit -m "fix: reject incomplete result report deliveries"
```

### Task 2: Connect the health gate to the Results Verifier

**Files:**
- Create: `tests/test_result_report_workflow.py`
- Modify: `backend/verificar_resultados.py`

- [ ] **Step 1: Write failing integration tests for the verifier boundary**

Create `tests/test_result_report_workflow.py`:

```python
from __future__ import annotations

import pytest

import backend.verificar_resultados as verifier
from tests.test_result_reporting import rows_with_states


class FakeBatchRepository:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def batches(self):
        return (tuple(rows_with_states(*(["ganado"] * 6))),)


def configure_report_run(monkeypatch, outcomes):
    monkeypatch.setenv("RESULT_REPORT_MODE", "final_only")
    monkeypatch.setattr(verifier, "SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setattr(verifier, "SUPABASE_SERVICE_ROLE_KEY", "service-role")
    monkeypatch.setattr(verifier, "supabase", object())
    monkeypatch.setattr(
        verifier,
        "SupabaseResultReportRepository",
        FakeBatchRepository,
    )
    monkeypatch.setattr(
        verifier,
        "publish_result_report",
        lambda *_args, **_kwargs: dict(outcomes),
    )


def test_verifier_rejects_report_after_collecting_all_destination_outcomes(
    monkeypatch,
):
    outcomes = {
        "admin": "success",
        "vip": "success",
        "free": "success",
        "facebook": "completion_failed",
        "instagram": "success",
    }
    configure_report_run(monkeypatch, outcomes)

    with pytest.raises(RuntimeError, match=r"facebook=completion_failed"):
        verifier.publish_available_result_reports()


def test_verifier_accepts_idempotent_complete_outcomes(monkeypatch):
    outcomes = {
        "admin": "complete",
        "vip": "complete",
        "free": "complete",
        "facebook": "complete",
        "instagram": "complete",
    }
    configure_report_run(monkeypatch, outcomes)

    assert verifier.publish_available_result_reports()
```

- [ ] **Step 2: Run the workflow tests and verify the RED state**

Run:

```powershell
python -m pytest tests/test_result_report_workflow.py -q
```

Expected: the unhealthy-outcome test fails because the verifier returns normally.

- [ ] **Step 3: Invoke the health gate after every report has been attempted**

Update the import in `backend/verificar_resultados.py`:

```python
from backend.result_report_publisher import (
    SupabaseResultArtifactStore,
    publish_result_report,
    require_healthy_result_reports,
)
```

At the end of `publish_available_result_reports`, replace the direct return with:

```python
    require_healthy_result_reports(published)
    return published
```

- [ ] **Step 4: Run the focused workflow and publisher tests**

Run:

```powershell
python -m pytest tests/test_result_report_workflow.py tests/test_result_report_publisher.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the verifier integration**

```powershell
git add -- backend/verificar_resultados.py tests/test_result_report_workflow.py
git commit -m "fix: fail results workflow on incomplete delivery"
```

### Task 3: Verify locally and with an idempotent GitHub run

**Files:**
- Verify only; no planned source changes.

- [ ] **Step 1: Run the complete related test suite**

Run:

```powershell
python -m pytest tests/test_result_report_workflow.py tests/test_result_report_publisher.py tests/test_result_report_repository.py tests/test_result_reporting.py tests/test_supabase_contract.py -q
```

Expected: all tests pass with zero failures.

- [ ] **Step 2: Check the staged and unstaged diff boundaries**

Run:

```powershell
git status --short
git diff --check
```

Expected: only pre-existing unrelated user files remain dirty; the implementation commits are clean.

- [ ] **Step 3: Push the implementation commits to `master`**

Run:

```powershell
git push origin master
```

Expected: `origin/master` advances to the local `HEAD`.

- [ ] **Step 4: Dispatch the Results Verifier without manual evidence**

Trigger `.github/workflows/scraper.yml` on `master` with both optional inputs empty.

Expected: the workflow completes successfully because the existing five ledger rows are already `complete`.

- [ ] **Step 5: Inspect the job log and Supabase ledger**

Expected GitHub log:

```text
Reporte final: admin=complete, vip=complete, free=complete, facebook=complete, instagram=complete
```

Expected Supabase ledger for the report batch:

```text
total_rows=5, successful_rows=5, pending_rows=0, failed_rows=0
```

The row count must remain five, proving the validation run did not create duplicate deliveries.

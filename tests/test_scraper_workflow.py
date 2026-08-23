from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_WORKFLOW = ROOT / ".github" / "workflows" / "collector.yml"
VERIFIER_WORKFLOW = ROOT / ".github" / "workflows" / "scraper.yml"
SERVICE_ROLE_EXPRESSION = "${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
RUN_KEY_EXPRESSION = "residential:${{ github.run_id }}"
RESIDENTIAL_RUNNER = ["self-hosted", "Windows", "X64", "playdoit-residential"]


def _workflow(path: Path) -> dict:
    parsed = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return parsed


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def test_collector_jobs_use_only_residential_windows_runners():
    workflow = _workflow(COLLECTOR_WORKFLOW)
    jobs = workflow["jobs"]

    assert jobs["collect_primary"]["runs-on"] == RESIDENTIAL_RUNNER
    assert jobs["collect_recovery"]["runs-on"] == RESIDENTIAL_RUNNER
    assert jobs["deliver_cloud"]["runs-on"] == "ubuntu-latest"


def test_recovery_reuses_run_key_and_runs_only_after_primary_failure():
    workflow = _workflow(COLLECTOR_WORKFLOW)
    jobs = workflow["jobs"]
    primary = jobs["collect_primary"]
    recovery = jobs["collect_recovery"]

    assert recovery["needs"] == "collect_primary"
    assert recovery["if"] == "failure()"
    assert primary["env"]["SCRAPER_RUN_KEY"] == RUN_KEY_EXPRESSION
    assert recovery["env"]["SCRAPER_RUN_KEY"] == RUN_KEY_EXPRESSION


def test_cloud_delivery_always_uses_exact_residential_run_key():
    workflow = _workflow(COLLECTOR_WORKFLOW)
    delivery = workflow["jobs"]["deliver_cloud"]

    assert delivery["needs"] == ["collect_primary", "collect_recovery"]
    assert delivery["if"] == "always() && !cancelled()"
    assert delivery["env"]["SCRAPER_RUN_KEY"] == RUN_KEY_EXPRESSION
    assert "--deliver-only" in _step(delivery, "Deliver exact persisted batch")["run"]
    assert "backend.social_poster" in _step(delivery, "Publish exact social batch")["run"]


def test_no_pull_request_event_can_reach_personal_computers():
    workflow = _workflow(COLLECTOR_WORKFLOW)

    assert "pull_request" not in workflow["on"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "rey-taco-residential-${{ github.event.schedule || 'manual' }}",
        "cancel-in-progress": "false",
    }


def test_collection_jobs_receive_no_delivery_or_meta_secrets():
    workflow = _workflow(COLLECTOR_WORKFLOW)
    forbidden = {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_CHANNEL_ID",
        "TELEGRAM_VIP_CHANNEL_ID",
        "TELEGRAM_FREE_CHANNEL_ID",
        "META_SYSTEM_USER_ACCESS_TOKEN",
        "FB_PAGE_ID",
        "IG_USER_ID",
    }

    for job_name in ("collect_primary", "collect_recovery"):
        job = workflow["jobs"][job_name]
        assert job["env"]["SUPABASE_SERVICE_ROLE_KEY"] == SERVICE_ROLE_EXPRESSION
        assert forbidden.isdisjoint(job["env"])
        assert "--collect-only" in _step(job, "Collect and persist only")["run"]


def test_residential_jobs_bypass_execution_policy_only_inside_the_job():
    workflow = _workflow(COLLECTOR_WORKFLOW)

    for job_name in ("collect_primary", "collect_recovery"):
        assert (
            workflow["jobs"][job_name]["env"]["PSExecutionPolicyPreference"]
            == "Bypass"
        )

    assert "PSExecutionPolicyPreference" not in workflow["jobs"]["deliver_cloud"]["env"]


def test_cloud_jobs_never_open_playdoit_or_target_residential_runner():
    collector = _workflow(COLLECTOR_WORKFLOW)
    verifier = _workflow(VERIFIER_WORKFLOW)

    cloud_jobs = [collector["jobs"]["deliver_cloud"], *verifier["jobs"].values()]
    for job in cloud_jobs:
        assert job["runs-on"] == "ubuntu-latest"
        text = str(job).lower()
        assert "playdoit-residential" not in text
        assert "setup-chrome" not in text
        assert "--collect-only" not in text


def test_workflows_keep_collection_and_verification_schedules():
    collector = _workflow(COLLECTOR_WORKFLOW)
    verifier = _workflow(VERIFIER_WORKFLOW)

    assert {row["cron"] for row in collector["on"]["schedule"]} == {
        "0 16 * * *",
        "0 22 * * *",
        "0 5 * * *",
    }
    assert {row["cron"] for row in verifier["on"]["schedule"]} == {
        "0 13 * * *",
        "0 19 * * *",
    }
    assert "workflow_dispatch" in collector["on"]
    assert "workflow_dispatch" in verifier["on"]


def test_workflows_use_python_311_and_non_persistent_checkout_credentials():
    for path in (COLLECTOR_WORKFLOW, VERIFIER_WORKFLOW):
        workflow = _workflow(path)
        assert workflow["permissions"] == {"contents": "read"}
        for job in workflow["jobs"].values():
            setup = _step(job, "Setup Python")
            checkout = _step(job, "Checkout code")
            assert setup["with"]["python-version"] == "3.11"
            assert checkout["with"]["persist-credentials"] == "false"


def test_every_action_is_pinned_to_an_approved_full_commit():
    expected = {
        "actions/checkout": (
            "11d5960a326750d5838078e36cf38b85af677262",
            "v4",
            4,
        ),
        "actions/setup-python": (
            "a26af69be951a213d495a4c3e4e4022e16d87065",
            "v5",
            4,
        ),
    }
    observed = {name: 0 for name in expected}
    action_lines = []
    for path in (COLLECTOR_WORKFLOW, VERIFIER_WORKFLOW):
        action_lines.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("uses:")
        )

    assert len(action_lines) == 8
    for line in action_lines:
        match = re.fullmatch(
            r"uses:\s*([^@\s]+)@([0-9a-f]{40})\s+#\s*(v\d+)", line
        )
        assert match is not None, f"action must use a full lowercase SHA: {line}"
        action, sha, version = match.groups()
        assert action in expected
        expected_sha, expected_version, _ = expected[action]
        assert (sha, version) == (expected_sha, expected_version)
        observed[action] += 1

    assert observed == {
        action: expected_count
        for action, (_, _, expected_count) in expected.items()
    }

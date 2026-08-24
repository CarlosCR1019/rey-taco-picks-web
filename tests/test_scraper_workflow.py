from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_WORKFLOW = ROOT / ".github" / "workflows" / "collector.yml"
VERIFIER_WORKFLOW = ROOT / ".github" / "workflows" / "scraper.yml"
MIGRATION_WORKFLOW = ROOT / ".github" / "workflows" / "database-migrations.yml"
DELIVERY_RECOVERY_WORKFLOW = (
    ROOT / ".github" / "workflows" / "delivery-recovery.yml"
)
SERVICE_ROLE_EXPRESSION = "${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
RUN_KEY_EXPRESSION = "residential:${{ github.run_id }}"
RESIDENTIAL_RUNNER = ["self-hosted", "Windows", "X64", "playdoit-residential"]
RECOVERY_LABEL_EXPRESSION = "${{ needs.collect_primary.outputs.recovery_label }}"


def _workflow(path: Path) -> dict:
    parsed = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return parsed


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def test_database_migrations_are_manual_dry_run_first_and_least_privilege():
    workflow = _workflow(MIGRATION_WORKFLOW)
    triggers = workflow["on"]

    assert set(triggers) == {"workflow_dispatch"}
    dispatch = triggers["workflow_dispatch"]
    assert dispatch["inputs"]["apply"] == {
        "description": "Apply pending migrations after the mandatory dry-run",
        "required": "true",
        "default": "false",
        "type": "boolean",
    }
    assert dispatch["inputs"]["synchronize_password"] == {
        "description": "Reset the database password to the configured GitHub secret",
        "required": "true",
        "default": "false",
        "type": "boolean",
    }
    assert dispatch["inputs"]["reconcile_existing_history"] == {
        "description": "Record the verified pre-existing baseline in migration history",
        "required": "true",
        "default": "false",
        "type": "boolean",
    }
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["migrate"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == "10"
    assert set(job["env"]) == {
        "SUPABASE_ACCESS_TOKEN",
        "SUPABASE_DB_PASSWORD",
        "SUPABASE_PROJECT_REF",
    }

    steps = {step["name"]: step for step in job["steps"]}
    password_sync = steps["Synchronize database password"]
    assert password_sync["if"] == "${{ inputs.synchronize_password == true }}"
    assert (
        "api.supabase.com/v1/projects/$SUPABASE_PROJECT_REF/database/password"
        in password_sync["run"]
    )
    assert "--request PATCH" in password_sync["run"]
    assert "--dry-run" in steps["Preview pending migrations"]["run"]
    pooler = steps["Resolve exact Supabase session pooler"]["run"]
    assert (
        "api.supabase.com/v1/projects/$SUPABASE_PROJECT_REF/config/database/pooler"
        in pooler
    )
    assert "/config/database/pgbouncer" not in pooler
    assert 'map(select(.database_type == "PRIMARY"))' in pooler
    assert ".pooler.supabase.com" in pooler
    assert 'echo "::add-mask::$encoded_password"' in pooler
    assert 'echo "::add-mask::$db_url"' in pooler
    assert "SUPABASE_DB_HOST=" in pooler
    assert "SUPABASE_DB_USER=" in pooler
    native_probe = steps["Verify native PostgreSQL connection"]
    assert 'PGPASSWORD="$SUPABASE_DB_PASSWORD" psql' in native_probe["run"]
    assert '--host="$SUPABASE_DB_HOST"' in native_probe["run"]
    assert '--username="$SUPABASE_DB_USER"' in native_probe["run"]
    assert "select 'database_connection=ok'" in native_probe["run"]
    marker_probe = steps["Inspect remote migration markers"]["run"]
    for version in (
        "20260820210000",
        "20260820220000",
        "20260820233000",
        "20260820234500",
        "20260821010000",
        "20260821020000",
        "20260822010000",
        "20260823090000",
        "20260823100000",
        "20260823110000",
        "20260823120000",
        "20260823130000",
        "20260824100000",
    ):
        assert version in marker_probe
    assert "to_regprocedure" in marker_probe
    assert "supabase_migrations.schema_migrations" in marker_probe
    baseline_validation = steps["Validate pre-existing baseline"]
    assert baseline_validation["if"] == (
        "${{ inputs.reconcile_existing_history == true }}"
    )
    assert "preexisting_baseline=verified" in baseline_validation["run"]
    baseline_repair = steps["Reconcile pre-existing migration history"]
    assert baseline_repair["if"] == (
        "${{ inputs.reconcile_existing_history == true }}"
    )
    assert "migration repair" in baseline_repair["run"]
    assert "--status applied" in baseline_repair["run"]
    for version in (
        "20260820210000",
        "20260820220000",
        "20260820233000",
        "20260820234500",
        "20260821010000",
        "20260821020000",
        "20260822010000",
    ):
        assert version in baseline_repair["run"]
    assert "SUPABASE_DB_URL" in steps["Preview pending migrations"]["run"]
    assert steps["Apply pending migrations"]["if"] == (
        "${{ inputs.apply == true }}"
    )
    assert 'SUPABASE_DB_URL' in (
        steps["Verify remote migration history"]["run"]
    )
    assert "--dry-run" in steps["Verify remote migration history"]["run"]
    text = MIGRATION_WORKFLOW.read_text(encoding="utf-8")
    assert "--include-all" not in text
    assert "service_role" not in text.casefold()


def test_collector_jobs_use_only_residential_windows_runners():
    workflow = _workflow(COLLECTOR_WORKFLOW)
    jobs = workflow["jobs"]

    assert jobs["collect_primary"]["runs-on"] == RESIDENTIAL_RUNNER
    assert jobs["collect_recovery"]["runs-on"] == [
        *RESIDENTIAL_RUNNER,
        RECOVERY_LABEL_EXPRESSION,
    ]
    assert jobs["deliver_cloud"]["runs-on"] == "ubuntu-latest"


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
    assert RECOVERY_LABEL_EXPRESSION in recovery["runs-on"]


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
    assert delivery["if"] == (
        "always() && !cancelled() && ((github.event_name == 'schedule' && "
        "github.event.schedule == '0 16 * * *') || (needs.collect_primary.result == "
        "'success' && needs.collect_primary.outputs.collection_eligible == "
        "'true' && needs.collect_primary.outputs.release_eligible == 'true') || "
        "(needs.collect_primary.result == 'failure' && "
        "needs.collect_recovery.result == 'success' && "
        "needs.collect_recovery.outputs.collection_eligible == 'true' && "
        "needs.collect_recovery.outputs.release_eligible == 'true'))"
    )
    assert delivery["env"]["SCRAPER_RUN_KEY"] == RUN_KEY_EXPRESSION
    assert "--deliver-only" in _step(delivery, "Deliver exact persisted batch")["run"]
    assert "backend.social_poster" in _step(delivery, "Publish exact social batch")["run"]
    assert workflow["jobs"]["collect_primary"]["if"] == (
        "github.event_name != 'schedule' || github.event.schedule != '0 16 * * *'"
    )


def test_delivery_recovery_is_manual_validated_and_idempotent():
    workflow = _workflow(DELIVERY_RECOVERY_WORKFLOW)

    assert set(workflow["on"]) == {"workflow_dispatch"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"source_run_id", "portfolio_date"}
    assert all(value["required"] == "true" for value in inputs.values())
    assert workflow["permissions"] == {"contents": "read"}

    job = workflow["jobs"]["recover_delivery"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["env"]["SCRAPER_RUN_KEY"] == (
        "residential:${{ inputs.source_run_id }}"
    )
    validation = _step(job, "Validate exact recovery target")["run"]
    assert "^[1-9][0-9]{0,19}$" in validation
    assert "^[0-9]{4}-[0-9]{2}-[0-9]{2}$" in validation
    assert "date --date" in validation
    assert '"$GITHUB_REF" == "refs/heads/master"' in validation
    checkout = _step(job, "Checkout trusted master")
    assert checkout["with"]["ref"] == "master"
    assert checkout["with"]["persist-credentials"] == "false"
    preflight = _step(job, "Preflight exact recovery state")
    assert preflight["id"] == "recovery_plan"
    assert "backend.delivery_recovery" in preflight["run"]
    assert "backend/scraper.py --deliver-only" in _step(
        job, "Resume exact persisted delivery"
    )["run"]
    assert "backend.social_poster" in _step(
        job, "Resume exact social delivery"
    )["run"]
    telegram = _step(job, "Resume exact persisted delivery")
    social = _step(job, "Resume exact social delivery")
    assert telegram["continue-on-error"] == "true"
    assert social["continue-on-error"] == "true"
    assert "steps.recovery_plan.outputs.telegram_recovery == 'eligible'" in (
        telegram["if"]
    )
    assert social["if"] == (
        "always() && steps.recovery_plan.conclusion == 'success' && "
        "steps.recovery_plan.outputs.social_recovery == 'eligible'"
    )
    aggregate = _step(job, "Verify independent recovery outcomes")
    assert aggregate["if"] == "always()"
    assert "ambiguous" in aggregate["run"]
    assert "TELEGRAM_OUTCOME" in aggregate["run"]
    assert "SOCIAL_OUTCOME" in aggregate["run"]

    text = DELIVERY_RECOVERY_WORKFLOW.read_text(encoding="utf-8")
    assert "self-hosted" not in text
    assert "pull_request" not in text


def test_no_pull_request_event_can_reach_personal_computers():
    workflow = _workflow(COLLECTOR_WORKFLOW)
    assert workflow["jobs"]["collect_primary"]["outputs"][
        "collection_eligible"
    ] == "${{ steps.collection_lease.outputs.acquired }}"
    assert workflow["jobs"]["collect_recovery"]["outputs"][
        "collection_eligible"
    ] == "${{ steps.collection_lease.outputs.acquired }}"
    assert workflow["jobs"]["collect_primary"]["outputs"][
        "release_eligible"
    ] == "${{ steps.collection_window.outputs.release_eligible }}"
    assert workflow["jobs"]["collect_recovery"]["outputs"][
        "release_eligible"
    ] == "${{ steps.collection_window.outputs.release_eligible }}"

    assert "pull_request" not in workflow["on"]
    assert workflow["permissions"] == {
        "actions": "read",
        "contents": "read",
    }
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
        assert job["env"]["DAILY_PORTFOLIO_ENABLED"] == "true"
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


def test_result_verifier_receives_detailed_stats_key_only_as_a_secret():
    verifier = _workflow(VERIFIER_WORKFLOW)["jobs"]["verificar"]
    verify_step = _step(verifier, "Verify Results")

    assert verify_step["env"]["API_FOOTBALL_KEY"] == (
        "${{ secrets.API_FOOTBALL_KEY }}"
    )
    assert "API_FOOTBALL_KEY" not in verifier.get("env", {})
    assert "python backend/verificar_resultados.py" == verify_step["run"]


def test_result_verifier_can_apply_explicit_manual_score_evidence():
    workflow = _workflow(VERIFIER_WORKFLOW)
    dispatch = workflow["on"]["workflow_dispatch"]
    assert dispatch["inputs"]["manual_result_evidence_json"] == {
        "description": "Reviewed final-score evidence JSON; leave blank for automatic verification",
        "required": "false",
        "default": "",
        "type": "string",
    }

    verifier = workflow["jobs"]["verificar"]
    step = _step(verifier, "Apply reviewed result evidence")
    assert step["if"] == "${{ inputs.manual_result_evidence_json != '' }}"
    assert step["env"]["SUPABASE_URL"] == "${{ secrets.SUPABASE_URL }}"
    assert step["env"]["SUPABASE_SERVICE_ROLE_KEY"] == SERVICE_ROLE_EXPRESSION
    assert step["env"]["MANUAL_RESULT_EVIDENCE_JSON"] == (
        "${{ inputs.manual_result_evidence_json }}"
    )
    assert step["run"] == "python -m backend.manual_result_evidence"


def test_result_report_secrets_are_scoped_to_the_verifier_step():
    verifier = _workflow(VERIFIER_WORKFLOW)["jobs"]["verificar"]
    verify_step = _step(verifier, "Verify Results")
    expected = {
        "META_SYSTEM_USER_ACCESS_TOKEN": "${{ secrets.META_SYSTEM_USER_ACCESS_TOKEN }}",
        "FB_PAGE_ID": "${{ secrets.FB_PAGE_ID }}",
        "IG_USER_ID": "${{ secrets.IG_USER_ID }}",
        "SUPABASE_STORAGE_BUCKET": "${{ secrets.SUPABASE_STORAGE_BUCKET }}",
    }

    for key, value in expected.items():
        assert verify_step["env"][key] == value
        assert key not in verifier.get("env", {})
    assert "github.event.schedule == '0 1 * * *'" in verify_step["env"][
        "RESULT_REPORT_MODE"
    ]


def test_workflows_keep_collection_and_verification_schedules():
    collector = _workflow(COLLECTOR_WORKFLOW)
    verifier = _workflow(VERIFIER_WORKFLOW)

    assert {row["cron"] for row in collector["on"]["schedule"]} == {
        "7 * * * *",
        "37 * * * *",
        "0 16 * * *",
    }
    assert {row["cron"] for row in verifier["on"]["schedule"]} == {
        "0 13 * * *",
        "0 19 * * *",
        "0 1 * * *",
        "0 5 * * *",
    }
    assert "workflow_dispatch" in collector["on"]
    assert "workflow_dispatch" in verifier["on"]


def test_workflows_use_python_311_and_non_persistent_checkout_credentials():
    for path in (COLLECTOR_WORKFLOW, VERIFIER_WORKFLOW):
        workflow = _workflow(path)
        expected_permissions = {"contents": "read"}
        if path == COLLECTOR_WORKFLOW:
            expected_permissions["actions"] = "read"
        assert workflow["permissions"] == expected_permissions
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


def test_stale_scheduled_collections_fail_closed_before_dependencies_or_scrape():
    workflow = _workflow(COLLECTOR_WORKFLOW)

    for job_name in ("collect_primary", "collect_recovery"):
        job = workflow["jobs"][job_name]
        gate = _step(job, "Check collection window")
        adaptive = _step(job, "Check adaptive work")
        install = _step(job, "Install dependencies")
        lease = _step(job, "Claim collection lease")
        collect = _step(job, "Collect and persist only")

        assert gate["id"] == "collection_window"
        assert gate["env"]["GH_TOKEN"] == "${{ github.token }}"
        assert "actions/runs/$env:GITHUB_RUN_ID" in gate["run"]
        assert 'Authorization = "Bearer $env:GH_TOKEN"' in gate["run"]
        assert "backend.adaptive_schedule" in gate["run"]
        assert '"--plan"' in gate["run"]
        assert '"--schedule", $env:GITHUB_EVENT_SCHEDULE' in gate["run"]
        assert "backend.daily_portfolio --created-at" in gate["run"]
        assert "$env:GITHUB_EVENT_NAME" in gate["run"]
        assert '"eligible=false" >> $env:GITHUB_OUTPUT' in gate["run"]
        assert '"eligible=true" >> $env:GITHUB_OUTPUT' in gate["run"]
        assert '"release_eligible=false" >> $env:GITHUB_OUTPUT' in gate["run"]
        assert "$releaseLines[0] >> $env:GITHUB_OUTPUT" in gate["run"]
        assert '"scan_mode=idle" >> $env:GITHUB_OUTPUT' in gate["run"]
        assert '"portfolio_date=invalid" >> $env:GITHUB_OUTPUT' in gate["run"]
        assert '"window_key=invalid" >> $env:GITHUB_OUTPUT' in gate["run"]
        assert "|schedule|$env:GITHUB_EVENT_SCHEDULE" in gate["run"]
        assert "|manual|$env:GITHUB_RUN_ID" in gate["run"]
        assert job["outputs"]["portfolio_date"] == (
            "${{ steps.collection_window.outputs.portfolio_date }}"
        )
        assert collect["env"]["DAILY_PORTFOLIO_DATE"] == (
            "${{ steps.collection_window.outputs.portfolio_date }}"
        )
        assert adaptive["id"] == "adaptive_work"
        assert adaptive["if"] == "steps.collection_window.outputs.eligible == 'true'"
        assert adaptive["env"]["SCAN_MODE"] == (
            "${{ steps.collection_window.outputs.scan_mode }}"
        )
        assert adaptive["env"]["PORTFOLIO_DATE"] == (
            "${{ steps.collection_window.outputs.portfolio_date }}"
        )
        assert "backend.adaptive_work" in adaptive["run"]
        assert '"needed=true" >> $env:GITHUB_OUTPUT' in adaptive["run"]
        assert '"needed=false" >> $env:GITHUB_OUTPUT' in adaptive["run"]
        active_condition = (
            "steps.collection_window.outputs.eligible == 'true' && "
            "steps.adaptive_work.outputs.needed == 'true'"
        )
        assert install["if"] == active_condition
        assert lease["id"] == "collection_lease"
        assert lease["if"] == active_condition
        assert lease["env"]["COLLECTION_WINDOW_KEY"] == (
            "${{ steps.collection_window.outputs.window_key }}"
        )
        assert "backend.collection_lease --window-key" in lease["run"]
        assert "[guid]::NewGuid()" in lease["run"]
        assert "$env:GITHUB_RUN_ATTEMPT" in lease["run"]
        assert "$env:GITHUB_JOB" in lease["run"]
        assert "$env:RUNNER_NAME" in lease["run"]
        assert '"COLLECTION_LEASE_OWNER_KEY=$ownerKey" >> $env:GITHUB_ENV' in lease["run"]
        assert '"COLLECTION_WINDOW_KEY=$env:COLLECTION_WINDOW_KEY" >> $env:GITHUB_ENV' in lease["run"]
        assert '"acquired=true" >> $env:GITHUB_OUTPUT' in lease["run"]
        assert '"acquired=false" >> $env:GITHUB_OUTPUT' in lease["run"]
        assert collect["if"] == (
            "steps.collection_window.outputs.eligible == 'true' && "
            "steps.adaptive_work.outputs.needed == 'true' && "
            "steps.collection_lease.outputs.acquired == 'true'"
        )
        assert "backend.collection_lease --window-key" in collect["run"]
        assert "--release" in collect["run"]
        assert collect["run"].index("backend/scraper.py --collect-only") < (
            collect["run"].index("--release")
        )
        step_names = [step["name"] for step in job["steps"]]
        assert step_names.index("Check adaptive work") < step_names.index(
            "Install dependencies"
        ) < step_names.index(
            "Claim collection lease"
        ) < step_names.index("Collect and persist only")


def test_daily_release_is_bounded_to_three_windows_or_manual_dispatch():
    workflow = _workflow(COLLECTOR_WORKFLOW)

    for job_name in ("collect_primary", "collect_recovery"):
        gate = _step(workflow["jobs"][job_name], "Check collection window")["run"]
        assert "backend.adaptive_schedule" in gate
        assert '"--plan"' in gate
        assert '"--schedule", $env:GITHUB_EVENT_SCHEDULE' in gate
        assert "$releaseSchedules" not in gate
        assert "^release_eligible=(true|false)$" in gate
        assert "$releaseLines[0] >> $env:GITHUB_OUTPUT" in gate

    assert "github.event.schedule == '0 16 * * *'" in workflow["jobs"][
        "deliver_cloud"
    ]["if"]
    assert workflow["jobs"]["deliver_cloud"]["env"][
        "DAILY_PORTFOLIO_ENABLED"
    ] == "true"


def test_cloud_only_ten_oclock_release_reuses_stale_gate_before_delivery():
    workflow = _workflow(COLLECTOR_WORKFLOW)
    delivery = workflow["jobs"]["deliver_cloud"]
    gate = _step(delivery, "Check cloud release window")
    install = _step(delivery, "Install dependencies")
    publish = _step(delivery, "Deliver exact persisted batch")
    social = _step(delivery, "Publish exact social batch")

    assert gate["id"] == "cloud_window"
    assert gate["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert gate["env"]["GITHUB_EVENT_NAME"] == "${{ github.event_name }}"
    assert gate["env"]["COLLECTED_PORTFOLIO_DATE"] == (
        "${{ needs.collect_primary.outputs.portfolio_date || "
        "needs.collect_recovery.outputs.portfolio_date }}"
    )
    manual_branch = gate["run"].index(
        '$env:GITHUB_EVENT_NAME -eq "workflow_dispatch"'
    )
    remote_lookup = gate["run"].index(
        "actions/runs/$env:GITHUB_RUN_ID"
    )
    assert manual_branch < remote_lookup
    assert (
        '"portfolio_date=$env:COLLECTED_PORTFOLIO_DATE" '
        '>> $env:GITHUB_OUTPUT'
    ) in gate["run"]
    assert '"eligible=true" >> $env:GITHUB_OUTPUT' in gate["run"]
    assert "actions/runs/$env:GITHUB_RUN_ID" in gate["run"]
    assert "backend.adaptive_schedule" in gate["run"]
    assert "backend.daily_portfolio --created-at" in gate["run"]
    assert '"eligible=false" >> $env:GITHUB_OUTPUT' in gate["run"]
    assert '"portfolio_date=invalid" >> $env:GITHUB_OUTPUT' in gate["run"]
    assert install["if"] == "steps.cloud_window.outputs.eligible == 'true'"
    assert publish["if"] == "steps.cloud_window.outputs.eligible == 'true'"
    assert social["if"] == (
        "success() && steps.cloud_window.outputs.eligible == 'true'"
    )
    assert publish["env"]["DAILY_PORTFOLIO_DATE"] == (
        "${{ steps.cloud_window.outputs.portfolio_date }}"
    )
    assert social["env"]["DAILY_PORTFOLIO_DATE"] == (
        "${{ steps.cloud_window.outputs.portfolio_date }}"
    )


def test_stale_gate_never_changes_power_state_or_logs_the_github_token():
    text = COLLECTOR_WORKFLOW.read_text(encoding="utf-8")
    lowered = text.lower()

    for forbidden in (
        "shutdown",
        "set-sleep",
        "powercfg",
        "rundll32.exe powrprof",
        "write-output $env:gh_token",
        "write-host $env:gh_token",
    ):
        assert forbidden not in lowered

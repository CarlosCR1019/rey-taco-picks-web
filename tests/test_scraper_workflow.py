from pathlib import Path

import yaml


WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "scraper.yml"
SERVICE_ROLE_EXPRESSION = "${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"


def _workflow() -> dict:
    # BaseLoader keeps GitHub Actions keys such as ``on`` and scalar values such
    # as ``false`` intact instead of applying YAML 1.1 boolean coercion.
    parsed = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return parsed


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


def test_workflow_uses_service_role_and_prevents_overlap():
    workflow = _workflow()
    assert workflow["concurrency"] == {
        "group": "rey-taco-scraper",
        "cancel-in-progress": "false",
    }

    jobs = workflow["jobs"]
    verifier = _step(jobs["verificar"], "Verify Results")
    scraper = _step(jobs["scraper"], "Run Scraper (Multi-Sport & KBO)")
    assert verifier["env"]["SUPABASE_SERVICE_ROLE_KEY"] == SERVICE_ROLE_EXPRESSION
    assert scraper["env"]["SUPABASE_SERVICE_ROLE_KEY"] == SERVICE_ROLE_EXPRESSION

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "SUPABASE_KEY" not in text


def test_scraper_waits_for_verification_and_social_requires_success():
    workflow = _workflow()
    jobs = workflow["jobs"]
    verifier = jobs["verificar"]
    scraper = jobs["scraper"]

    assert verifier["if"] == (
        "github.event.schedule == '0 5 * * *' || "
        "github.event_name == 'workflow_dispatch'"
    )
    assert scraper["needs"] == "verificar"
    condition = " ".join(scraper["if"].split())
    assert condition == (
        "always() && "
        "(needs.verificar.result == 'success' || "
        "needs.verificar.result == 'skipped')"
    )

    social = _step(scraper, "Auto-Post Social Media Banner (Facebook & Instagram)")
    assert social["if"] == "success()"


def test_workflow_keeps_all_schedules_and_python_311():
    workflow = _workflow()
    schedules = {entry["cron"] for entry in workflow["on"]["schedule"]}
    assert schedules == {"0 16 * * *", "0 22 * * *", "0 5 * * *"}
    assert "workflow_dispatch" in workflow["on"]

    for job_name in ("verificar", "scraper"):
        setup_python = _step(workflow["jobs"][job_name], "Setup Python")
        assert setup_python["with"]["python-version"] == "3.11"

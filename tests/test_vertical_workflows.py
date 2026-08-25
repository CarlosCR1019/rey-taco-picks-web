from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_WORKFLOW = ROOT / ".github" / "workflows" / "collector.yml"
RESULTS_WORKFLOW = ROOT / ".github" / "workflows" / "scraper.yml"
RECOVERY_WORKFLOW = ROOT / ".github" / "workflows" / "delivery-recovery.yml"


def _workflow() -> dict:
    parsed = yaml.load(
        COLLECTOR_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    assert isinstance(parsed, dict)
    return parsed


def _load_workflow(path: Path) -> dict:
    parsed = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    return parsed


def test_pre_event_story_step_follows_exact_feed_publish() -> None:
    job = _workflow()["jobs"]["deliver_cloud"]
    names = [step["name"] for step in job["steps"]]

    assert names.index("Publish exact pre-event stories") == (
        names.index("Publish exact social batch") + 1
    )
    story = next(
        step for step in job["steps"]
        if step["name"] == "Publish exact pre-event stories"
    )
    assert story["if"] == (
        "success() && steps.cloud_window.outputs.eligible == 'true'"
    )
    assert story["run"] == "python -m backend.vertical_publisher --mode pre-event"


def test_pre_event_story_step_has_only_approved_scoped_configuration() -> None:
    job = _workflow()["jobs"]["deliver_cloud"]
    story = next(
        step for step in job["steps"]
        if step["name"] == "Publish exact pre-event stories"
    )

    assert story["env"] == {
        "DAILY_PORTFOLIO_DATE": "${{ steps.cloud_window.outputs.portfolio_date }}",
        "SUPABASE_URL": "${{ secrets.SUPABASE_URL }}",
        "SUPABASE_SERVICE_ROLE_KEY": "${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}",
        "META_SYSTEM_USER_ACCESS_TOKEN": (
            "${{ secrets.META_SYSTEM_USER_ACCESS_TOKEN }}"
        ),
        "IG_USER_ID": "${{ secrets.IG_USER_ID }}",
        "META_GRAPH_VERSION": "v26.0",
        "TELEGRAM_BOT_TOKEN": "${{ secrets.TELEGRAM_BOT_TOKEN }}",
        "TELEGRAM_CHAT_ID": "${{ secrets.TELEGRAM_CHAT_ID }}",
    }
    assert "FB_PAGE_ID" not in story["env"]
    assert "GROQ_API_KEY" not in story["env"]
    assert "CLOUDFLARE_AI_API_TOKEN" not in story["env"]


def test_pre_event_story_step_is_headless_and_non_interactive() -> None:
    job = _workflow()["jobs"]["deliver_cloud"]
    story = next(
        step for step in job["steps"]
        if step["name"] == "Publish exact pre-event stories"
    )
    text = str(story).casefold()

    for forbidden in ("chrome", "playwright", "selenium", "start-process"):
        assert forbidden not in text


def test_result_workflow_installs_local_media_tools_before_dependencies() -> None:
    job = _load_workflow(RESULTS_WORKFLOW)["jobs"]["verificar"]
    names = [step["name"] for step in job["steps"]]

    assert names.index("Install local result media tools") < names.index(
        "Install dependencies"
    )
    media = next(
        step
        for step in job["steps"]
        if step["name"] == "Install local result media tools"
    )
    assert media["run"] == (
        "sudo apt-get update && sudo apt-get install -y "
        "ffmpeg tesseract-ocr tesseract-ocr-spa"
    )


def test_result_workflow_runs_idempotent_final_vertical_after_verifier() -> None:
    job = _load_workflow(RESULTS_WORKFLOW)["jobs"]["verificar"]
    names = [step["name"] for step in job["steps"]]
    assert names.index("Publish final vertical media") == names.index(
        "Verify Results"
    ) + 1
    step = next(
        item for item in job["steps"] if item["name"] == "Publish final vertical media"
    )
    assert step["run"] == "python -m backend.vertical_publisher --mode final"
    assert step["env"] == {
        "SUPABASE_URL": "${{ secrets.SUPABASE_URL }}",
        "SUPABASE_SERVICE_ROLE_KEY": "${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}",
        "META_SYSTEM_USER_ACCESS_TOKEN": (
            "${{ secrets.META_SYSTEM_USER_ACCESS_TOKEN }}"
        ),
        "FB_PAGE_ID": "${{ secrets.FB_PAGE_ID }}",
        "IG_USER_ID": "${{ secrets.IG_USER_ID }}",
        "META_GRAPH_VERSION": "v26.0",
        "TELEGRAM_BOT_TOKEN": "${{ secrets.TELEGRAM_BOT_TOKEN }}",
        "TELEGRAM_ADMIN_ID": "${{ secrets.TELEGRAM_CHAT_ID }}",
    }


def test_recovery_workflow_has_media_tools_and_ledger_only_vertical_recovery() -> None:
    job = _load_workflow(RECOVERY_WORKFLOW)["jobs"]["recover_delivery"]
    names = [step["name"] for step in job["steps"]]
    assert names.index("Install local result media tools") < names.index(
        "Install dependencies"
    )
    step = next(
        item
        for item in job["steps"]
        if item["name"] == "Recover final vertical media"
    )
    assert step["run"] == "python -m backend.vertical_publisher --mode recover"
    assert "scraper" not in str(step).casefold()
    assert step["env"]["SUPABASE_URL"] == "${{ secrets.SUPABASE_URL }}"
    assert step["env"]["FB_PAGE_ID"] == "${{ secrets.FB_PAGE_ID }}"
    assert step["env"]["IG_USER_ID"] == "${{ secrets.IG_USER_ID }}"

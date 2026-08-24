from types import MappingProxyType

import pytest

from backend.delivery_recovery import build_recovery_plan, run_main


def release(*, portfolio_date="2026-08-24", ledger=None):
    return {
        "portfolio_date": portfolio_date,
        "delivery_status": MappingProxyType(ledger or {}),
    }


def test_recovery_requires_an_existing_exact_portfolio_release():
    with pytest.raises(RuntimeError, match="does not exist"):
        build_recovery_plan(
            None,
            portfolio_date="2026-08-24",
            telegram_destinations=("admin",),
            meta_destinations=("facebook",),
        )

    with pytest.raises(RuntimeError, match="date mismatch"):
        build_recovery_plan(
            release(portfolio_date="2026-08-23"),
            portfolio_date="2026-08-24",
            telegram_destinations=("admin",),
            meta_destinations=("facebook",),
        )


def test_recovery_marks_all_recorded_successes_complete():
    plan = build_recovery_plan(
        release(
            ledger={
                "admin": {"success": True},
                "vip": {"success": True},
                "facebook": {"state": "success", "success": True},
                "instagram": {"state": "success", "success": True},
            }
        ),
        portfolio_date="2026-08-24",
        telegram_destinations=("admin", "vip"),
        meta_destinations=("facebook", "instagram"),
    )

    assert plan.telegram == "complete"
    assert plan.social == "complete"


def test_missing_telegram_is_ambiguous_but_unclaimed_meta_is_safe():
    plan = build_recovery_plan(
        release(),
        portfolio_date="2026-08-24",
        telegram_destinations=("admin",),
        meta_destinations=("facebook", "instagram"),
    )

    assert plan.telegram == "ambiguous"
    assert plan.social == "eligible"


def test_terminal_failures_are_eligible_and_active_meta_claim_is_ambiguous():
    plan = build_recovery_plan(
        release(
            ledger={
                "admin": {"success": False, "error": "http_500"},
                "facebook": {
                    "state": "in_progress",
                    "success": False,
                    "error": "",
                },
            }
        ),
        portfolio_date="2026-08-24",
        telegram_destinations=("admin",),
        meta_destinations=("facebook",),
    )

    assert plan.telegram == "eligible"
    assert plan.social == "ambiguous"


def test_unconfigured_destination_groups_are_not_scheduled():
    plan = build_recovery_plan(
        release(),
        portfolio_date="2026-08-24",
        telegram_destinations=(),
        meta_destinations=(),
    )

    assert plan.telegram == "not_configured"
    assert plan.social == "not_configured"


class FakeRepository:
    def __init__(self, result):
        self.result = result
        self.run_keys = []

    def resume_daily(self, run_key):
        self.run_keys.append(run_key)
        return self.result


def runtime_values():
    return {
        "SCRAPER_RUN_KEY": "residential:32704791042",
        "DAILY_PORTFOLIO_ENABLED": "true",
        "DAILY_PORTFOLIO_DATE": "2026-08-24",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role",
        "TELEGRAM_BOT_TOKEN": "telegram-token",
        "TELEGRAM_CHAT_ID": "admin-id",
        "META_SYSTEM_USER_ACCESS_TOKEN": "meta-token",
        "FB_PAGE_ID": "123456789",
    }


def test_command_outputs_only_safe_exact_plan(capsys):
    repository = FakeRepository(
        release(
            ledger={
                "admin": {"success": True},
                "facebook": {
                    "state": "failed",
                    "success": False,
                    "error": "delivery_failed",
                },
            }
        )
    )

    assert run_main(values=runtime_values(), repository=repository) == 0
    assert repository.run_keys == ["residential:32704791042"]
    assert capsys.readouterr().out.splitlines() == [
        "recovery_target=valid",
        "telegram_recovery=complete",
        "social_recovery=eligible",
    ]


def test_command_fails_for_a_missing_target(capsys):
    repository = FakeRepository(None)

    assert run_main(values=runtime_values(), repository=repository) == 2
    assert capsys.readouterr().out == "recovery_target=invalid\n"

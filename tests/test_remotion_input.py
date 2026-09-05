from datetime import date

import pytest

from backend.remotion_input import ReelInput, build_reel_input


def test_reel_input_contains_only_persisted_public_data():
    value = build_reel_input(
        batch_id="11111111-1111-1111-1111-111111111111",
        portfolio_date=date(2026, 9, 5),
        picks=[{"partido": "A vs B", "pick": "A", "cuota": "1.80"}],
        template_digest="e" * 64,
    )
    assert isinstance(value, ReelInput)
    assert value.picks[0]["pick"] == "A"
    assert "token" not in value.to_json().lower()


def test_reel_input_rejects_private_or_unbounded_fields():
    with pytest.raises(ValueError, match="reel input contains forbidden field"):
        build_reel_input(
            batch_id="11111111-1111-1111-1111-111111111111",
            portfolio_date=date(2026, 9, 5),
            picks=[{"partido": "A", "pick": "A", "cuota": "1.80", "telegram_id": "1"}],
            template_digest="e" * 64,
        )


def test_reel_input_rejects_empty_or_unbounded_pick_lists():
    with pytest.raises(ValueError, match="reel input requires one to six picks"):
        build_reel_input(
            batch_id="11111111-1111-1111-1111-111111111111",
            portfolio_date="2026-09-05",
            picks=[],
            template_digest="e" * 64,
        )
    with pytest.raises(ValueError, match="reel input requires one to six picks"):
        build_reel_input(
            batch_id="11111111-1111-1111-1111-111111111111",
            portfolio_date="2026-09-05",
            picks=[{"partido": "A", "pick": "A", "cuota": "1.80"}] * 7,
            template_digest="e" * 64,
        )

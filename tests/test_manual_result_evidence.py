import pytest

from backend.manual_result_evidence import build_manual_result_updates


def pending_pick(**overrides):
    row = {
        "id": 42,
        "partido": "Kairat  (F) vs FC Atyrau Women",
        "pick": "Kairat  (F)",
        "cuota": "1.4445",
        "mercado": "Ganador del partido",
        "source_market_key": "h2h",
        "fecha_evento": "2026-08-24",
        "estado": "pendiente",
        "active": True,
    }
    row.update(overrides)
    return row


def final_evidence(**overrides):
    row = {
        "partido": "Kairat  (F) vs FC Atyrau Women",
        "pick": "Kairat  (F)",
        "source": "camel1",
        "source_id": (
            "https://www.camel1.tv/es/football/"
            "kairat-almaty-w-vs-fk-atyrau-w/l7oqdehgvjopr51"
        ),
        "event_date": "2026-08-24",
        "home_team": "Kairat (F)",
        "away_team": "FC Atyrau Women",
        "home_score": 3,
        "away_score": 0,
        "completed": True,
    }
    row.update(overrides)
    return row


def test_manual_evidence_builds_one_audited_winning_update():
    updates = build_manual_result_updates([pending_pick()], [final_evidence()])

    assert len(updates) == 1
    pick_id, decision = updates[0]
    assert pick_id == 42
    assert decision["estado"] == "ganado"
    assert decision["resultado_fuente"] == "camel1"
    assert decision["resultado_evento_id"] == (
        "https://www.camel1.tv/es/football/"
        "kairat-almaty-w-vs-fk-atyrau-w/l7oqdehgvjopr51"
    )
    assert decision["resultado_marcador"] == "3-0"
    assert decision["resultado_verificado_at"]


@pytest.mark.parametrize(
    "override",
    [
        {"completed": False},
        {"source_id": "http://example.com/result"},
        {"event_date": "2026-08-23"},
    ],
)
def test_manual_evidence_rejects_unverifiable_rows(override):
    with pytest.raises(ValueError):
        build_manual_result_updates(
            [pending_pick()],
            [final_evidence(**override)],
        )


def test_manual_evidence_requires_exactly_one_pending_pick():
    duplicate = pending_pick(id=43)

    with pytest.raises(ValueError, match="exactly one pending pick"):
        build_manual_result_updates(
            [pending_pick(), duplicate],
            [final_evidence()],
        )


def test_manual_evidence_requires_the_expected_selection():
    with pytest.raises(ValueError, match="selection does not match"):
        build_manual_result_updates(
            [pending_pick()],
            [final_evidence(pick="FC Atyrau Women")],
        )

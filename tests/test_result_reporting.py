from __future__ import annotations

from datetime import date

import pytest

from backend.result_reporting import build_result_report


BATCH_ID = "12345678-1234-4234-8234-123456789abc"


def rows_with_states(*states: str) -> list[dict[str, object]]:
    assert len(states) == 6
    rows: list[dict[str, object]] = []
    for index, state in enumerate(states, start=1):
        verified = state != "pendiente"
        rows.append(
            {
                "id": index,
                "batch_id": BATCH_ID,
                "portfolio_date": date(2026, 8, 24).isoformat(),
                "partido": f"Equipo {index}A vs Equipo {index}B",
                "pick": f"Selección {index}",
                "cuota": f"{1.50 + index / 100:.2f}",
                "estado": state,
                "resultado_fuente": "api_football" if verified else None,
                "resultado_evento_id": f"event-{index}" if verified else None,
                "resultado_marcador": "2-1" if verified else None,
                "resultado_verificado_at": (
                    f"2026-08-24T{12 + index:02d}:00:00+00:00"
                    if verified
                    else None
                ),
            }
        )
    return rows


def test_evening_report_counts_only_verified_rows():
    report = build_result_report(
        rows_with_states(
            "ganado",
            "ganado",
            "pendiente",
            "pendiente",
            "pendiente",
            "pendiente",
        ),
        kind="evening",
    )

    assert report.eligible is True
    assert report.terminal is False
    assert len(report.rows) == 2
    assert "2 verificados" in report.telegram
    assert "4 selecciones pendientes" in report.telegram
    assert "CIERRE VERIFICADO" not in report.telegram


def test_final_report_requires_all_six_settled_rows():
    with pytest.raises(ValueError, match="six settled"):
        build_result_report(
            rows_with_states(
                "ganado",
                "ganado",
                "pendiente",
                "pendiente",
                "pendiente",
                "pendiente",
            ),
            kind="final",
        )


def test_final_report_does_not_treat_review_as_a_settled_result():
    with pytest.raises(ValueError, match="six settled"):
        build_result_report(
            rows_with_states(
                "ganado",
                "ganado",
                "ganado",
                "ganado",
                "ganado",
                "revision_pendiente",
            ),
            kind="final",
        )


def test_six_wins_disclose_all_six_rows_after_settlement():
    report = build_result_report(
        rows_with_states(*(["ganado"] * 6)),
        kind="final",
    )

    assert report.record == "6-0"
    assert report.terminal is True
    assert report.telegram.count("✅") == 6
    assert all(str(row["pick"]) in report.telegram for row in report.rows)
    assert "garant" not in report.telegram.casefold()
    assert report.facebook.startswith("👑 REY TACO PICKS · CIERRE VERIFICADO")
    assert report.instagram.endswith(
        "#ReyTacoPicks #ResultadosVerificados #ApuestasResponsables"
    )


def test_losses_void_and_review_are_not_hidden_in_evening_report():
    report = build_result_report(
        rows_with_states(
            "ganado",
            "perdido",
            "void",
            "revision_pendiente",
            "ganado",
            "ganado",
        ),
        kind="evening",
    )

    assert "❌" in report.telegram
    assert "↩️" in report.telegram
    assert "🟡" in report.telegram
    assert "1 void" in report.telegram
    assert "1 en revisión" in report.telegram


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda rows: rows[:5], "six rows"),
        (lambda rows: [*rows[:5], {**rows[5], "id": 1}], "unique integer"),
        (lambda rows: [{**rows[0], "batch_id": "bad"}, *rows[1:]], "batch"),
        (lambda rows: [{**rows[0], "portfolio_date": "24/08/2026"}, *rows[1:]], "date"),
        (lambda rows: [{**rows[0], "estado": "oculto"}, *rows[1:]], "state"),
        (lambda rows: [{**rows[0], "cuota": "nan"}, *rows[1:]], "odds"),
        (
            lambda rows: [{**rows[0], "resultado_marcador": ""}, *rows[1:]],
            "resultado_marcador",
        ),
    ],
)
def test_result_report_rejects_malformed_or_unverified_rows(mutate, message):
    rows = rows_with_states(*(["ganado"] * 6))

    with pytest.raises(ValueError, match=message):
        build_result_report(mutate(rows), kind="evening")


def test_evening_requires_at_least_one_verified_row():
    with pytest.raises(ValueError, match="verified row"):
        build_result_report(
            rows_with_states(*(["pendiente"] * 6)),
            kind="evening",
        )


def test_digest_is_stable_for_the_same_verified_snapshot_and_changes_with_state():
    original = rows_with_states("ganado", "pendiente", "pendiente", "pendiente", "pendiente", "pendiente")
    same = [dict(row) for row in original]
    changed = [dict(row) for row in original]
    changed[0]["estado"] = "perdido"

    assert build_result_report(original, kind="evening").digest == build_result_report(
        same, kind="evening"
    ).digest
    assert build_result_report(original, kind="evening").digest != build_result_report(
        changed, kind="evening"
    ).digest

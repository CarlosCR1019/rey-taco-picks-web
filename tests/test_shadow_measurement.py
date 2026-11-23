"""
tests/test_shadow_measurement.py
================================
Verifica que el módulo de medición en modo sombra (shadow_measurement.py)
sea 100% de solo lectura respecto a producción (no altera verified_record.json)
y calcule correctamente las métricas por deporte, banda de cuota, drawdown y CLV.
"""

from backend.shadow_measurement import (
    PICK_TRACKING_PATH,
    REPO_ROOT,
    SHADOW_LATEST_PATH,
    run_shadow_measurement,
)


def test_shadow_measurement_never_touches_live_verified_record():
    live_prod = REPO_ROOT / "data" / "verified_record.json"
    live_frontend = REPO_ROOT / "frontend" / "public" / "verified_record.json"

    before_prod = live_prod.read_bytes() if live_prod.exists() else None
    before_frontend = live_frontend.read_bytes() if live_frontend.exists() else None

    report = run_shadow_measurement(persist=True)

    after_prod = live_prod.read_bytes() if live_prod.exists() else None
    after_frontend = live_frontend.read_bytes() if live_frontend.exists() else None

    assert before_prod == after_prod, "shadow_measurement no debe modificar data/verified_record.json"
    assert before_frontend == after_frontend, "shadow_measurement no debe modificar frontend/public/verified_record.json"
    assert report["mode"] == "SHADOW_MEASUREMENT_READONLY"
    assert report["affects_production"] is False
    assert SHADOW_LATEST_PATH.exists()
    assert "active_core_portfolio" in report["portfolio_measurement"]
    assert "linea_principal (1.70-1.99)" in report["odds_band_performance"]
    assert "max_drawdown_units" in report["equity_and_drawdown"]

    if PICK_TRACKING_PATH.exists():
        assert report["clv_telemetry"]["samples"] >= 140
        assert report["clv_telemetry"]["mean_clv_pct"] > 0
        assert report["paired_brier_and_logloss_calibration"]["all_tracked_sports"]["paired_settled_samples"] >= 110

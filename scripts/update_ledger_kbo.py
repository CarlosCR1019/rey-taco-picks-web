import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.audit_ledger import (
    record_pick_created,
    record_price_expired,
    verify_ledger_integrity,
    AUDIT_LEDGER_PATH
)

# 1. Registrar que el ticket previo de Filipinas expiró porque la línea subió a 3.5
record_price_expired(
    ticket_id="RT-20260917-FÚT-7CB2",
    stale_odds=1.50,
    current_live_odds=2.20,
    min_acceptable_odds=1.50,
    ledger_path=AUDIT_LEDGER_PATH
)

# 2. Registrar los nuevos picks de KBO y NPB
kbo_pick = {
    "home_team": "Doosan Bears",
    "away_team": "Kiwoom Heroes",
    "sport": "Béisbol",
    "league": "KBO Corea",
    "pick": "Más de 7.0 Carreras",
    "market": "Totales de Carreras (7.0)",
    "market_odds_decimal": 1.74,
    "minimum_odds_decimal": 1.70,
    "calibrated_probability": 0.6111,
    "market_probability": 0.5372,
    "model_edge_pp": 7.39,
    "ev_percent": 6.38,
    "stake_units": 1.60,
    "tactical_rationale": "Línea baja de 7.0 en KBO donde el promedio de liga es de 8.8 carreras. Doosan con ofensiva encendida frente a bullpen de Kiwoom."
}

npb_pick = {
    "home_team": "Chunichi Dragons",
    "away_team": "Yomiuri Giants",
    "sport": "Béisbol",
    "league": "NPB Japón",
    "pick": "Menos de 5.5 Carreras",
    "market": "Totales de Carreras (5.5)",
    "market_odds_decimal": 1.95,
    "minimum_odds_decimal": 1.85,
    "calibrated_probability": 0.5626,
    "market_probability": 0.4887,
    "model_edge_pp": 7.39,
    "ev_percent": 9.84,
    "stake_units": 1.92,
    "tactical_rationale": "Nagoya Dome es el parque más favorable a lanzadores de Japón. Duelo de abridores con ERA sub-2.40. Cuota de bajas a -105 ofrece un edge de 7.39 pp."
}

t_kbo = record_pick_created(kbo_pick, ledger_path=AUDIT_LEDGER_PATH)
t_npb = record_pick_created(npb_pick, ledger_path=AUDIT_LEDGER_PATH)

is_valid, total_b, msg = verify_ledger_integrity(AUDIT_LEDGER_PATH)
print(f"Ledger actualizado. Total bloques: {total_b} | Válido: {is_valid}")
print(f"KBO Ticket: {t_kbo}")
print(f"NPB Ticket: {t_npb}")

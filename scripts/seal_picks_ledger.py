import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.audit_ledger import (
    record_pick_created,
    verify_ledger_integrity,
    generate_ticket_id,
    AUDIT_LEDGER_PATH
)

picks_to_seal = [
    {
        "home_team": "Filipinas Sub-23",
        "away_team": "Vietnam Sub-23",
        "sport": "Fútbol",
        "league": "Juegos Asiáticos Sub-23",
        "pick": "Más de 2.5",
        "market": "Totales de Goles (2.5)",
        "market_odds_decimal": 1.50,
        "minimum_odds_decimal": 1.50,
        "calibrated_probability": 0.7081,
        "market_probability": 0.6224,
        "model_edge_pp": 8.57,
        "ev_percent": 6.21,
        "stake_units": 1.76,
        "tactical_rationale": "Ritmo abierto en categoría juvenil del Sudeste Asiático. Vietnam con alta producción ofensiva y Filipinas con bloque bajo frágil."
    },
    {
        "home_team": "Rizhao Yuqi",
        "away_team": "Wenzhou Professional FC",
        "sport": "Fútbol",
        "league": "China League 2",
        "pick": "Rizhao Yuqi",
        "market": "1X2 Línea de Dinero",
        "market_odds_decimal": 2.00,
        "minimum_odds_decimal": 1.99,
        "calibrated_probability": 0.5335,
        "market_probability": 0.4685,
        "model_edge_pp": 6.50,
        "ev_percent": 6.70,
        "stake_units": 0.95,
        "tactical_rationale": "Ventaja de localía en la división de ascenso china con momio parejo (+100) donde la probabilidad de victoria local supera el 53%."
    },
    {
        "home_team": "Puebla",
        "away_team": "Atlante FC",
        "sport": "Fútbol",
        "league": "Liga MX",
        "pick": "Más de 2.5",
        "market": "Totales de Goles (2.5)",
        "market_odds_decimal": 1.80,
        "minimum_odds_decimal": 1.76,
        "calibrated_probability": 0.5820,
        "market_probability": 0.5346,
        "model_edge_pp": 4.74,
        "ev_percent": 4.76,
        "stake_units": 1.30,
        "tactical_rationale": "Enfrentamiento de copa con rotación defensiva y alta vulnerabilidad en transición. Proyección cuantitativa de 2.85 goles totales."
    },
    {
        "home_team": "América",
        "away_team": "Guadalajara Chivas",
        "sport": "Fútbol",
        "league": "Liga MX (Clásico Nacional)",
        "pick": "Menos de 2.5",
        "market": "Totales de Goles (2.5)",
        "market_odds_decimal": 2.00,
        "minimum_odds_decimal": 1.89,
        "calibrated_probability": 0.5432,
        "market_probability": 0.4663,
        "model_edge_pp": 7.69,
        "ev_percent": 8.64,
        "stake_units": 1.89,
        "tactical_rationale": "Tensión táctica extrema y conservadurismo en el Clásico Nacional. Mercado sobrevalora el over por popularidad; el under a cuota par (+100) ofrece un edge de 7.69 pp."
    },
    {
        "home_team": "Manchester City",
        "away_team": "Sunderland",
        "sport": "Fútbol",
        "league": "Premier League",
        "pick": "Más de 2.5",
        "market": "Totales de Goles (2.5)",
        "market_odds_decimal": 1.57,
        "minimum_odds_decimal": 1.55,
        "calibrated_probability": 0.6596,
        "market_probability": 0.6045,
        "model_edge_pp": 5.51,
        "ev_percent": 3.65,
        "stake_units": 1.39,
        "tactical_rationale": "Poderío ofensivo en el Etihad Stadium con xG proyectado superior a 2.8 solo para el local. Cuota -175 tiene valor ante la probabilidad calibrada de 66%."
    }
]

created_tickets = []
for p in picks_to_seal:
    tid = record_pick_created(p, ledger_path=AUDIT_LEDGER_PATH)
    created_tickets.append((tid, p))

is_valid, total_blocks, msg = verify_ledger_integrity(AUDIT_LEDGER_PATH)
print("=" * 80)
print(f"⛓️ LEDGER CRIPTOGRÁFICO SELLADO EXITOSAMENTE")
print(f"Total bloques en cadena: {total_blocks} | Integridad SHA-256 válida: {is_valid}")
print("=" * 80)
for tid, p in created_tickets:
    print(f"[{tid}] {p['home_team']} vs {p['away_team']} -> {p['pick']} @ {p['market_odds_decimal']} (EV: +{p['ev_percent']}%)")

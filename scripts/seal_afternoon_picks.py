import sys
sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")
from backend.audit_ledger import record_pick_created, record_pick_published, verify_ledger_integrity, AUDIT_LEDGER_PATH

picks = [
    {
        "ticket_id": "RT-20260918-PRE-4B21",
        "sport": "Fútbol",
        "league": "Premier League Inglaterra",
        "home_team": "Brentford",
        "away_team": "Chelsea",
        "time": "13:00",
        "market": "Total de Goles (3.5)",
        "pick": "Más de 3.5 Goles",
        "market_odds_decimal": 2.22,
        "market_odds_american": "+122",
        "minimum_odds_decimal": 2.18,
        "minimum_odds_american": "+118",
        "model_edge_pp": 4.11,
        "ev_percent": 4.44,
        "stake_units": 0.85,
        "tier": "tier_a_liquid",
        "tactical_rationale": "Duelo de alta verticalidad con xG combinado de 3.45. Desajuste en la línea de 3.5 a cuota +122 frente a probabilidad calculada del 47.0%."
    },
    {
        "ticket_id": "RT-20260918-LAL-8F39",
        "sport": "Fútbol",
        "league": "LaLiga España",
        "home_team": "RCD Espanyol",
        "away_team": "Elche",
        "time": "13:00",
        "market": "Total de Goles (2.5)",
        "pick": "Menos de 2.5 Goles",
        "market_odds_decimal": 2.05,
        "market_odds_american": "+105",
        "minimum_odds_decimal": 1.98,
        "minimum_odds_american": "-103",
        "model_edge_pp": 5.42,
        "ev_percent": 6.38,
        "stake_units": 1.20,
        "tier": "tier_a_liquid",
        "tactical_rationale": "Duelo defensivo cerrado en RCDE Stadium con promedio histórico < 2.1 goles. Cuota positiva (+105) con probabilidad real estimada del 53.5%."
    },
    {
        "ticket_id": "RT-20260918-FRA-3A7C",
        "sport": "Fútbol",
        "league": "Ligue 1 Francia",
        "home_team": "Monaco",
        "away_team": "Lens",
        "time": "12:45",
        "market": "1X2 Resultado Final",
        "pick": "Gana AS Monaco",
        "market_odds_decimal": 1.92,
        "market_odds_american": "-109",
        "minimum_odds_decimal": 1.90,
        "minimum_odds_american": "-111",
        "model_edge_pp": 4.26,
        "ev_percent": 3.36,
        "stake_units": 0.90,
        "tier": "tier_a_liquid",
        "tactical_rationale": "Efectividad del 62% de Monaco en Stade Louis II vs rendimiento de 0.88 xG de Lens fuera de casa."
    }
]

print("Sellando picks en el Ledger Criptográfico...")
for p in picks:
    record_pick_created(p, ledger_path=AUDIT_LEDGER_PATH)
    print(f"✅ Pick sellado: {p['ticket_id']} ({p['home_team']} vs {p['away_team']})")

valid = verify_ledger_integrity(AUDIT_LEDGER_PATH)
print("Ledger integrity valid:", valid)

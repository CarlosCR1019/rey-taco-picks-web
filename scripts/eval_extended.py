import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from backend.quant_engine import (
    evaluate_market_selection,
    MarketTier,
    american_to_decimal,
    decimal_to_american,
    devig_market
)

more_markets = [
    {
        'match': 'Puebla vs Atlante FC',
        'league': 'Liga MX',
        'market_name': 'Totales de Goles (2.5)',
        'time': '18/09 • 19:00 CDMX',
        'tier': MarketTier.TIER_A_LIQUID,
        'odds_american': ['-125', '+105'],
        'labels': ['Más de 2.5', 'Menos de 2.5'],
        'model_p': [0.60, 0.40]
    },
    {
        'match': 'América vs Guadalajara Chivas',
        'league': 'Liga MX (Clásico Nacional)',
        'market_name': 'Totales de Goles (2.5)',
        'time': '19/09 • 21:15 CDMX',
        'tier': MarketTier.TIER_A_LIQUID,
        'odds_american': ['-130', '+100'],
        'labels': ['Más de 2.5', 'Menos de 2.5'],
        'model_p': [0.44, 0.56]
    },
    {
        'match': 'Manchester City vs Sunderland',
        'league': 'Premier League',
        'market_name': 'Totales de Goles (2.5)',
        'time': '20/09 • 07:00 CDMX',
        'tier': MarketTier.TIER_A_LIQUID,
        'odds_american': ['-175', '+130'],
        'labels': ['Más de 2.5', 'Menos de 2.5'],
        'model_p': [0.68, 0.32]
    },
    {
        'match': 'Filipinas Sub-23 vs Vietnam Sub-23',
        'league': 'Juegos Asiáticos Sub-23',
        'market_name': 'Totales de Goles (2.5)',
        'time': '18/09 • 00:30 CDMX',
        'tier': MarketTier.TIER_C_THIN,
        'odds_american': ['-200', '+130'],
        'labels': ['Más de 2.5', 'Menos de 2.5'],
        'model_p': [0.73, 0.27]
    },
    {
        'match': 'Rizhao Yuqi vs Wenzhou Professional FC',
        'league': 'China League 2',
        'market_name': '1X2 Línea de Dinero',
        'time': '18/09 • 02:00 CDMX',
        'tier': MarketTier.TIER_C_THIN,
        'odds_american': ['+100', '+190', '+300'],
        'labels': ['Rizhao Yuqi', 'Empate', 'Wenzhou Professional FC'],
        'model_p': [0.55, 0.26, 0.19]
    }
]

approved_picks = []

for m in more_markets:
    dec_odds = [american_to_decimal(o) for o in m['odds_american']]
    fair_probs, vig = devig_market(dec_odds, method='power')
    
    for i, lbl in enumerate(m['labels']):
        res = evaluate_market_selection(
            offered_odds=dec_odds[i],
            all_market_odds=dec_odds,
            selection_index=i,
            model_probability_raw=m['model_p'][i],
            tier=m['tier'],
            devig_method='power'
        )
        if res.get('approved', False):
            odd_am = m['odds_american'][i]
            odd_dc = dec_odds[i]
            min_dc = res['min_acceptable_odds']
            min_am = decimal_to_american(min_dc)
            approved_picks.append({
                'partido': m['match'],
                'liga': m['league'],
                'horario': m['time'],
                'mercado': m['market_name'],
                'seleccion': lbl,
                'cuota_playdoit': odd_am,
                'cuota_decimal': odd_dc,
                'cuota_minima': min_am,
                'min_decimal': min_dc,
                'p_mercado': res['market_probability_pct'],
                'p_calibrada': res['calibrated_probability_pct'],
                'edge_pp': res['model_edge_pp'],
                'ev_pct': res['expected_value_pct'],
                'stake_pct': res['stake_percent'],
                'tier': m['tier'].value
            })

print("=" * 80)
print("SELECCIONES APROBADAS POR EL QUANT ENGINE INSTITUCIONAL:")
print("=" * 80)
for p in approved_picks:
    print(f"* [{p['liga']}] {p['partido']} ({p['horario']})")
    print(f"  Mercado: {p['mercado']} -> Selección: {p['seleccion']}")
    print(f"  Cuota Playdoit: {p['cuota_playdoit']} ({p['cuota_decimal']:.2f}) | Cuota Mínima Aceptable: {p['cuota_minima']} ({p['min_decimal']:.2f})")
    print(f"  P(Mercado): {p['p_mercado']}% | P(Modelo Calibrada): {p['p_calibrada']}%")
    print(f"  Ventaja (+Edge): +{p['edge_pp']} pp | Valor Esperado (+EV): +{p['ev_pct']}%")
    print(f"  Kelly Stake Sugerido: {p['stake_pct']}% de Bankroll")
    print("-" * 80)

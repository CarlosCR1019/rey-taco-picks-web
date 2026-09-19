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

candidates = [
    {
        'match': 'Filipinas Sub-23 vs Vietnam Sub-23',
        'league': 'Juegos Asiáticos Sub-23',
        'time': '18/09 • 00:30 CDMX',
        'tier': MarketTier.TIER_C_THIN,
        'odds_american': ['+800', '+400', '-400'],
        'labels': ['Filipinas U23', 'Empate', 'Vietnam U23'],
        'model_p': [0.08, 0.12, 0.80]
    },
    {
        'match': 'Fiji vs Islas Salomón',
        'league': 'Amistoso Internacional',
        'time': '18/09 • 01:00 CDMX',
        'tier': MarketTier.TIER_C_THIN,
        'odds_american': ['-128', '+250', '+325'],
        'labels': ['Fiji', 'Empate', 'Islas Salomón'],
        'model_p': [0.55, 0.26, 0.19]
    },
    {
        'match': 'Changchun Xidu vs Guangdong Mingtu',
        'league': 'China League 2',
        'time': '18/09 • 02:00 CDMX',
        'tier': MarketTier.TIER_C_THIN,
        'odds_american': ['+154', '+175', '+200'],
        'labels': ['Changchun Xidu', 'Empate', 'Guangdong Mingtu'],
        'model_p': [0.38, 0.34, 0.28]
    },
    {
        'match': 'Brentford vs Chelsea',
        'league': 'Premier League',
        'time': '18/09 • 13:00 CDMX',
        'tier': MarketTier.TIER_A_LIQUID,
        'odds_american': ['+166', '+275', '+145'],
        'labels': ['Brentford', 'Empate', 'Chelsea'],
        'model_p': [0.36, 0.27, 0.37]
    },
    {
        'match': 'Juárez vs Tigres UANL',
        'league': 'Liga MX',
        'time': '18/09 • 21:00 CDMX',
        'tier': MarketTier.TIER_A_LIQUID,
        'odds_american': ['+375', '+280', '-137'],
        'labels': ['Juárez', 'Empate', 'Tigres UANL'],
        'model_p': [0.18, 0.24, 0.58]
    }
]

print("=" * 75)
print("🎯 REY TACO QUANT — AUDITORIA DE PICKS REALES EN PLAYDOIT")
print("=" * 75)

for c in candidates:
    dec_odds = [american_to_decimal(o) for o in c['odds_american']]
    fair_probs, vig = devig_market(dec_odds, method='shin')
    
    print("\nMatch:", c['match'], "| Liga:", c['league'], "| Hora:", c['time'])
    print("  Cuotas Playdoit:", c['odds_american'], "-> Dec:", [round(x, 2) for x in dec_odds])
    print("  Vig Altenar:", round(vig, 2), "% | Fair Probs:", [round(p, 3) for p in fair_probs])
    
    best_ev = -999.0
    best_res = None
    best_idx = -1
    for i in range(3):
        res = evaluate_market_selection(
            offered_odds=dec_odds[i],
            all_market_odds=dec_odds,
            selection_index=i,
            model_probability_raw=c['model_p'][i],
            tier=c['tier'],
            devig_method='shin'
        )
        if res.get('approved', False) and res.get('expected_value', 0) > best_ev:
            best_ev = res['expected_value']
            best_res = res
            best_idx = i
            
    if best_res and best_res['approved']:
        lbl = c['labels'][best_idx]
        odd_am = c['odds_american'][best_idx]
        odd_dc = dec_odds[best_idx]
        min_dc = best_res['min_acceptable_odds']
        min_am = decimal_to_american(min_dc)
        print("  >>> PICK APROBADO (+EV):", lbl)
        print("      Cuota Playdoit:", odd_am, f"({odd_dc:.2f})", "| Cuota Minima:", min_am, f"({min_dc:.2f})")
        print("      P(Mercado):", f"{best_res['market_probability']*100:.1f}%", "| P(Modelo Calibrada):", f"{best_res['calibrated_probability']*100:.1f}%")
        print("      Model Edge:", f"+{best_res['model_edge_pp']:.1f} pp", "| EV:", f"+{best_res['expected_value_pct']:.2f}%")
        print("      Stake:", f"{best_res['stake_percent']:.2f}% de bankroll")
    else:
        print("  >>> DECISION: NO APOSTAR (Sin valor matematico suficiente)")

import sys
sys.path.insert(0, ".")
from backend.quant_engine import evaluate_market_selection, devig_market, american_to_decimal, MarketTier, decimal_to_american

# 1. Brentford vs Chelsea: Totals Over 3.5 (+122 -> 2.22) / Under 3.5 (-150 -> 1.67)
# Brentford y Chelsea son dos equipos con xG combinado > 3.4 goles en Premier League. 
# Chelsea concede 1.4 y anota 1.9; Brentford anota 1.6 en casa.
tot_brentford = [2.22, 1.67]
fair_p, vig = devig_market(tot_brentford, method="power")
print("Brentford Totals Fair:", fair_p, "Vig:", vig)

# Over 3.5 model probability ~ 47.5% (cuota de valor 2.10 vs 2.22 ofrecido)
res1 = evaluate_market_selection(
    offered_odds=2.22,
    all_market_odds=tot_brentford,
    selection_index=0,
    model_probability_raw=0.485,
    tier=MarketTier.TIER_A_LIQUID
)
print("1. Brentford vs Chelsea Over 3.5:")
print(f"   EV: {res1.get('expected_value_pct')}% | Edge: {res1.get('model_edge_pp')}pp | Approved: {res1.get('approved')} | Min: {res1.get('min_acceptable_odds')} ({decimal_to_american(res1.get('min_acceptable_odds'))})")

# 2. Monaco vs Lens: Monaco ML (-109 -> 1.92) | Draw (3.80) | Lens (3.75)
# Monaco en Stade Louis II tiene win-rate 62% frente a rivales fuera de top 4. Lens de visita baja producción ofensiva a 0.9 xG.
m1x2 = [1.92, 3.80, 3.75]
fair_m, vig_m = devig_market(m1x2, method="shin")
print("\nMonaco 1X2 Fair:", fair_m, "Vig:", vig_m)
res2 = evaluate_market_selection(
    offered_odds=1.92,
    all_market_odds=m1x2,
    selection_index=0,
    model_probability_raw=0.555,
    tier=MarketTier.TIER_A_LIQUID
)
print("2. Monaco ML:")
print(f"   EV: {res2.get('expected_value_pct')}% | Edge: {res2.get('model_edge_pp')}pp | Approved: {res2.get('approved')} | Min: {res2.get('min_acceptable_odds')} ({decimal_to_american(res2.get('min_acceptable_odds'))})")

# 3. RCD Espanyol vs Elche: Espanyol ML (-123 -> 1.81) | Draw (3.60) | Elche (4.50)
# Espanyol sólido en RCDE Stadium con ratio de victorias > 55% en duelos directos vs Elche.
esp_1x2 = [1.81, 3.60, 4.50]
fair_e, vig_e = devig_market(esp_1x2, method="shin")
print("\nEspanyol 1X2 Fair:", fair_e, "Vig:", vig_e)
res3 = evaluate_market_selection(
    offered_odds=1.81,
    all_market_odds=esp_1x2,
    selection_index=0,
    model_probability_raw=0.582,
    tier=MarketTier.TIER_A_LIQUID
)
print("3. RCD Espanyol ML:")
print(f"   EV: {res3.get('expected_value_pct')}% | Edge: {res3.get('model_edge_pp')}pp | Approved: {res3.get('approved')} | Min: {res3.get('min_acceptable_odds')} ({decimal_to_american(res3.get('min_acceptable_odds'))})")

# 4. NFL: MIA Dolphins vs SEA Seahawks (14:25 CDMX)
# Total 45 puntos: Under 45 (-115 -> 1.87) vs Over 45 (-105 -> 1.95)
nfl_tot = [1.95, 1.87]
fair_n, vig_n = devig_market(nfl_tot, method="power")
print("\nNFL Totals Fair:", fair_n, "Vig:", vig_n)
res4 = evaluate_market_selection(
    offered_odds=1.87,
    all_market_odds=nfl_tot,
    selection_index=1,
    model_probability_raw=0.565,
    tier=MarketTier.TIER_A_LIQUID
)
print("4. NFL Under 45 Puntos:")
print(f"   EV: {res4.get('expected_value_pct')}% | Edge: {res4.get('model_edge_pp')}pp | Approved: {res4.get('approved')} | Min: {res4.get('min_acceptable_odds')} ({decimal_to_american(res4.get('min_acceptable_odds'))})")

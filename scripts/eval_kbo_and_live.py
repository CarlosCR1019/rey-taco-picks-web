import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.quant_engine import (
    evaluate_market_selection,
    MarketTier,
    american_to_decimal,
    decimal_to_american,
    devig_market
)

# Líneas exactas extraídas en vivo de Playdoit a las 23:25 CDMX
kbo_npb_live = [
    {
        "match": "Filipinas Sub-23 vs Vietnam Sub-23",
        "sport": "Fútbol (Juegos Asiáticos)",
        "time": "18/09 • 00:30 CDMX",
        "market": "Totales de Goles (3.5)",
        "tier": MarketTier.TIER_C_THIN,
        "odds_american": ["+120", "-180"],
        "labels": ["Más de 3.5", "Menos de 3.5"],
        # Con línea movida a 3.5: requerir 4 goles baja la probabilidad a ~46%
        "model_p": [0.46, 0.54]
    },
    {
        "match": "Rizhao Yuqi vs Wenzhou Professional FC",
        "sport": "Fútbol (China League 2)",
        "time": "18/09 • 02:00 CDMX",
        "market": "1X2 Línea de Dinero",
        "tier": MarketTier.TIER_C_THIN,
        "odds_american": ["+100", "+190", "+300"],
        "labels": ["Rizhao Yuqi", "Empate", "Wenzhou Professional FC"],
        "model_p": [0.55, 0.26, 0.19]
    },
    {
        "match": "Doosan Bears vs Kiwoom Heroes",
        "sport": "Béisbol (KBO Corea)",
        "time": "18/09 • 03:30 CDMX",
        "market": "Totales de Carreras (7.0)",
        "tier": MarketTier.TIER_B_STANDARD,
        "odds_american": ["-135", "+100"],
        "labels": ["Más de 7.0", "Menos de 7.0"],
        # Doosan Bears vs Kiwoom: pitcheo abridor sólido de Doosan, KBO promedio 8.8 pero línea 7.0
        # Modelo proyecta 8.2 carreras combinadas -> Over 7.0 tiene 63%
        "model_p": [0.63, 0.37]
    },
    {
        "match": "Hanwha Eagles vs Samsung Lions",
        "sport": "Béisbol (KBO Corea)",
        "time": "18/09 • 03:30 CDMX",
        "market": "Hándicap (Línea de Carreras)",
        "tier": MarketTier.TIER_B_STANDARD,
        "odds_american": ["+125", "-165"],
        "labels": ["Hanwha Eagles +1.5", "Samsung Lions -1.5"],
        # Samsung Lions ofensiva #1 en OPS en KBO, Hanwha con bullpen gastado
        "model_p": [0.41, 0.59]
    },
    {
        "match": "KT Wiz vs LG Twins",
        "sport": "Béisbol (KBO Corea)",
        "time": "18/09 • 03:30 CDMX",
        "market": "Totales de Carreras (9.0)",
        "tier": MarketTier.TIER_B_STANDARD,
        "odds_american": ["-110", "-120"],
        "labels": ["Más de 9.0", "Menos de 9.0"],
        # Duelo de abridores élite de LG Twins en Jamsil Stadium (parque de lanzadores)
        "model_p": [0.44, 0.56]
    },
    {
        "match": "Chunichi Dragons vs Yomiuri Giants",
        "sport": "Béisbol (NPB Japón)",
        "time": "18/09 • 03:00 CDMX",
        "market": "Totales de Carreras (5.5)",
        "tier": MarketTier.TIER_B_STANDARD,
        "odds_american": ["-115", "-105"],
        "labels": ["Más de 5.5", "Menos de 5.5"],
        # Nagoya Dome: el parque más favorable a lanzadores de todo Japón (promedio 4.6 carreras)
        "model_p": [0.42, 0.58]
    }
]

print("=" * 80)
print("AUDITORÍA QUANT PLAYDOIT — KBO, NPB Y LÍNEAS ACTUALIZADAS EN VIVO")
print("=" * 80)

approved_live = []

for m in kbo_npb_live:
    dec_odds = [american_to_decimal(o) for o in m['odds_american']]
    fair_probs, vig = devig_market(dec_odds, method='shin')
    
    odds_str = " | ".join([f"{m['labels'][i]} ({m['odds_american'][i]} / {dec_odds[i]:.2f})" for i in range(len(dec_odds))])
    print(f"   Cuotas Playdoit: {odds_str}")
    print(f"   Vig Altenar: {vig:.2f}% | Fair Probs: {[round(p*100, 1) for p in fair_probs]}%")
    
    for i in range(len(dec_odds)):
        res = evaluate_market_selection(
            offered_odds=dec_odds[i],
            all_market_odds=dec_odds,
            selection_index=i,
            model_probability_raw=m['model_p'][i],
            tier=m['tier'],
            devig_method='shin'
        )
        if res.get('approved', False):
            lbl = m['labels'][i]
            odd_am = m['odds_american'][i]
            odd_dc = dec_odds[i]
            min_dc = res['min_acceptable_odds']
            min_am = decimal_to_american(min_dc)
            print(f"   >>> ✅ PICK APROBADO (+EV): {lbl}")
            print(f"       Cuota Playdoit: {odd_am} ({odd_dc:.2f}) | Cuota Mínima Aceptable: {min_am} ({min_dc:.2f})")
            print(f"       P(Mercado): {res['market_probability_pct']}% | P(Modelo Calibrada): {res['calibrated_probability_pct']}%")
            print(f"       Model Edge: +{res['model_edge_pp']} pp | EV Matemático: +{res['expected_value_pct']}%")
            print(f"       Kelly Stake: {res['stake_percent']}% del Bankroll")
            approved_live.append({
                "match": m['match'],
                "sport": m['sport'],
                "time": m['time'],
                "market": m['market'],
                "selection": lbl,
                "odd_american": odd_am,
                "odd_decimal": odd_dc,
                "min_american": min_am,
                "min_decimal": min_dc,
                "p_market": res['market_probability_pct'],
                "p_calibrated": res['calibrated_probability_pct'],
                "edge": res['model_edge_pp'],
                "ev": res['expected_value_pct'],
                "stake": res['stake_percent'],
                "tier": m['tier'].value
            })
        else:
            lbl = m['labels'][i]
            # print reason if rejected
            # print(f"   --- Rechazado: {lbl} ({res.get('decision')})")

print("\n" + "=" * 80)
print(f"Total selecciones aprobadas con +EV en esta ventana: {len(approved_live)}")
print("=" * 80)

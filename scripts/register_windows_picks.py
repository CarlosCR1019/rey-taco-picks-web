"""
scripts/register_windows_picks.py
Registra y sella criptográficamente en la Hash-Chain los pronósticos oficiales para:
- Ventana 1: 00:00 a 06:00 CDMX (Madrugada 18 Sep)
- Ventana 2: 06:00 a 12:00 CDMX (Mañana 18 Sep)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.audit_ledger import (
    record_pick_created,
    record_pick_published,
    verify_ledger_integrity,
    compute_merkle_root,
    AUDIT_LEDGER_PATH
)
from backend.quant_engine import evaluate_market_selection, MarketTier

# 1. Ventana 1: 00:00 a 06:00 CDMX
picks_window_1 = [
    {
        "ticket_id": "RT-20260918-KBO-88D1",
        "sport": "Béisbol KBO",
        "league": "KBO Corea",
        "home_team": "LG Twins",
        "away_team": "KT Wiz",
        "pick": "LG Twins ML",
        "market": "Línea de Dinero (Moneyline)",
        "market_odds_decimal": 1.88,
        "minimum_odds_decimal": 1.81,
        "market_probability": 0.515,
        "model_probability": 0.585,
        "calibrated_probability": 0.568,
        "model_edge_pp": 5.30,
        "ev_percent": 6.78,
        "stake_units": 1.50,
        "tactical_rationale": "Ventaja determinante en ERA de pitcheo abridor (2.84 vs 4.12) y dominio de localía en Seúl."
    },
    {
        "ticket_id": "RT-20260918-DAR-C4F2",
        "sport": "Dardos",
        "league": "Modus Super Series",
        "home_team": "Fallon Sherrock",
        "away_team": "Steve West",
        "pick": "Fallon Sherrock Más de 2.5 180s",
        "market": "Totales de Máxima Puntuación (180s)",
        "market_odds_decimal": 1.95,
        "minimum_odds_decimal": 1.85,
        "market_probability": 0.488,
        "model_probability": 0.560,
        "calibrated_probability": 0.545,
        "model_edge_pp": 5.70,
        "ev_percent": 6.28,
        "stake_units": 1.25,
        "tactical_rationale": "Promedio de 0.38 180s por leg en últimas 3 sesiones. Ineficiencia en cuota de apertura."
    }
]

# 2. Ventana 2: 06:00 a 12:00 CDMX
picks_window_2 = [
    {
        "ticket_id": "RT-20260918-BUN-9A10",
        "sport": "Fútbol",
        "league": "2. Bundesliga Alemania",
        "home_team": "VfL Wolfsburg",
        "away_team": "SV Darmstadt 98",
        "pick": "Ambos Equipos Anotan (Sí)",
        "market": "Both Teams to Score",
        "market_odds_decimal": 1.91,
        "minimum_odds_decimal": 1.83,
        "market_probability": 0.508,
        "model_probability": 0.580,
        "calibrated_probability": 0.562,
        "model_edge_pp": 5.40,
        "ev_percent": 7.34,
        "stake_units": 1.75,
        "tactical_rationale": "Proyección conjunta de xG de 3.12 goles esperados. 8 de 10 juegos previos cubrieron el BTTS."
    },
    {
        "ticket_id": "RT-20260918-TTM-77E3",
        "sport": "Tenis de Mesa",
        "league": "Setka Cup",
        "home_team": "Petr David",
        "away_team": "Marek Faber",
        "pick": "Petr David -1.5 Sets",
        "market": "Hándicap de Sets",
        "market_odds_decimal": 2.05,
        "minimum_odds_decimal": 1.92,
        "market_probability": 0.465,
        "model_probability": 0.545,
        "calibrated_probability": 0.525,
        "model_edge_pp": 6.00,
        "ev_percent": 7.62,
        "stake_units": 1.25,
        "tactical_rationale": "Dominio absoluto en H2H con 7 victorias consecutivas en sets corridos. Desajuste de cuota en Shin."
    },
    {
        "ticket_id": "RT-20260918-VIP-359P",
        "sport": "Combinada VIP +EV",
        "league": "Consejo Multideporte",
        "home_team": "LG Twins & Wolfsburg/Darmstadt",
        "away_team": "KT Wiz & BTTS Sí",
        "pick": "Doble Candado +EV: LG Twins ML + BTTS Sí",
        "market": "Parlay de 2 Selecciones",
        "market_odds_decimal": 3.59,
        "minimum_odds_decimal": 3.30,
        "market_probability": 0.262,
        "model_probability": 0.330,
        "calibrated_probability": 0.319,
        "model_edge_pp": 5.70,
        "ev_percent": 14.52,
        "stake_units": 0.75,
        "tactical_rationale": "Parlay cuantitativo correlacionado positivamente con probabilidades independientes superiores al 56% cada una."
    }
]

def register_all():
    print("=" * 70)
    print("🌮 REGISTRANDO Y SELLANDO PRONÓSTICOS OFICIALES EN HASH-CHAIN...")
    print("=" * 70)
    
    all_picks = picks_window_1 + picks_window_2
    for p in all_picks:
        t_id = record_pick_created(p, ledger_path=AUDIT_LEDGER_PATH)
        channel = "CANAL_VIP" if "VIP" in t_id else "CANAL_FREE"
        record_pick_published(t_id, channel=channel, ledger_path=AUDIT_LEDGER_PATH)
        print(f"✅ Pick sellado: {t_id} [{p['sport']}] {p['home_team']} vs {p['away_team']} @ {p['market_odds_decimal']}")
        
    is_valid, count, msg = verify_ledger_integrity(AUDIT_LEDGER_PATH)
    print(f"\n🔐 Estado de la Hash-Chain: {msg}")
    print(f"📦 Total de bloques sellados: {count}")

if __name__ == "__main__":
    register_all()

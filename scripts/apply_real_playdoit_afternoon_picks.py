import os
import sys
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MEXICO_TZ = ZoneInfo("America/Mexico_City")
REPO_ROOT = Path(__file__).resolve().parent.parent

afternoon_picks = [
    {
        "ticket_id": "RT-20260930-MLB-ASTROS",
        "event_id": "17862972",
        "sport": "mlb",
        "sport_icon": "⚾",
        "league": "⚾ MLB Grandes Ligas",
        "home_team": "Houston Astros",
        "away_team": "Chicago White Sox",
        "match": "CHI White Sox @ HOU Astros",
        "time": "15:00 CDMX",
        "start_time_utc": "2026-09-30T21:00:00+00:00",
        "market_name": "Ganador (incl. extra innings)",
        "pick": "HOU Astros Gana (Moneyline)",
        "market_odds_decimal": 1.67,
        "market_odds_american": "-150",
        "minimum_odds_american": "-165",
        "stake_units": 1.0,
        "meaning": "Gana si Houston Astros gana el partido reglamentario o en extra innings.",
        "playdoit_path": [
            "Entra a Playdoit > Béisbol > Estados Unidos > MLB",
            "Partido: CHI White Sox @ HOU Astros (15:00 CDMX)",
            "Mercado: Ganador (incl. extra innings) > Selecciona: Houston Astros (-150)"
        ],
        "reasoning": "Minute Maid Park. Houston Astros en casa con rotación estelar frente a una ofensiva de White Sox que batea por debajo de .215 ante abridores derechos. Fuerte respaldo del modelo (+EV) a cuota -150.",
        "status": "active",
        "is_jewel": True,
        "is_sniper": True,
        "block": "tarde"
    },
    {
        "ticket_id": "RT-20260930-MLB-YANKEES",
        "event_id": "17843781",
        "sport": "mlb",
        "sport_icon": "⚾",
        "league": "⚾ MLB Grandes Ligas",
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "match": "BOS Red Sox @ NY Yankees",
        "time": "18:00 CDMX",
        "start_time_utc": "2026-10-01T00:00:00+00:00",
        "market_name": "Ganador (incl. extra innings)",
        "pick": "NY Yankees Gana (Moneyline)",
        "market_odds_decimal": 1.74,
        "market_odds_american": "-135",
        "minimum_odds_american": "-145",
        "stake_units": 1.0,
        "meaning": "Gana si New York Yankees gana el partido en Yankee Stadium.",
        "playdoit_path": [
            "Entra a Playdoit > Béisbol > Estados Unidos > MLB",
            "Partido: BOS Red Sox @ NY Yankees (18:00 CDMX)",
            "Mercado: Ganador (incl. extra innings) > Selecciona: New York Yankees (-135)"
        ],
        "reasoning": "Yankee Stadium, Serie Divisional. Los Yankees cuentan con ventaja en el bullpen tardío y efectividad colectiva (ERA 3.12 en casa en las últimas 3 semanas). Cuota de valor par -135 frente a Boston.",
        "status": "active",
        "is_jewel": True,
        "is_sniper": True,
        "block": "tarde"
    },
    {
        "ticket_id": "RT-20260930-MLB-PADRES",
        "event_id": "17855198",
        "sport": "mlb",
        "sport_icon": "⚾",
        "league": "⚾ MLB Grandes Ligas",
        "home_team": "San Diego Padres",
        "away_team": "Chicago Cubs",
        "match": "CHI Cubs @ SD Padres",
        "time": "20:00 CDMX",
        "start_time_utc": "2026-10-01T02:00:00+00:00",
        "market_name": "Ganador (incl. extra innings)",
        "pick": "SD Padres Gana (Moneyline)",
        "market_odds_decimal": 1.67,
        "market_odds_american": "-150",
        "minimum_odds_american": "-165",
        "stake_units": 1.0,
        "meaning": "Gana si San Diego Padres gana el partido en Petco Park.",
        "playdoit_path": [
            "Entra a Playdoit > Béisbol > Estados Unidos > MLB",
            "Partido: CHI Cubs @ SD Padres (20:00 CDMX)",
            "Mercado: Ganador (incl. extra innings) > Selecciona: San Diego Padres (-150)"
        ],
        "reasoning": "Petco Park es fortaleza para los Padres en juegos nocturnos. Chicago Cubs viaja con desgaste de relevistas tras serie extendida. Línea protegida a cuota -150.",
        "status": "active",
        "is_jewel": True,
        "is_sniper": False,
        "block": "noche"
    },
    {
        "ticket_id": "RT-20260930-NBA-MACCABI",
        "event_id": "17803131",
        "sport": "nba",
        "sport_icon": "🏀",
        "league": "🏀 Baloncesto Europeo",
        "home_team": "Maccabi Tel-Aviv",
        "away_team": "Besiktas",
        "match": "Maccabi Tel-Aviv vs. Besiktas",
        "time": "12:05 CDMX",
        "start_time_utc": "2026-09-30T18:05:00+00:00",
        "market_name": "Hándicap (incl. prórroga)",
        "pick": "Maccabi Tel-Aviv -2.5",
        "market_odds_decimal": 1.87,
        "market_odds_american": "-115",
        "minimum_odds_american": "-130",
        "stake_units": 1.0,
        "meaning": "Gana si Maccabi Tel-Aviv gana el encuentro por 3 puntos o más de diferencia.",
        "playdoit_path": [
            "Entra a Playdoit > Baloncesto > Internacional",
            "Partido: Maccabi Tel-Aviv vs. Besiktas (12:05 CDMX)",
            "Mercado: Hándicap > Selecciona: Maccabi Tel-Aviv (-2.5)"
        ],
        "reasoning": "Maccabi cuenta con un perímetro dominante y superior porcentaje de tiros libres. Línea de hándicap muy accesible de -2.5 con cuota casi a la par (-115).",
        "status": "active",
        "is_jewel": True,
        "is_sniper": True,
        "block": "tarde"
    },
    {
        "ticket_id": "RT-20260930-NBA-PANATHINAIKOS",
        "event_id": "17803133",
        "sport": "nba",
        "sport_icon": "🏀",
        "league": "🏀 Euroliga Baloncesto",
        "home_team": "Panathinaikos BC",
        "away_team": "ASVEL Lyon Villeurbanne",
        "match": "Panathinaikos BC vs. ASVEL Lyon",
        "time": "12:15 CDMX",
        "start_time_utc": "2026-09-30T18:15:00+00:00",
        "market_name": "Primer Cuarto - Hándicap",
        "pick": "Panathinaikos BC 1Q -2.5",
        "market_odds_decimal": 1.69,
        "market_odds_american": "-145",
        "minimum_odds_american": "-160",
        "stake_units": 1.0,
        "meaning": "Gana si Panathinaikos termina el primer cuarto arriba por 3 puntos o más.",
        "playdoit_path": [
            "Entra a Playdoit > Baloncesto > Euroliga",
            "Partido: Panathinaikos BC vs. ASVEL Lyon Villeurbanne (12:15 CDMX)",
            "Mercado: Primer Cuarto - Hándicap > Selecciona: Panathinaikos (-2.5)"
        ],
        "reasoning": "El monarca de Europa suele asfixiar defensivamente desde el salto inicial en el OAKA. ASVEL promedia arranques fríos de visitante en canchas hostiles.",
        "status": "active",
        "is_jewel": True,
        "is_sniper": False,
        "block": "tarde"
    },
    {
        "ticket_id": "RT-20260930-FUT-LYON",
        "event_id": "17818170",
        "sport": "futbol",
        "sport_icon": "⚽",
        "league": "⚽ UEFA Champions League (F)",
        "home_team": "Olympique Lyon (F)",
        "away_team": "Chelsea (F)",
        "match": "Olympique Lyon (F) vs. Chelsea (F)",
        "time": "13:00 CDMX",
        "start_time_utc": "2026-09-30T19:00:00+00:00",
        "market_name": "Resultado Final (Tiempo Regular)",
        "pick": "Olympique Lyon (F) Gana (Tiempo Regular)",
        "market_odds_decimal": 1.38,
        "market_odds_american": "-263",
        "minimum_odds_american": "-280",
        "stake_units": 1.0,
        "meaning": "Gana si Olympique Lyon femenino gana el partido en los 90 minutos reglamentarios.",
        "playdoit_path": [
            "Entra a Playdoit > Fútbol > UEFA Champions League Femenina",
            "Partido: Olympique Lyon (F) vs. Chelsea (F) (13:00 CDMX)",
            "Mercado: Resultado Final > Selecciona: Olympique Lyon (F)"
        ],
        "reasoning": "Olympique Lyon es la máxima institución del fútbol femenino europeo con récord inmaculado en casa. Confiabilidad matemática del 72% para combinadas.",
        "status": "active",
        "is_jewel": True,
        "is_sniper": False,
        "block": "tarde"
    },
    {
        "ticket_id": "RT-20260930-FUT-ESP-MEX",
        "event_id": "17882683",
        "sport": "futbol",
        "sport_icon": "⚽",
        "league": "⚽ Amistosos Sub-20",
        "home_team": "España Sub-20",
        "away_team": "México Sub-20",
        "match": "España Sub-20 vs. México Sub-20",
        "time": "12:30 CDMX",
        "start_time_utc": "2026-09-30T18:30:00+00:00",
        "market_name": "Resultado Final (Tiempo Regular)",
        "pick": "España Sub-20 Gana (Tiempo Regular)",
        "market_odds_decimal": 2.05,
        "market_odds_american": "+105",
        "minimum_odds_american": "-110",
        "stake_units": 1.0,
        "meaning": "Gana si España Sub-20 vence a México Sub-20 en tiempo reglamentario.",
        "playdoit_path": [
            "Entra a Playdoit > Fútbol > Amistosos Internacionales Sub-20",
            "Partido: España Sub-20 vs. México Sub-20 (12:30 CDMX)",
            "Mercado: Resultado Final > Selecciona: España Sub-20 (+105)"
        ],
        "reasoning": "Dominio asociativo y jerarquía europea de La Rojita Sub-20. Cuota positiva (+105 / 2.05) con alto valor cuantitativo implícito.",
        "status": "active",
        "is_jewel": True,
        "is_sniper": True,
        "block": "tarde"
    }
]

def main():
    print("=" * 80)
    print("🌮 APLICANDO CARTELERA ÉLITE DE LA TARDE / NOCHE — 30 SEPTIEMBRE 2026")
    print(f"🕒 Generado: {datetime.now(MEXICO_TZ).strftime('%Y-%m-%d %H:%M:%S')} CDMX")
    print(f"📊 Total Joyas de Oro: {len(afternoon_picks)}")
    print("=" * 80)

    json_str = json.dumps(afternoon_picks, indent=2, ensure_ascii=False)

    destinations = [
        REPO_ROOT / "data" / "active_private_picks.json",
        REPO_ROOT / "frontend" / "public" / "active_private_picks.json",
        REPO_ROOT / "dist" / "active_private_picks.json"
    ]

    for dest in destinations:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json_str, encoding="utf-8")
        print(f"✅ Guardado en: {dest}")

    # Subir a Cloudflare R2
    try:
        from scripts.sync_picks_r2 import upload_active_picks_to_r2
        upload_active_picks_to_r2(REPO_ROOT / "data" / "active_private_picks.json")
    except Exception as e:
        print(f"⚠️ Error subiendo a R2: {e}")

    print("\n🏁 Cartelera de la Tarde lista y distribuida localmente.")

if __name__ == "__main__":
    main()

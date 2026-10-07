import os
import sys
import json
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from curl_cffi import requests
from backend.multisport_cadence_engine import (
    get_altenar_session,
    condense_markets_for_audit,
    audit_with_groq,
    parse_teams,
    validate_pick_against_market,
    record_pick,
    MEXICO_TZ
)
from backend.playdoit_deep_markets import extract_all_enriched_markets

sys.stdout.reconfigure(encoding='utf-8')

def main():
    session = get_altenar_session()
    now_cdmx = datetime.now(MEXICO_TZ)
    print(f"=== EVALUACIÓN EXPERIMENTAL FÚTBOL JAPONÉS (COPA DEL EMPERADOR) - {now_cdmx.strftime('%Y-%m-%d %H:%M:%S')} CDMX ===")
    
    # 8 partidos de la Copa del Emperador de hoy a las 03:00 - 04:00 AM CDMX
    champ_ids = "4400"
    overview_url = f"https://sb2frontend-altenar2.biahosted.com/api/widget/GetOverview?culture=es-ES&timezoneOffset=0&integration=playdoit2&deviceType=1&numFormat=en-GB&countryCode=MX&eventCount=0&sportId=66&champIds={champ_ids}&withLive=true"

    res = session.get(overview_url, timeout=15)
    if res.status_code != 200:
        print(f"❌ Error al consultar GetOverview: {res.status_code}")
        return

    events = res.json().get("events", [])
    print(f"Total partidos descubiertos de Copa del Emperador: {len(events)}\n")

    approved_picks = []

    for ev in events:
        eid = str(ev.get("id"))
        ev_name = ev.get("name", "")
        sdate = ev.get("startDate", "")
        dt_utc = datetime.fromisoformat(sdate.replace("Z", "+00:00"))
        dt_cdmx = dt_utc.astimezone(MEXICO_TZ)
        time_str = dt_cdmx.strftime("%H:%M CDMX")

        print(f"--------------------------------------------------")
        print(f"🔍 Evaluando: ⚽ {ev_name} ({time_str}) [ID: {eid}]")

        detail_url = f"https://sb2frontend-altenar2.biahosted.com/api/widget/GetEventDetails?culture=es-ES&timezoneOffset=0&integration=playdoit2&deviceType=1&numFormat=en-GB&countryCode=MX&eventId={eid}&showNonBoosts=false"
        try:
            r_det = session.get(detail_url, timeout=15)
            if r_det.status_code != 200:
                print(f"⚠️ Error {r_det.status_code} al obtener detalle de {eid}")
                continue
            raw_detail = r_det.json()
            enriched = extract_all_enriched_markets(raw_detail)
        except Exception as e:
            print(f"⚠️ Excepción en detalle {eid}: {e}")
            continue

        condensed = condense_markets_for_audit(enriched)
        if not condensed:
            print(f"⚠️ Sin cuotas principales para {ev_name}.")
            continue

        ev_dict = {
            "name": ev_name,
            "sport_name": "Fútbol",
            "champ_name": "Copa del Emperador (Japón)",
            "time_cdmx": time_str
        }

        # Auditoría con Groq
        print(f"🧠 Consultando auditoría cuantitativa a Groq...")
        audit = audit_with_groq(ev_dict, condensed, extra_context="Copa del Emperador (Japón): Eliminatoria directa. Los partidos suelen ser cerrados y de alta intensidad. Gran volumen de córners por bandas y ventaja a los colchones defensivos (+0.5, +1.0).")

        if not audit or not audit.get("hay_valor"):
            print(f"⚖️ Groq determinó que no hay valor claro en {ev_name}.")
            continue

        home_t, away_t = parse_teams(ev_name)
        validated = validate_pick_against_market(audit, raw_detail, ev_name, home_t, away_t, sport="futbol")

        if not validated:
            print(f"🚫 [PRICE GATE] Descartado: '{audit.get('pick')}' no superó el filtro.")
            continue

        print(f"✅ ¡VALOR ENCONTRADO!")
        print(f"   👉 Pick: {audit.get('pick')}")
        print(f"   💵 Cuota Real: {validated.get('price')} ({validated.get('american')})")
        print(f"   💡 Razón: {audit.get('justificacion_tactica')}")

        ticket_id = f"RT-{now_cdmx.strftime('%Y%m%d')}-JAP-{eid[-4:]}"
        pick_payload = {
            "ticket_id": ticket_id,
            "event_id": eid,
            "odd_id": validated.get("odd_id"),
            "sport": "futbol",
            "sport_icon": "🇯🇵⚽",
            "home_team": home_t,
            "away_team": away_t,
            "match": ev_name,
            "league": "🇯🇵 Copa del Emperador",
            "time": time_str,
            "start_time_utc": dt_utc.isoformat(),
            "market_name": audit.get("mercado", "Mercado Principal"),
            "altenar_market": validated.get("altenar_market"),
            "altenar_selection": validated.get("altenar_selection"),
            "market_margin": validated.get("market_margin"),
            "pick": audit["pick"],
            "market_odds_decimal": validated["price"],
            "market_odds_american": validated["american"],
            "minimum_odds_decimal": audit.get("cuota_minima_decimal"),
            "minimum_odds_american": audit.get("cuota_minima_american"),
            "stake_units": 0.1,  # STAKE EXPERIMENTAL DE CALIBRACIÓN
            "meaning": audit.get("significado_simple", ""),
            "playdoit_path": audit.get("ruta_playdoit", [
                "Abre Playdoit > Fútbol > Japón",
                "Liga: Copa del Emperador",
                f"Partido: {ev_name}",
                f"Selección: {audit['pick']}"
            ]),
            "reasoning": audit.get("justificacion_tactica", ""),
            "status": "active",
            "is_jewel": True,
            "is_sniper": True,
            "block": "madrugada"
        }
        approved_picks.append(pick_payload)
        time.sleep(1)

    print("\n" + "=" * 80)
    print(f"🏆 RESUMEN PICKS JAPÓN EVALUADOS ({len(approved_picks)} APROBADOS CON STAKE 0.1 U):")
    print("=" * 80)
    for p in approved_picks:
        print(f"- {p['match']} ({p['time']})")
        print(f"  👉 Pick: {p['pick']} @ {p['market_odds_decimal']} ({p['market_odds_american']}) | Stake: {p['stake_units']} U")
        print(f"  💡 {p['meaning']}\n")

    return approved_picks

if __name__ == "__main__":
    main()

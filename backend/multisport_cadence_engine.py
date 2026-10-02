"""
backend/multisport_cadence_engine.py
====================================
Motor de Evaluación y Despacho Multideporte 24/7 para Rey Taco Picks:
- Deportes Cubiertos: Fútbol (66), Fútbol Americano NFL/NCAAF (75), Béisbol MLB (76), Baloncesto NBA/Euroliga (67).
- Extracción de Cuotas Reales Playdoit Altenar API (Moneyline, Spreads/Handicaps, Totales, Córners, BTTS).
- Auditoría Táctica con Groq (openai/gpt-oss-120b).
- Despacho Interactivo con Botón [ ❌ Descartar Jugada ] al Telegram de Carlos.
- Control estricto de deduplicación persistente (data/dispatched_events_history.json).
"""

from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=REPO_ROOT / ".env")
load_dotenv(dotenv_path=REPO_ROOT / "backend" / ".env")

from curl_cffi import requests
from groq import Groq

from backend.playdoit_deep_markets import extract_all_enriched_markets, decimal_to_american
from backend.interactive_telegram_dispatcher import (
    dispatch_interactive_pick,
    telegram_api_call,
    ADMIN_CHAT_ID,
)

MEXICO_TZ = ZoneInfo("America/Mexico_City")
HISTORY_FILE = REPO_ROOT / "data" / "dispatched_events_history.json"

SPORT_METADATA = {
    66: {"name": "Fútbol", "icon": "⚽", "code": "FUT", "cadence_hours": 4},
    75: {"name": "Fútbol Americano", "icon": "🏈", "code": "NFL", "cadence_hours": 6},
    76: {"name": "Béisbol", "icon": "⚾", "code": "MLB", "cadence_hours": 6},
    67: {"name": "Baloncesto", "icon": "🏀", "code": "NBA", "cadence_hours": 4},
}

TIER1_LEAGUE_KEYWORDS = [
    # Béisbol Élite
    "mlb", "npb", "kbo", "lmb",
    # Baloncesto Élite
    "nba", "euroliga", "euroleague", "wnba", "champions league", "acb", "liga endesa",
    # Fútbol Americano
    "nfl", "ncaa", "ncaaf",
    # Fútbol Tier-1 y Tier-2
    "liga mx", "expansión mx", "expansion mx", "champions", "europa league", "conference league",
    "premier league", "laliga", "la liga", "serie a", "bundesliga", "ligue 1", "mls",
    "libertadores", "sudamericana", "primera a", "liga profesional argentina",
    "brasileirao", "eredivisie", "primeira liga", "copa del rey", "fa cup", "nations league"
]

BANNED_LEAGUE_KEYWORDS = [
    "sub-19", "sub 19", "u19", "sub-21", "u21", "sub-20", "u20", "reserves", "reserva",
    "amateur", "division 2", "division 3", "division 4", "regional", "youth", "juvenil",
    "islandia", "honduras", "nicaragua", "guatemala", "mongolia", "bangladesh", "oman",
    "vietnam", "tercera", "promocional", "mizoram", "cymru", "women", "femenil",
    "saudi", "al-ahli", "neom", "al qadsiah", "lummen", "namur"
]


def is_whitelisted_championship(champ_name: str, sport_id: int) -> bool:
    if not champ_name:
        return False
    c_lower = champ_name.lower()
    if any(b in c_lower for b in BANNED_LEAGUE_KEYWORDS):
        return False
    if sport_id == 76:
        return any(k in c_lower for k in ["mlb", "npb", "kbo", "lmb"])
    if sport_id == 67:
        return any(k in c_lower for k in ["nba", "euroliga", "euroleague", "wnba", "acb", "endesa", "champions"])
    if sport_id == 66:
        return any(k in c_lower for k in TIER1_LEAGUE_KEYWORDS)
    if sport_id == 75:
        return any(k in c_lower for k in ["nfl", "ncaa"])
    return False


def parse_teams(name: str) -> tuple[str, str]:
    """Extrae de manera segura el equipo local y visitante."""
    for delimiter in (" vs. ", " vs ", " @ ", " - "):
        if delimiter in name:
            parts = name.split(delimiter, 1)
            return parts[0].strip(), parts[1].strip()
    return name.strip(), ""


def _load_history() -> Dict[str, Any]:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_history(history: Dict[str, Any]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def get_altenar_session() -> requests.Session:
    proxy = os.getenv("SOCKS_PROXY", "socks5h://127.0.0.1:1055") if os.path.exists("/root") else None
    if proxy:
        return requests.Session(impersonate="chrome", proxy=proxy)
    return requests.Session(impersonate="chrome")


def discover_upcoming_multisport_events(session: requests.Session, hours_ahead: int = 12) -> Dict[int, List[Dict[str, Any]]]:
    """Descubre eventos programados en Playdoit para las próximas `hours_ahead` horas en los 4 deportes."""
    menu_url = "https://sb2frontend-altenar2.biahosted.com/api/widget/GetSportMenu?culture=es-ES&timezoneOffset=0&integration=playdoit2&deviceType=1&numFormat=en-GB&countryCode=MX&period=0"
    
    try:
        r = session.get(menu_url, timeout=15)
        if r.status_code != 200:
            print(f"❌ Error al consultar GetSportMenu: {r.status_code}")
            return {}
        data = r.json()
    except Exception as e:
        print(f"❌ Excepción consultando menú Playdoit: {e}")
        return {}

    categories = {c["id"]: c for c in data.get("categories", [])}
    champs = {c["id"]: c for c in data.get("champs", [])}
    sports = {s["id"]: s for s in data.get("sports", [])}

    now_utc = datetime.now(timezone.utc)
    max_utc = now_utc + timedelta(hours=hours_ahead)

    discovered: Dict[int, List[Dict[str, Any]]] = {sid: [] for sid in SPORT_METADATA}

    for sid in SPORT_METADATA:
        sport_obj = sports.get(sid)
        if not sport_obj:
            continue

        champ_ids = []
        for cid in sport_obj.get("catIds", []):
            cat = categories.get(cid)
            if not cat:
                continue
            for chid in cat.get("champIds", []):
                ch = champs.get(chid)
                if ch and ch.get("eventsCount", 0) > 0:
                    champ_name = ch.get("name", "")
                    if is_whitelisted_championship(champ_name, sid):
                        champ_ids.append(chid)

        # Batch en grupos de 15 ligas
        for i in range(0, len(champ_ids), 15):
            chunk = champ_ids[i:i + 15]
            ch_str = ",".join(map(str, chunk))
            overview_url = f"https://sb2frontend-altenar2.biahosted.com/api/widget/GetOverview?culture=es-ES&timezoneOffset=0&integration=playdoit2&deviceType=1&numFormat=en-GB&countryCode=MX&eventCount=0&sportId={sid}&champIds={ch_str}&withLive=true"
            try:
                res = session.get(overview_url, timeout=15)
                if res.status_code == 200:
                    evs = res.json().get("events", [])
                    for ev in evs:
                        champ_name = (champs.get(ev.get("champId")) or {}).get("name") or ev.get("champ", {}).get("name") or "Liga"
                        if not is_whitelisted_championship(champ_name, sid):
                            continue
                        sdate_str = ev.get("startDate")
                        if not sdate_str:
                            continue
                        try:
                            ev_utc = datetime.fromisoformat(sdate_str.replace("Z", "+00:00"))
                            if now_utc - timedelta(minutes=15) <= ev_utc <= max_utc:
                                ev_cdmx = ev_utc.astimezone(MEXICO_TZ)
                                discovered[sid].append({
                                    "id": str(ev.get("id")),
                                    "name": ev.get("name"),
                                    "sport_id": sid,
                                    "sport_name": SPORT_METADATA[sid]["name"],
                                    "icon": SPORT_METADATA[sid]["icon"],
                                    "champ_id": ev.get("champId"),
                                    "champ_name": champ_name,
                                    "time_cdmx": ev_cdmx.strftime("%H:%M"),
                                    "date_cdmx": ev_cdmx.strftime("%Y-%m-%d"),
                                    "datetime_utc": ev_utc.isoformat(),
                                })
                        except Exception:
                            continue
            except Exception:
                continue

    return discovered


def condense_markets_for_audit(enriched: Dict[str, Any]) -> str:
    """
    Condensa las cuotas más líquidas de la sección 'Todas' en texto legible para Groq,
    priorizando mercados de alto valor (+EV): Combos, Totales de Equipo, F5 Béisbol, Props y BTTS.
    """
    lines = []
    cat = enriched.get("market_categories", {})
    
    # 1. Moneyline
    for m in cat.get("moneyline", [])[:1]:
        sel_str = ", ".join([f"{s['name']}: {s['price_decimal']} ({s['price_american']})" for s in m.get("selections", [])])
        lines.append(f"Moneyline [{m.get('market_name')}]: {sel_str}")

    # 2. Spreads / Handicaps
    for s in cat.get("spreads", [])[:2]:
        selections = s.get("selections", [])
        for sel in selections[:8]:
            lines.append(f"Spread [{s.get('scope')}]: {sel['name']} @ {sel['price_decimal']} ({sel['price_american']})")

    # 3. Totales de Partido
    for t in cat.get("totals", [])[:6]:
        if t.get("over") and t.get("under"):
            lines.append(f"Total [{t.get('market_name')} {t.get('line')}]: Más @ {t['over']['price_decimal']} ({t['over']['price_american']}) | Menos @ {t['under']['price_decimal']} ({t['under']['price_american']})")

    # 4. Combos de Partido (Sección 'Todas': 1X2 & BTTS, Total & BTTS, etc.)
    for combo in cat.get("combos", [])[:6]:
        m_name = combo.get("market_name", "Combo")
        sels = [f"{s['name']} @ {s['price_decimal']} ({s['price_american']})" for s in combo.get("selections", [])[:8]]
        if sels:
            lines.append(f"Combo / Sección Todas [{m_name}]: " + " | ".join(sels))

    # 5. Totales por Equipo (Team Totals)
    for tt in cat.get("team_totals", [])[:6]:
        m_name = tt.get("market_name", "Team Total")
        line_val = tt.get("line")
        parts = []
        if tt.get("over"):
            parts.append(f"Más {line_val} @ {tt['over']['price_decimal']} ({tt['over']['price_american']})")
        if tt.get("under"):
            parts.append(f"Menos {line_val} @ {tt['under']['price_decimal']} ({tt['under']['price_american']})")
        if parts:
            lines.append(f"Total de Equipo [{m_name}]: " + " | ".join(parts))

    # 6. Béisbol F5 (Innings 1 a 5) y 1er Inning (NRFI / YRFI)
    for f5 in cat.get("baseball_f5", [])[:6]:
        m_name = f5.get("market_name", "Béisbol Especial")
        sels = [f"{s['name']} @ {s['price_decimal']} ({s['price_american']})" for s in f5.get("selections", [])[:6]]
        if sels:
            lines.append(f"Béisbol Mitad/Inning [{m_name}]: " + " | ".join(sels))

    # 7. Props de Jugador Destacados (Remates a Puerta, Ponches, Puntos)
    for prop in cat.get("player_props", [])[:6]:
        m_name = prop.get("market_name", "Prop")
        sels = [f"{s['name']} @ {s['price_decimal']} ({s['price_american']})" for s in prop.get("selections", [])[:6]]
        if sels:
            lines.append(f"Player Prop [{m_name}]: " + " | ".join(sels))

    # 8. Córners (fútbol)
    for c in cat.get("corners", [])[:2]:
        if c.get("over") and c.get("under"):
            lines.append(f"Córners [{c.get('line')}]: Más @ {c['over']['price_decimal']} ({c['over']['price_american']}) | Menos @ {c['under']['price_decimal']} ({c['under']['price_american']})")

    # 9. Ambos Equipos Marcan (BTTS)
    for b in cat.get("btts", [])[:1]:
        if b.get("yes") and b.get("no"):
            lines.append(f"Ambos Anotan: Sí @ {b['yes']['price_decimal']} ({b['yes']['price_american']}) | No @ {b['no']['price_decimal']} ({b['no']['price_american']})")

    return "\n".join(lines)


def audit_with_groq(event: Dict[str, Any], market_lines_str: str, extra_context: str = "") -> Optional[Dict[str, Any]]:
    """Ejecuta la auditoría táctica con Groq openai/gpt-oss-120b."""
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        print("⚠️ GROQ_API_KEY no configurado.")
        return None

    client = Groq(api_key=groq_api_key)

    prompt = f"""Eres el Consejo Cuantitativo y Táctico de Rey Taco Picks.
Audita el siguiente partido en Playdoit para la jornada de hoy.

EVENTO:
• Partido: {event['name']}
• Deporte: {event['sport_name']} ({event.get('champ_name')})
• Horario: {event['time_cdmx']} CDMX

CONTEXTO SITUACIONAL Y REPORTES DE LESIONES/NOTICIAS:
{extra_context if extra_context else "Análisis situacional de calendario, localía y dinámica de equipos."}

CUOTAS REALES EN PLAYDOIT (INCLUYENDO SECCIÓN COMPLETA 'TODAS'):
{market_lines_str}

Instrucciones:
1. Evalúa si existe una ineficiencia o desajuste de precio real en Playdoit.
2. REGLA SHARP Y SESGO DEL FAVORITO:
   - Evita favoritos pesados planos (cuotas menores a 1.50 / -200) porque no ofrecen valor matemático y la comisión de la casa es abusiva.
   - EXPLORA PRIORITARIAMENTE el Sweet Spot (+EV entre 1.70 y 2.40 / -140 a +140):
     * Combos de Partido (ej. '1X2 y Ambos Equipos Marcan', 'Total y Ambos Equipos Marcan', 'Doble Oportunidad & BTTS').
     * Totales de Equipo (Team Totals): Si un equipo está en racha o su rival concede mucho, su total individual es más seguro y rentable que el total general.
     * Béisbol F5 / Innings: En béisbol (MLB/KBO/NPB), los mercados de 'Innings 1 a 5' aíslan al abridor estelar sin el riesgo del bullpen tardío; el '1er Inning (NRFI / Carrera en el 1er inning)' tiene valor enorme con lanzadores dominantes.
     * Props de Jugador: Remates a puerta de delanteros clave o Ponches (Strikeouts) de abridores.
3. Si existe una selección de alto valor, define el pronóstico exacto, la cuota, la cuota mínima de valor y un stake razonable (1.0 a 1.2 U).
4. Si el partido es equilibrado sin ventaja matemática evidente, responde "hay_valor": false.

Responde ÚNICAMENTE en JSON con este esquema:
{{
  "hay_valor": true,
  "mercado": "Combo / Totales de Equipo / Béisbol F5 / Ambos Anotan / Spread / Totales / Prop",
  "pick": "...",
  "cuota_playdoit_decimal": 1.95,
  "cuota_playdoit_american": "-105",
  "cuota_minima_decimal": 1.85,
  "cuota_minima_american": "-118",
  "stake": 1.0,
  "significado_simple": "Explicación breve de qué debe ocurrir en el juego para ganar (ej. 'Gana si hay 2 goles o menos en total')",
  "ruta_playdoit": [
    "Entra a Playdoit > Sección Deportes > {event['sport_name']}",
    "Busca la liga: {event.get('champ_name')}",
    "Partido: {event['name']}",
    "Abre la pestaña 'Todas' o la sub-pestaña correspondiente",
    "Selecciona la cuota indicada"
  ],
  "justificacion_tactica": "...",
  "es_apto_parlay": false
}}"""

    models_to_try = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    for model_name in models_to_try:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "Eres un auditor cuantitativo de apuestas deportivas. Responde estrictamente en JSON válido."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                print(f"⚠️ Rate limit en {model_name}, probando respaldo...")
                continue
            print(f"❌ Error consultando Groq ({model_name}) para {event['name']}: {e}")
            break
    return None


def run_multisport_cadence_cycle(hours_ahead: int = 12) -> List[Dict[str, Any]]:
    """Ciclo completo de escaneo multideporte, evaluación y despacho a Telegram."""
    now_cdmx = datetime.now(MEXICO_TZ)
    print("\n" + "=" * 80)
    print("🌮 REY TACO PICKS — CICLO MULTIDEPORTE 24/7 (PLAYDOIT + GROQ)")
    print(f"🕒 Hora CDMX: {now_cdmx.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    session = get_altenar_session()
    history = _load_history()

    # 1. Descubrir eventos próximos
    print(f"\n🔍 Buscando partidos en Playdoit para las próximas {hours_ahead} horas...")
    discovered = discover_upcoming_multisport_events(session, hours_ahead=hours_ahead)

    total_discovered = sum(len(evs) for evs in discovered.values())
    print(f"📊 Total partidos descubiertos: {total_discovered}")
    for sid, evs in discovered.items():
        meta = SPORT_METADATA[sid]
        print(f"   {meta['icon']} {meta['name']}: {len(evs)} partidos")

    dispatched_picks = []

    # Contextos conocidos de ground truth
    known_contexts = {
        "16551508": "NFL Monday Night Football: Chicago Bears sin su QB titular Caleb Williams (isquiotibiales) ni Tyson Bagent (conmoción). Juega el 3er string Case Keenum sin ritmo. Eagles con Jalen Hurts sano y defensa completa.",
        "16955446": "UEFA Nations League: Kylian Mbappé fuera por lesión de rodilla ante Turquía. Francia pierde su principal referente goleador. Mercado castigó Over 2.5 en 1.52 erróneamente.",
        "16943078": "UEFA Nations League: Turquía en casa es incisiva y concede espacios. Duelo de transiciones rápidas con Italia.",
    }

    # 2. Limpiar historial de más de 24 horas para mantenerlo fresco
    cutoff_iso = (now_cdmx - timedelta(hours=24)).isoformat()
    history = {k: v for k, v in history.items() if v.get("evaluated_at", "") > cutoff_iso}

    MAX_PICKS_PER_WINDOW = 5

    # 3. Evaluar eventos pendientes por deporte
    for sid, evs in discovered.items():
        if len(dispatched_picks) >= MAX_PICKS_PER_WINDOW:
            print(f"✅ Cupo máximo de {MAX_PICKS_PER_WINDOW} picks por ventana de 12 horas alcanzado.")
            break
        meta = SPORT_METADATA[sid]
        sorted_evs = sorted(evs, key=lambda x: x["time_cdmx"])
        # Filtrar los que aún no han sido evaluados en las últimas 24 horas
        candidates = [ev for ev in sorted_evs if ev["id"] not in history][:6]

        if not candidates:
            print(f"ℹ️ {meta['icon']} {meta['name']}: Todos los partidos del bloque ({len(evs)}) ya fueron evaluados.")
            continue

        for ev in candidates:
            eid = ev["id"]

            print(f"\n📈 Extrayendo mercados profundos para {meta['icon']} {ev['name']} ({ev['champ_name']})...")
            detail_url = f"https://sb2frontend-altenar2.biahosted.com/api/widget/GetEventDetails?culture=es-ES&timezoneOffset=0&integration=playdoit2&deviceType=1&numFormat=en-GB&countryCode=MX&eventId={eid}&showNonBoosts=false"
            
            try:
                res = session.get(detail_url, timeout=20)
                if res.status_code != 200:
                    print(f"⚠️ No se pudo obtener detalle de {eid}: {res.status_code}")
                    continue
                enriched = extract_all_enriched_markets(res.json())
            except Exception as e:
                print(f"⚠️ Error obteniendo detalle de {eid}: {e}")
                continue

            condensed = condense_markets_for_audit(enriched)
            if not condensed:
                print(f"⚠️ Sin cuotas principales para {ev['name']}.")
                continue

            extra_ctx = known_contexts.get(eid, "")
            print(f"🧠 Consultando auditoría a Groq (openai/gpt-oss-120b)...")
            audit = audit_with_groq(ev, condensed, extra_context=extra_ctx)

            if not audit or not audit.get("hay_valor"):
                print(f"⚖️ Groq determinó que no hay valor significativo en {ev['name']}.")
                history[eid] = {"status": "no_value", "evaluated_at": now_cdmx.isoformat()}
                _save_history(history)
                continue

            # Construir boleto interactivo
            sport_code = meta.get("code", "RT")
            ticket_id = f"RT-{now_cdmx.strftime('%Y%m%d')}-{sport_code}-{eid[-4:]}"
            home_t, away_t = parse_teams(ev["name"])
            
            sport_key = "nba" if sid == 67 else ("mlb" if sid == 76 else ("nfl" if sid == 75 else "futbol"))
            hour_cdmx = int(ev["time_cdmx"].split(":")[0]) if ":" in ev["time_cdmx"] else 12
            block_name = "tarde" if hour_cdmx >= 11 else "madrugada"

            pick_payload = {
                "ticket_id": ticket_id,
                "event_id": eid,
                "sport": sport_key,
                "sport_icon": meta["icon"],
                "home_team": home_t,
                "away_team": away_t,
                "match": ev["name"],
                "league": f"{meta['icon']} {ev['champ_name']}",
                "time": f"{ev['time_cdmx']} CDMX",
                "start_time_utc": ev.get("datetime_utc"),
                "market_name": audit.get("mercado", "Mercado Principal"),
                "pick": audit["pick"],
                "market_odds_decimal": audit["cuota_playdoit_decimal"],
                "market_odds_american": audit["cuota_playdoit_american"],
                "minimum_odds_decimal": audit["cuota_minima_decimal"],
                "minimum_odds_american": audit["cuota_minima_american"],
                "stake_units": min(float(audit.get("stake", 1.0)), 1.0),
                "meaning": audit.get("significado_simple", ""),
                "playdoit_path": audit.get("ruta_playdoit", [
                    f"Abre Playdoit > {meta['name']}",
                    f"Liga: {ev['champ_name']}",
                    f"Partido: {ev['name']}",
                    f"Selección: {audit['pick']}"
                ]),
                "analysis_type": "situational",
                "reasoning": audit.get("justificacion_tactica", "Ventaja matemática y situacional detectada por Groq en Playdoit."),
                "status": "active",
                "is_jewel": True,
                "is_sniper": True,
                "block": block_name
            }

            print(f"📢 Despachando propuesta a Telegram: {ticket_id} ({audit['pick']})...")
            dispatch_interactive_pick(pick_payload)
            dispatched_picks.append(pick_payload)

            history[eid] = {
                "status": "dispatched",
                "ticket_id": ticket_id,
                "pick": audit["pick"],
                "evaluated_at": now_cdmx.isoformat(),
            }
            _save_history(history)
            time.sleep(1)

    # Guardar picks activos en JSON para la Mini App fusionando con los existentes
    active_picks_file = REPO_ROOT / "data" / "active_private_picks.json"
    active_picks_file.parent.mkdir(parents=True, exist_ok=True)
    
    existing_active = []
    if active_picks_file.exists():
        try:
            existing_active = json.loads(active_picks_file.read_text(encoding="utf-8"))
        except Exception:
            existing_active = []

    # Insertar los nuevos al principio si no están repetidos
    known_eids = {p.get("event_id") for p in existing_active if p.get("event_id")}
    known_tids = {p.get("ticket_id") for p in existing_active if p.get("ticket_id")}
    for p in dispatched_picks:
        if p.get("ticket_id") not in known_tids and p.get("event_id") not in known_eids:
            existing_active.insert(0, p)
            known_tids.add(p.get("ticket_id"))
            known_eids.add(p.get("event_id"))

    # Filtrar rigurosamente solo juegos que aún no han empezado (o empezaron hace menos de 10 min)
    now_cdmx = datetime.now(MEXICO_TZ)
    upcoming_active = []
    import re
    for p in existing_active:
        st_utc = p.get("start_time_utc")
        if st_utc:
            try:
                game_utc = datetime.fromisoformat(st_utc.replace("Z", "+00:00"))
                if (game_utc - datetime.now(timezone.utc)).total_seconds() < -600:
                    continue
                upcoming_active.append(p)
                continue
            except Exception:
                pass
        
        # Fallback a parseo de hora CDMX
        t_str = str(p.get("time") or "")
        m = re.search(r"(\d{1,2}):(\d{2})", t_str)
        if m:
            h, mins = int(m.group(1)), int(m.group(2))
            game_dt = now_cdmx.replace(hour=h, minute=mins, second=0, microsecond=0)
            m_date = re.search(r"RT-(\d{4})(\d{2})(\d{2})", str(p.get("ticket_id") or ""))
            if m_date:
                try:
                    game_dt = game_dt.replace(year=int(m_date.group(1)), month=int(m_date.group(2)), day=int(m_date.group(3)))
                except Exception:
                    pass
            if (game_dt - now_cdmx).total_seconds() < -600:
                continue
        upcoming_active.append(p)

    existing_active = upcoming_active

    # REGLA ESTRICTA: Mantener EXACTAMENTE máximo 5 picks por ventana de 12 horas
    existing_active = existing_active[:5]
    active_picks_file.write_text(json.dumps(existing_active, indent=2, ensure_ascii=False), encoding="utf-8")

    # Actualizar copias locales en dist y frontend/public
    for target_dir in [REPO_ROOT / "dist", REPO_ROOT / "frontend" / "public"]:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / "active_private_picks.json").write_text(json.dumps(existing_active, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # Sincronizar automáticamente con Cloudflare R2 para la Mini App
    try:
        from scripts.sync_picks_r2 import upload_active_picks_to_r2
        upload_active_picks_to_r2(active_picks_file)
    except Exception as e:
        print(f"⚠️ Error subiendo picks a R2: {e}")

    # Enviar tarjeta consolidada antispam a Telegram
    if dispatched_picks and ADMIN_CHAT_ID:
        summary_text = f"""🌮 <b>REY TACO — NUEVOS PICKS EN TU MINI APP</b> 👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
Se auditaron y aprobaron <b>{len(dispatched_picks)} oportunidades de valor</b> en Playdoit para las próximas horas:

"""
        for p in dispatched_picks:
            match_title = f"{p.get('home_team')} vs. {p.get('away_team')}" if p.get('home_team') and p.get('away_team') else p.get('match', '')
            summary_text += f"• {p.get('league')} | <b>{match_title}</b>:\n  👉 <b>{p.get('pick')}</b> @ <code>{p.get('market_odds_american')}</code> ({p.get('time')} CDMX)\n"
            if p.get('meaning'):
                summary_text += f"  <i>💡 {p.get('meaning')}</i>\n"

        summary_text += """━━━━━━━━━━━━━━━━━━━━━━━━━━
Toca el botón abajo para ver las <b>rutas exactas paso a paso</b> y registrarlos sin perderte 👇"""

        telegram_api_call("sendMessage", {
            "chat_id": ADMIN_CHAT_ID,
            "text": summary_text,
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "📱 Abrir Panel de Picks Privados", "web_app": {"url": "https://reytacopicks.com/mini-app.html?v=2"}}
                    ]
                ]
            }
        })

    print(f"\n🏁 Ciclo completado. {len(dispatched_picks)} nuevas jugadas despachadas a Telegram.")
    return dispatched_picks


if __name__ == "__main__":
    run_multisport_cadence_cycle(hours_ahead=12)

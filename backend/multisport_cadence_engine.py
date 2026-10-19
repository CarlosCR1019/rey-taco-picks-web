"""
backend/multisport_cadence_engine.py
====================================
Motor de Evaluación y Despacho Multideporte 24/7 para Rey Taco Picks:
- Deportes Cubiertos: Fútbol (66), Fútbol Americano NFL Profesional (75 - NCAA Prohibido), Béisbol MLB (76), Baloncesto NBA/Euroliga (67).
- Extracción de Cuotas Reales Playdoit Altenar API (Moneyline, Spreads/Handicaps, Totales, Córners, BTTS).
- Auditoría Táctica con Groq (openai/gpt-oss-120b).
- Despacho Interactivo con Botón [ ❌ Descartar Jugada ] al Telegram de Carlos.
- Control estricto de deduplicación persistente (data/dispatched_events_history.json).
"""

from __future__ import annotations

import os
import sys
import json
import re
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
from backend.live_grounded_context import fetch_live_event_context
from backend.interactive_telegram_dispatcher import (
    dispatch_interactive_pick,
    telegram_api_call,
    ADMIN_CHAT_ID,
    FREE_CHANNEL_ID,
    VIP_CHANNEL_ID,
)
from backend.pick_tracker import validate_pick_against_market, record_pick, refresh_closing_prices, team_in_text, norm
from backend.pick_settlement import settle_pending, build_report

MEXICO_TZ = ZoneInfo("America/Mexico_City")
HISTORY_FILE = REPO_ROOT / "data" / "dispatched_events_history.json"

SPORT_METADATA = {
    66: {"name": "Fútbol", "icon": "⚽", "code": "FUT", "cadence_hours": 4},
    75: {"name": "Fútbol Americano", "icon": "🏈", "code": "NFL", "cadence_hours": 6},
    67: {"name": "Baloncesto", "icon": "🏀", "code": "NBA", "cadence_hours": 4},
    68: {"name": "Tenis", "icon": "🎾", "code": "TEN", "cadence_hours": 4},
}


TIER1_LEAGUE_KEYWORDS = [
    # Baloncesto Élite
    "nba", "euroliga", "euroleague", "wnba", "champions league", "acb", "liga endesa",
    # Fútbol Americano (Exclusivamente NFL Profesional)
    "nfl",
    # Fútbol Tier-1 y Tier-2
    "liga mx", "expansión mx", "expansion mx", "champions", "europa league", "conference league",
    "premier league", "laliga", "la liga", "serie a", "bundesliga", "ligue 1", "mls",
    "libertadores", "sudamericana", "primera a", "liga profesional argentina",
    "brasileirao", "eredivisie", "primeira liga", "copa del rey", "fa cup", "nations league",
    # Fútbol Japón (J-League y Copas)
    "liga j", "j-league", "j.league", "j1", "j2", "copa del emperador"
]

BANNED_LEAGUE_KEYWORDS = [
    # Prohibición Total Béisbol (Suspendido institucionalmente por ROI negativo)
    "mlb", "npb", "kbo", "lmb", "béisbol", "baseball",
    # Prohibición Total NCAA / Deporte Colegial (Orden Institucional Directa)
    "ncaa", "ncaaf", "ncaab", "college", "colegial", "universitario", "universitaria", "fcs",
    # Divisiones inferiores y no profesionales
    "sub-19", "sub 19", "u19", "sub-20", "u20", "sub-21", "u21", "sub-22", "sub 22", "u22", "sub-23", "sub 23", "u23",
    "reserves", "reserva", "reserve", "(res.)", "res.",
    "amateur", "division 2", "division 3", "division 4", "regional", "youth", "juvenil",
    "islandia", "honduras", "nicaragua", "guatemala", "mongolia", "bangladesh", "oman",
    "vietnam", "tercera", "promocional", "mizoram", "cymru", "women", "femenil", "(f)",
    "saudi", "al-ahli", "neom", "al qadsiah", "lummen", "namur"
]


def is_whitelisted_championship(champ_name: str, sport_id: int) -> bool:
    if not champ_name:
        return False
    c_lower = champ_name.lower()
    if any(b in c_lower for b in BANNED_LEAGUE_KEYWORDS):
        return False
    if sport_id in (70, 76):
        # Béisbol suspendido institucionalmente (MLB, LMB, NPB, KBO vetados)
        return False
    if sport_id == 67:
        return any(k in c_lower for k in ["nba", "euroliga", "euroleague", "wnba", "acb", "endesa", "champions"])
    if sport_id == 66:
        return any(k in c_lower for k in TIER1_LEAGUE_KEYWORDS)
    if sport_id == 75:
        # Única y exclusivamente NFL Profesional. Cero colegial.
        return "nfl" in c_lower and not any(k in c_lower for k in ["ncaa", "college", "colegial", "fcs"])
    if sport_id == 68:
        tier1_tennis = [
            "atp", "wta", "grand slam", "australia", "roland garros", "wimbledon",
            "us open", "estados unidos", "shanghái", "shanghai", "pekín", "beijing",
            "wuhan", "davis cup", "masters", "finals", "francia", "abierto"
        ]
        banned_tennis = [
            "utr", "itf", "m15", "w15", "m25", "w25", "w35", "w50", "w75", "w100",
            "challenger", "dobles", "doubles", "mixto", "mixed"
        ]
        if any(k in c_lower for k in tier1_tennis):
            return not any(b in c_lower for b in banned_tennis)
        return False
    return False



def parse_teams(name: str) -> tuple[str, str]:
    """Extrae de manera segura el equipo local y visitante (home, away)."""
    if " @ " in name:
        parts = name.split(" @ ", 1)
        return parts[1].strip(), parts[0].strip()  # In US format (Away @ Home), returns (home, away)
    for delimiter in (" vs. ", " vs ", " - "):
        if delimiter in name:
            parts = name.split(delimiter, 1)
            return parts[0].strip(), parts[1].strip()  # home, away
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


class FallbackSession:
    """Sesión Altenar: intenta el proxy residencial y, si falla (proxy caído), cae a conexión directa.

    El proxy (Tailscale -> teléfono/PC) puede estar apagado; antes eso se veía como
    '0 partidos' y no llegaba ningún pick sin ninguna alerta.
    """

    def __init__(self) -> None:
        proxy = os.getenv("SOCKS_PROXY", "socks5h://127.0.0.1:1055") if os.path.exists("/root") else None
        self._proxied = requests.Session(impersonate="chrome", proxy=proxy) if proxy else None
        self._direct = requests.Session(impersonate="chrome")
        self.proxy_ok = True
        self.used_fallback = False

    def get(self, url: str, **kwargs: Any):
        if self._proxied is not None and self.proxy_ok:
            try:
                return self._proxied.get(url, **kwargs)
            except Exception as e:
                print(f"⚠️ Proxy residencial caído ({str(e)[:80]}). Cambiando a conexión directa.")
                self.proxy_ok = False
        self.used_fallback = self.used_fallback or self._proxied is not None
        return self._direct.get(url, **kwargs)


def get_altenar_session() -> FallbackSession:
    return FallbackSession()


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
                        ev_name = ev.get("name") or ""
                        ev_name_lower = ev_name.lower()
                        if any(b in ev_name_lower for b in ["(res.)", "res.", "reserva", "reserve", "(f)", "women", "femenil"]):
                            continue
                        if sid == 68 and "/" in ev_name:
                            # Veto estricto a Tenis de Dobles (los dobles siempre llevan '/' entre compañeros)
                            continue
                        champ_name = (champs.get(ev.get("champId")) or {}).get("name") or ev.get("champ", {}).get("name") or "Liga"
                        if not is_whitelisted_championship(champ_name, sid):
                            continue
                        sdate_str = ev.get("startDate")
                        if not sdate_str:
                            continue
                        try:
                            ev_utc = datetime.fromisoformat(sdate_str.replace("Z", "+00:00"))
                            if now_utc + timedelta(minutes=45) <= ev_utc <= max_utc:
                                ev_cdmx = ev_utc.astimezone(MEXICO_TZ)
                                venue_value = ev.get("stadium") or ev.get("venueName") or ev.get("venue") or ""
                                if isinstance(venue_value, dict):
                                    venue_value = venue_value.get("name") or venue_value.get("stadium") or ""
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
                                    "stadium": str(venue_value).strip(),
                                    "datetime_utc": ev_utc.isoformat(),
                                })
                        except Exception:
                            continue
            except Exception:
                continue

    return discovered


def extract_deep_props_markets(event_id: str, session: Any) -> List[Dict[str, Any]]:
    """Extrae todos los mercados y selecciones planas para un evento de Altenar (usado por Reto Escalera)."""
    detail_url = f"https://sb2frontend-altenar2.biahosted.com/api/widget/GetEventDetails?culture=es-ES&timezoneOffset=0&integration=playdoit2&deviceType=1&numFormat=en-GB&countryCode=MX&eventId={event_id}&showNonBoosts=false"
    try:
        res = session.get(detail_url, timeout=15)
        if res.status_code != 200:
            return []
        raw = res.json()
        enriched = extract_all_enriched_markets(raw)
        flat_list = []
        cats = enriched.get("market_categories", {})
        for cat_name, mkt_list in cats.items():
            for m in mkt_list:
                m_name = m.get("market_name", cat_name)
                for s in m.get("selections", []):
                    flat_list.append({
                        "market_name": m_name,
                        "selection_name": s.get("name", ""),
                        "decimal_odds": s.get("price_decimal", 0.0),
                        "american_odds": s.get("price_american", "+100"),
                    })
                if m.get("over"):
                    flat_list.append({
                        "market_name": f"{m_name} Más de {m.get('line', '')}",
                        "selection_name": f"Over {m.get('line', '')}",
                        "decimal_odds": m["over"].get("price_decimal", 0.0),
                        "american_odds": m["over"].get("price_american", "+100"),
                    })
                if m.get("under"):
                    flat_list.append({
                        "market_name": f"{m_name} Menos de {m.get('line', '')}",
                        "selection_name": f"Under {m.get('line', '')}",
                        "decimal_odds": m["under"].get("price_decimal", 0.0),
                        "american_odds": m["under"].get("price_american", "+100"),
                    })
        return flat_list
    except Exception:
        return []


def condense_markets_for_audit(enriched: Dict[str, Any], sport_id: int = 0) -> str:
    """
    Condensa las cuotas más líquidas de la sección 'Todas' en texto legible para Groq,
    priorizando estrictamente los mercados ganadores comprobados por deporte:
    - NBA (67) / NFL (75): Moneyline (2 vías) y Spreads con Colchón.
    - Tenis Singles (68): Exclusivamente Moneyline (Ganador directo 2 vías, 73.3% WR).
    - Fútbol (66): Exclusivamente mercados con colchón anti-empate: Hándicap Asiático / Spreads (+0 Empate No Acción, +0.5, +1.0), Doble Oportunidad (1X, X2), y Córners. 1X2 plano prohibido.
    """
    lines = []
    cat = enriched.get("market_categories", {})

    # Para Deportes con Spreads / Hándicaps (Fútbol, NBA, NFL)
    spread_lines = []
    if sport_id != 68:  # En Tenis se excluyen hándicaps de juegos por alta varianza
        for s in cat.get("spreads", [])[:3]:
            selections = s.get("selections", [])
            balanced_sels = [sel for sel in selections if 1.75 <= float(sel.get('price_decimal', 0)) <= 2.45]
            target_sels = balanced_sels if balanced_sels else [sel for sel in selections if 1.70 <= float(sel.get('price_decimal', 0)) <= 2.45]
            for sel in target_sels[:6]:
                spread_lines.append(f"Spread / Hándicap con Colchón [{s.get('scope')}]: {sel['name']} @ {sel['price_decimal']} ({sel['price_american']})")

    # 1. Moneyline (EXCLUSIVAMENTE en deportes de 2 vías: NBA 67, NFL 75, Tenis 68; NUNCA en Fútbol 66)
    if sport_id in (67, 68, 75):
        for m in cat.get("moneyline", [])[:1]:
            valid_sels = [
                s for s in m.get("selections", [])
                if float(s.get('price_decimal', 0)) >= 1.75
                and str(s.get("name", "")).strip().lower() != "empate"
            ]
            sels_to_show = valid_sels if valid_sels else m.get("selections", [])
            sel_str = ", ".join([f"{s['name']}: {s['price_decimal']} ({s['price_american']})" for s in sels_to_show])
            if sel_str:
                lines.append(f"Moneyline / Ganador Directo (2 vías) [{m.get('market_name')}]: {sel_str}")

    # 2. Spreads / Hándicaps con Colchón
    lines.extend(spread_lines)

    # 3. Doble Oportunidad (Fútbol 66 élite únicamente)
    if sport_id in (66, 0):
        for dc in cat.get("double_chance", [])[:1]:
            valid_sels = [s for s in dc.get("selections", []) if 1.75 <= float(s.get('price_decimal', 0)) <= 2.45]
            if valid_sels:
                dc_str = ", ".join([f"{s['name']} ({s.get('code', 'DC')}): {s['price_decimal']} ({s['price_american']})" for s in valid_sels])
                lines.append(f"Doble Oportunidad con Colchón [{dc.get('market_name', '1X / X2')}]: {dc_str}")

    # 4. Córners (Fútbol 66 élite únicamente: volumen por bandas independiente del marcador)
    if sport_id in (66, 0):
        for c in cat.get("corners", [])[:2]:
            if c.get("over") and c.get("under"):
                over_price = float(c['over'].get('price_decimal', 0))
                if 1.75 <= over_price <= 2.45:
                    lines.append(f"Córners de Fútbol [{c.get('line')}]: Más @ {c['over']['price_decimal']} ({c['over']['price_american']})")

    return "\n".join(lines)


def audit_with_groq(event: Dict[str, Any], market_lines_str: str, extra_context: str = "") -> Optional[Dict[str, Any]]:
    """Ejecuta la auditoría táctica con Groq openai/gpt-oss-120b."""
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        print("⚠️ GROQ_API_KEY no configurado.")
        return None

    client = Groq(api_key=groq_api_key)

    home_t, away_t = parse_teams(event.get('name', ''))
    prompt = f"""Eres el Consejo Cuantitativo y Táctico de Rey Taco Picks.
Audita el siguiente partido en Playdoit para la jornada de hoy.

EVENTO:
• Partido: {event['name']}
• Equipo Local: {home_t}
• Equipo Visitante: {away_t}
• Deporte: {event['sport_name']} ({event.get('champ_name')})
• Horario: {event['time_cdmx']} CDMX

CONTEXTO SITUACIONAL Y REPORTES DE LESIONES/NOTICIAS:
{extra_context if extra_context else "Análisis situacional de calendario, localía y dinámica de equipos."}

CUOTAS REALES EN PLAYDOIT (INCLUYENDO SECCIÓN COMPLETA 'TODAS'):
{market_lines_str}

Instrucciones:
1. Evalúa si existe una ineficiencia o desajuste de precio real en Playdoit basándote ESTRICTAMENTE en las métricas deportivas y el contexto fáctico reciente.
2. REGLAS INSTITUCIONALES RIGUROSAS DE CONTROL DE VARIANZA Y ALTA RENTABILIDAD:
   - EN BALONCESTO NBA (2 VÍAS), NFL (2 VÍAS) Y TENIS SINGLES ATP/WTA (2 VÍAS):
     * MERCADO GANADOR (MONEYLINE DIRECTO DE 2 VÍAS): Con 81.8% de acierto en deportes sin empate y 73.3% en Tenis Singles, si identificas ventaja clara en momio 1.75 a 2.35, prioriza Moneyline Directo o Spread con Colchón (+3.5 a +8.5 / -2.5 a -6.5 en NBA/NFL).
     * EN TENIS: Selecciona EXCLUSIVAMENTE Ganador Directo (Moneyline). Prohibido seleccionar Hándicap de juegos o Totales de juegos en Tenis.
   - EN FÚTBOL (DEPORTE DE 3 VÍAS CON ALTO RIESGO DE EMPATE):
     * VETO TOTAL A 1X2 DIRECTO: Está terminantemente prohibido seleccionar ganador local o visitante simple en 1X2 tradicional en fútbol (causante del 60% de fallos por empates 1-1 / 0-0).
     * MERCADOS PERMITIDOS EN FÚTBOL (OBLIGATORIO ELEGIR SOLO ENTRE ESTOS):
       1) Hándicap Asiático / Spread con Colchón (+0 Empate No Acción, +0.5, +1.0, +1.5) donde un empate no pierde el dinero.
       2) Empate No Acción (Draw No Bet) donde el empate devuelve el 100% de la apuesta.
       3) Doble Oportunidad (1X, X2).
       4) Tiros de Esquina (Córners Over 8.5 / 9.5).
     * Si en fútbol no hay mercados con colchón disponibles con cuota de valor, responde "hay_valor": false.
   - PROHIBIDO ABSOLUTO E IRREVOCABLE:
     * TOTALES GENERALES (OVER/UNDER DE PARTIDO COMPLETO): Prohibido pronosticar altas/bajas de puntos, goles, juegos o carreras.
     * BÉISBOL (MLB, KBO, NPB), NCAA / DEPORTES COLEGIALES Y TENIS DE DOBLES: Prohibición total institucional. Responde "hay_valor": false inmediatamente.
     * CUOTAS FUERA DEL SWEET SPOT: La cuota DEBE estar estrictamente en el SWEET SPOT +EV entre 1.75 y 2.45 (PROHIBIDO cuotas menores a 1.75).
     * COMBOS CRUZADOS (ej. '1x2 y total', 'Gana y Ambos Anotan'): Prohibidos 100%. Solo selecciones de 1 SOLA CONDICIÓN PURA.
3. Si existe una selección de alto valor, define el pronóstico exacto, la cuota, la cuota mínima de valor y un stake razonable (1.0 U).
4. Si el partido es equilibrado sin ventaja matemática evidente, responde "hay_valor": false.

Responde ÚNICAMENTE en JSON con este esquema:
{{
  "hay_valor": true,
  "mercado": "Moneyline / Spread con Colchón / Córners",
  "pick": "...",
  "cuota_playdoit_decimal": 1.95,
  "cuota_playdoit_american": "-105",
  "cuota_minima_decimal": 1.85,
  "cuota_minima_american": "-118",
  "stake": 1.0,
  "significado_simple": "Explicación breve de qué debe ocurrir en el juego para ganar (ej. 'Gana si Denver gana el partido directo')",
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


def get_current_cadence_window(dt: datetime) -> tuple[str, str, int]:
    """
    Retorna (window_key, window_label, hours_until_window_end)
    4 Ventanas fijas de 6 horas CDMX:
    - 00:00 - 06:00: madrugada (KBO, NPB, Asia)
    - 06:00 - 12:00: manana (Fútbol Europeo Élite)
    - 12:00 - 18:00: tarde (NFL Domingo, MLB Tarde, Fútbol Liga MX/Sudamérica)
    - 18:00 - 24:00: noche (NFL Sunday Night, Liga MX Noche, MLB Noche, NBA)
    """
    h = dt.hour
    if 0 <= h < 6:
        return "madrugada", "MADRUGADA (00:00 - 06:00 CDMX)", max(1, 6 - h)
    elif 6 <= h < 12:
        return "manana", "MAÑANA (06:00 - 12:00 CDMX)", max(1, 12 - h)
    elif 12 <= h < 18:
        return "tarde", "TARDE (12:00 - 18:00 CDMX)", max(1, 18 - h)
    else:
        return "noche", "NOCHE (18:00 - 24:00 CDMX)", max(1, 24 - h)


def run_multisport_cadence_cycle(hours_ahead: Optional[int] = None, force_dispatch: bool = False) -> List[Dict[str, Any]]:
    """Ciclo de escaneo multideporte por ventana de 6 horas y despacho consolidado a Telegram."""
    now_cdmx = datetime.now(MEXICO_TZ)
    window_key, window_label, window_hours_left = get_current_cadence_window(now_cdmx)
    actual_hours = hours_ahead if hours_ahead is not None else min(6, window_hours_left + 1)

    print("\n" + "=" * 80)
    print(f"🌮 REY TACO PICKS — CICLO MULTIDEPORTE 24/7 ({window_label})")
    print(f"🕒 Hora CDMX: {now_cdmx.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    session = get_altenar_session()
    history = _load_history()

    # GUARDIA INSTITUCIONAL: VENTANA MADRUGADA DESHABILITADA (Ligas asiáticas KBO/NPB vetadas)
    if window_key == "madrugada":
        print(f"ℹ️ La ventana 'madrugada' (00:00 - 06:00 CDMX) ha sido deshabilitada institucionalmente para proteger el bankroll.")
        return []

    window_dispatch_key = f"window_{now_cdmx.strftime('%Y%m%d')}_{window_key}"
    if window_dispatch_key in history and not force_dispatch:
        print(f"ℹ️ La ventana '{window_label}' ya fue despachada hoy a las {history[window_dispatch_key].get('dispatched_at')}.")
        return []

    # 1. Descubrir eventos próximos dentro de la ventana de 6 horas
    print(f"\n🔍 Buscando partidos en Playdoit para la ventana {window_label} (próximas {actual_hours} horas)...")
    discovered = discover_upcoming_multisport_events(session, hours_ahead=actual_hours)

    if not discovered:
        # Fallo real de conexión con Playdoit (no es 'sin partidos'): avisar una vez por ventana
        alert_key = f"alert_discovery_{now_cdmx.strftime('%Y%m%d')}_{window_key}"
        print("🚨 No se pudo consultar Playdoit (ni por proxy ni directo).")
        if alert_key not in history and ADMIN_CHAT_ID:
            telegram_api_call("sendMessage", {
                "chat_id": ADMIN_CHAT_ID,
                "text": f"🚨 Rey Taco: no pude consultar Playdoit en la ventana {window_label}. "
                        f"Sigo reintentando cada 10 min. Si ves esto seguido, hay que revisar el servidor.",
            })
            history[alert_key] = {"evaluated_at": now_cdmx.isoformat()}
            _save_history(history)
        return []

    if session.used_fallback:
        print("ℹ️ Playdoit consultado por conexión directa (proxy residencial caído).")

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

    # MODO FRANCOTIRADOR (SNIPER MODE): Máximo 2 picks por ventana y 1 por deporte
    # Meta cuantitativa: 0 a 1 fallo al día (2 a 3 selecciones estelares de máxima certeza)
    MAX_PICKS_PER_WINDOW = 2
    MAX_PICKS_PER_SPORT = 1

    # 3. Construir lista intercalada (Round-Robin) entre los deportes activos
    # para garantizar equidad multideporte y evitar que el fútbol agote el cupo antes de evaluar NBA y NFL
    candidates_by_sport = {}
    for sid, evs in discovered.items():
        sorted_evs = sorted(evs, key=lambda x: x["time_cdmx"])
        candidates_by_sport[sid] = [ev for ev in sorted_evs if ev["id"] not in history]

    max_depth = max((len(ev_list) for ev_list in candidates_by_sport.values()), default=0)
    interleaved_candidates = []
    # Rotación balanceada de alta rentabilidad: NBA (67, +22.7% ROI), NFL (75, +15.9% ROI), Fútbol (66), Tenis (68)
    sport_order = [67, 75, 66, 68]
    for depth in range(max_depth):
        for sid in sport_order:
            if sid in candidates_by_sport and depth < len(candidates_by_sport[sid]):
                interleaved_candidates.append((sid, candidates_by_sport[sid][depth]))

    sport_pick_counts = {66: 0, 67: 0, 68: 0, 75: 0}

    print(f"🔄 Candidatos intercalados para evaluación ({len(interleaved_candidates)} en total):")
    for s_id, cand in interleaved_candidates:
        print(f"   - {SPORT_METADATA[s_id]['icon']} {cand['name']} ({cand['champ_name']}) @ {cand['time_cdmx']}")

    for sid, ev in interleaved_candidates:
        if len(dispatched_picks) >= MAX_PICKS_PER_WINDOW:
            print(f"✅ Cupo máximo de {MAX_PICKS_PER_WINDOW} picks para la ventana {window_label} alcanzado.")
            break
        if sport_pick_counts[sid] >= MAX_PICKS_PER_SPORT:
            continue

        meta = SPORT_METADATA[sid]
        eid = ev["id"]

        # VETO PROGRAMÁTICO ABSOLUTO: NCAA / DEPORTES COLEGIALES Y TENIS DE DOBLES
        ev_text = f"{ev.get('champ_name', '')} {ev.get('name', '')}".lower()
        if any(kw in ev_text for kw in ["ncaa", "ncaaf", "ncaab", "college", "colegial", "fcs"]):
            print(f"🚫 [VETO NCAA] Descartado {ev['name']}: Deporte colegial/NCAA vetado 100%.")
            history[eid] = {"status": "ncaa_banned", "evaluated_at": now_cdmx.isoformat()}
            _save_history(history)
            continue
        if sid == 68 and ("/" in ev.get("name", "") or "dobles" in ev_text or "doubles" in ev_text):
            print(f"🚫 [VETO TENIS DOBLES] Descartado {ev['name']}: Solo se permite Tenis Singles ATP/WTA.")
            history[eid] = {"status": "tennis_doubles_banned", "evaluated_at": now_cdmx.isoformat()}
            _save_history(history)
            continue

        print(f"\n📈 Extrayendo mercados profundos para {meta['icon']} {ev['name']} ({ev['champ_name']})...")
        detail_url = f"https://sb2frontend-altenar2.biahosted.com/api/widget/GetEventDetails?culture=es-ES&timezoneOffset=0&integration=playdoit2&deviceType=1&numFormat=en-GB&countryCode=MX&eventId={eid}&showNonBoosts=false"
        
        try:
            res = session.get(detail_url, timeout=20)
            if res.status_code != 200:
                print(f"⚠️ No se pudo obtener detalle de {eid}: {res.status_code}")
                continue
            raw_detail = res.json()
            enriched = extract_all_enriched_markets(raw_detail)
        except Exception as e:
            print(f"⚠️ Error obteniendo detalle de {eid}: {e}")
            continue

        condensed = condense_markets_for_audit(enriched, sport_id=sid)
        if not condensed:
            print(f"⚠️ Sin cuotas principales para {ev['name']}.")
            continue

        extra_ctx = known_contexts.get(eid, "")
        if not extra_ctx:
            print(f"🌐 Obteniendo contexto deportivo en vivo (Gemini + Search Grounding) para {ev['name']}...")
            extra_ctx = fetch_live_event_context(ev)
            if extra_ctx:
                print(f"   Contexto factual obtenido:\n   {extra_ctx[:180]}...")

        print(f"🧠 Consultando auditoría a Groq (openai/gpt-oss-120b)...")
        audit = audit_with_groq(ev, condensed, extra_context=extra_ctx)

        if not audit or not audit.get("hay_valor"):
            print(f"⚖️ Groq determinó que no hay valor significativo en {ev['name']}.")
            history[eid] = {"status": "no_value", "evaluated_at": now_cdmx.isoformat()}
            _save_history(history)
            continue

        # GUARDIA PROGRAMÁTICA: BÉISBOL ASIÁTICO (NPB y KBO)
        c_name_lower = (ev.get("champ_name") or "").lower()
        home_t, away_t = parse_teams(ev["name"])
        if "npb" in c_name_lower or "japon" in c_name_lower or "nippon" in c_name_lower:
            pick_str = norm(audit.get("pick", ""))
            hcp_match = re.search(r"-\s*1\.5", pick_str)
            if hcp_match and team_in_text(home_t, pick_str) >= team_in_text(away_t, pick_str):
                print(f"🚫 [GUARDIA NPB] Descartado para {ev['name']}: '{audit.get('pick')}' es Runline Local -1.5 en NPB (trampa de baja de la 9na).")
                history[eid] = {"status": "npb_home_runline_rejected", "evaluated_at": now_cdmx.isoformat()}
                _save_history(history)
                continue

        # PRICE GATE: Validar selección contra el mercado real de Altenar
        validated = validate_pick_against_market(
            audit, raw_detail, ev["name"], home_t, away_t,
            sport=("nba" if sid == 67 else ("tennis" if sid == 68 else ("nfl" if sid == 75 else "futbol"))))
        if not validated:
            print(f"🚫 [PRICE GATE] Descartado para {ev['name']}: '{audit.get('pick')}' no superó el filtro de mercado.")
            history[eid] = {"status": "price_gate_rejected", "evaluated_at": now_cdmx.isoformat()}
            _save_history(history)
            continue

        # GUARDIA PROGRAMÁTICA INSTITUCIONAL: VETO A MERCADOS COMBO Y TOTALES GENERALES
        alt_mkt_norm = norm(str(validated.get("altenar_market", "")) + " " + str(validated.get("altenar_selection", "")))
        mkt_norm = norm(str(audit.get("mercado", "")) + " " + str(audit.get("pick", "")) + " " + alt_mkt_norm)
        if any(k in alt_mkt_norm for k in ["y total", "& total", "y ambos", "primero gol", "primer gol"]):
            print(f"🚫 [VETO COMBO] Descartado para {ev['name']}: Mercado compuesto '{validated.get('altenar_market')}' prohibido.")
            history[eid] = {"status": "combo_market_banned", "evaluated_at": now_cdmx.isoformat()}
            _save_history(history)
            continue
        is_corner_prop = any(k in mkt_norm for k in ["esquina", "corner"])
        is_total_market = any(k in mkt_norm for k in ["total", "mas de", "menos de", "over", "under"])
        if is_total_market and not is_corner_prop:
            print(f"🚫 [VETO TOTALES] Descartado para {ev['name']}: '{audit.get('pick')}' es Totales Over/Under (acumulan 70% de pérdidas del bot).")
            history[eid] = {"status": "totals_banned", "evaluated_at": now_cdmx.isoformat()}
            _save_history(history)
            continue

        # GUARDIA PROGRAMÁTICA INSTITUCIONAL: VETO A 1X2 PLANO EN FÚTBOL (BLINDAJE ANTI-VARIANZA)
        if sid == 66:
            alt_mkt_lower = norm(str(validated.get("altenar_market", "")))
            alt_sel_lower = norm(str(validated.get("altenar_selection", "")))
            is_safe_soccer_mkt = any(k in alt_mkt_lower for k in [
                "handicap", "spread", "asiatico", "linea",
                "empate apuesta no valida", "draw no bet", "sin empate", "apuesta no valida", "no valida",
                "doble oportunidad", "doble", "esquina", "corner"
            ]) or any(k in alt_sel_lower for k in [
                "(0)", "(+0)", "(-0)", "(+", "(-", "empate no accion", "draw no bet", "1x", "x2", "12"
            ])
            is_plain_1x2 = any(k in alt_mkt_lower for k in [
                "1x2", "resultado final", "ganador del partido", "resultado del partido", "ganador"
            ]) and not is_safe_soccer_mkt
            if is_plain_1x2:
                print(f"🚫 [VETO FÚTBOL 1X2] Descartado para {ev['name']}: '{audit.get('pick')}' es 1X2 plano sin protección de empate.")
                history[eid] = {"status": "football_plain_1x2_banned", "evaluated_at": now_cdmx.isoformat()}
                _save_history(history)
                continue

        # GUARDIA PROGRAMÁTICA INSTITUCIONAL: CUOTA MÍNIMA SWEET SPOT (1.75 A 2.45)
        price_val = float(validated.get("price", 0.0))
        if price_val < 1.75 or price_val > 2.45:
            print(f"🚫 [VETO CUOTA] Descartado para {ev['name']}: Cuota {price_val} fuera del Sweet Spot institucional (1.75 - 2.45).")
            history[eid] = {"status": "odds_sweet_spot_rejected", "evaluated_at": now_cdmx.isoformat()}
            _save_history(history)
            continue

        # Anclar cuota real y mercado certificado de Altenar
        audit["cuota_playdoit_decimal"] = validated["price"]
        audit["cuota_playdoit_american"] = validated["american"]

        # Construir boleto interactivo
        sport_code = meta.get("code", "RT")
        ticket_id = f"RT-{now_cdmx.strftime('%Y%m%d')}-{sport_code}-{eid[-4:]}"
        
        sport_key = "nba" if sid == 67 else ("tennis" if sid == 68 else ("nfl" if sid == 75 else "futbol"))
        hour_cdmx = int(ev["time_cdmx"].split(":")[0]) if ":" in ev["time_cdmx"] else 12
        block_name = "tarde" if hour_cdmx >= 11 else "madrugada"

        # Stake Defensivo para Mañana / Madrugada / Ligas Asiáticas / Experimental Fútbol Japonés
        c_name_lower = (ev.get("champ_name") or "").lower()
        is_japan_soccer = any(k in c_name_lower for k in ["liga j", "j-league", "j.league", "copa del emperador"]) and sid == 66
        is_asian_league = any(k in c_name_lower for k in ["npb", "kbo", "japon", "corea", "nippon"])
        if is_japan_soccer:
            assigned_stake = 0.1  # Stake Experimental de Calibración
        elif window_key in ("madrugada", "manana") or block_name == "madrugada" or is_asian_league:
            assigned_stake = 0.5  # Stake Defensivo en mañana/madrugada; 1.0 U concentrado en Tarde y Noche (+22% ROI)
        else:
            assigned_stake = min(float(audit.get("stake", 1.0)), 1.0)

        from backend.ladder_challenge_engine import format_explicit_pick
        explicit_pick_val = format_explicit_pick(
            str(audit.get("pick", "")),
            str(validated.get("altenar_market") or audit.get("mercado") or "")
        )

        pick_payload = {
            "ticket_id": ticket_id,
            "event_id": eid,
            "odd_id": validated.get("odd_id"),
            "sport": sport_key,
            "sport_icon": meta["icon"],
            "home_team": home_t,
            "away_team": away_t,
            "match": ev["name"],
            "league": f"{meta['icon']} {ev['champ_name']}",
            "time": f"{ev['time_cdmx']} CDMX",
            "date_cdmx": ev.get("date_cdmx"),
            "stadium": ev.get("stadium", ""),
            "start_time_utc": ev.get("datetime_utc"),
            "market_name": validated.get("altenar_market") or audit.get("mercado", "Mercado Principal"),
            "altenar_market": validated.get("altenar_market"),
            "altenar_selection": validated.get("altenar_selection"),
            "market_margin": validated.get("market_margin"),
            "pick": explicit_pick_val,
            "market_odds_decimal": audit["cuota_playdoit_decimal"],
            "market_odds_american": audit["cuota_playdoit_american"],
            "minimum_odds_decimal": audit["cuota_minima_decimal"],
            "minimum_odds_american": audit["cuota_minima_american"],
            "stake_units": assigned_stake,
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

        # Registrar en el tracking auditable persistente (Fase 1)
        record_pick(pick_payload, window_key=window_key)

        # REGLA ANTISPAM: NO despachar mensajes individuales con botones interactivos por cada pick
        dispatched_picks.append(pick_payload)
        sport_pick_counts[sid] = sport_pick_counts.get(sid, 0) + 1

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

    # REGLA ESTRICTA MODO FRANCOTIRADOR: Mantener EXACTAMENTE máximo 3 picks activos en simultáneo
    existing_active = existing_active[:3]
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

    # Enviar tarjeta consolidada antispam a Telegram (1 SOLO MENSAJE POR VENTANA)
    if dispatched_picks and ADMIN_CHAT_ID:
        import html

        # Construir Parlay de Oro de 2 selecciones si hay al menos 2 picks
        parlay_block = ""
        if len(dispatched_picks) >= 2:
            p1, p2 = dispatched_picks[0], dispatched_picks[1]
            try:
                c_dec = round(float(p1.get("market_odds_decimal", 1.8)) * float(p2.get("market_odds_decimal", 1.8)), 2)
                c_ame = decimal_to_american(c_dec)
                p_stake = min(float(p1.get("stake_units", 1.0)), float(p2.get("stake_units", 1.0)))
                p_stake_txt = f"{p_stake} U (Defensivo Control de Varianza)" if p_stake <= 0.5 else "1.0 U"
                parlay_block = f"""🎯 <b>PARLAY DE ORO RECOMENDADO ({c_ame}):</b>
1. {p1['sport_icon']} {html.escape(p1['match'])} ➔ <b>{html.escape(p1['pick'])}</b> ({p1['time']})
2. {p2['sport_icon']} {html.escape(p2['match'])} ➔ <b>{html.escape(p2['pick'])}</b> ({p2['time']})
📊 <i>Cuota Combinada: <code>{c_ame}</code> ({c_dec}) • Stake: {p_stake_txt}</i>

"""
            except Exception:
                pass

        summary_text = f"""🌮 <b>REY TACO — CARTELERA OFICIAL DE LA {window_label}</b> 👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
{parlay_block}💎 <b>JOYAS INDIVIDUALES APROBADAS ({len(dispatched_picks)}):</b>
"""
        for idx, p in enumerate(dispatched_picks, 1):
            match_title = f"{p.get('home_team')} vs. {p.get('away_team')}" if p.get('home_team') and p.get('away_team') else p.get('match', '')
            summary_text += f"\n<b>{idx}. {p.get('sport_icon')} {html.escape(match_title)}</b> [{html.escape(p.get('league', ''))}]\n"
            summary_text += f"   👉 <b>{html.escape(p.get('pick', ''))}</b> @ <code>{p.get('market_odds_american', '')}</code> ({p.get('time', '')})\n"
            stake_val = float(p.get('stake_units', 1.0))
            if stake_val <= 0.15:
                stake_txt = f"{stake_val} U (Experimental Calibración J-League)"
            elif stake_val <= 0.5:
                stake_txt = f"{stake_val} U (Defensivo Control de Varianza)"
            else:
                stake_txt = f"{stake_val} U"
            summary_text += f"   ⚖️ <i>Stake Sugerido: {stake_txt}</i>\n"
            if p.get('meaning'):
                summary_text += f"   <i>💡 {html.escape(p.get('meaning'))}</i>\n"
            if p.get('playdoit_path'):
                clean_path = " ➔ ".join(str(s) for s in p.get('playdoit_path')[:3])
                summary_text += f"   🗺️ <i>Ruta: {html.escape(clean_path)}</i>\n"

        summary_text += """\n━━━━━━━━━━━━━━━━━━━━━━━━━━
📱 <i>Cartelera interactiva lista en tu Mini App de Telegram</i> 👇"""

        res = telegram_api_call("sendMessage", {
            "chat_id": ADMIN_CHAT_ID,
            "text": summary_text,
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {"text": "📱 Abrir Mini App Rey Taco", "web_app": {"url": "https://reytacopicks.com/mini-app.html?v=3"}}
                    ]
                ]
            }
        })
        if not res or not res.get("ok"):
            print(f"⚠️ Telegram sendMessage HTML falló: {res}. Reintentando sin parse_mode...")
            plain_text = (summary_text.replace("<b>", "").replace("</b>", "")
                                     .replace("<i>", "").replace("</i>", "")
                                     .replace("<code>", "").replace("</code>", ""))
            telegram_api_call("sendMessage", {
                "chat_id": ADMIN_CHAT_ID,
                "text": plain_text,
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {"text": "📱 Abrir Mini App Rey Taco", "web_app": {"url": "https://reytacopicks.com/mini-app.html?v=3"}}
                        ]
                    ]
                }
            })

        # Enviar también la cartelera completa al chat privado de la novia de Carlos (8996443105)
        try:
            from backend.interactive_telegram_dispatcher import resolve_girlfriend_chat_id
            gf_chat_id = resolve_girlfriend_chat_id()
            if gf_chat_id and str(gf_chat_id) != str(ADMIN_CHAT_ID):
                telegram_api_call("sendMessage", {
                    "chat_id": gf_chat_id,
                    "text": summary_text,
                    "parse_mode": "HTML",
                    "reply_markup": {
                        "inline_keyboard": [
                            [
                                {"text": "📱 Abrir Mini App Rey Taco", "web_app": {"url": "https://reytacopicks.com/mini-app.html?v=3"}}
                            ]
                        ]
                    }
                })
                print(f"💝 ✅ Cartelera de ventana enviada al privado de tu novia ({gf_chat_id}).")
        except Exception as e_gf:
            print(f"⚠️ Error enviando cartelera al privado de tu novia: {e_gf}")

        # Publicación a Canales Públicos (VIP y FREE) para ventanas diurnas/vespertinas (mañana, tarde, noche)
        is_daytime_window = window_key in ["manana", "tarde", "noche"]

        # Canal VIP: Cartelera Oficial Completa (Joyas + Parlay de Oro)
        if VIP_CHANNEL_ID and is_daytime_window:
            vip_text = summary_text.replace(
                f"CARTELERA OFICIAL DE LA {window_label}",
                f"CARTELERA VIP EXCLUSIVA — {window_label.upper()}"
            )
            telegram_api_call("sendMessage", {
                "chat_id": VIP_CHANNEL_ID,
                "text": vip_text,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {"text": "👑 Abrir Mini App VIP", "url": "https://reytacopicks.com/mini-app.html?v=13&mode=vip"}
                        ]
                    ]
                }
            })

        # Canal Free: Joya Gratuita Oficial + Teasers VIP Bloqueados + Embudo hacia Canal VIP
        if FREE_CHANNEL_ID and is_daytime_window and dispatched_picks:
            free_pick = dispatched_picks[0]
            free_pick["is_free_pick"] = True
            m_title = f"{free_pick.get('home_team')} vs. {free_pick.get('away_team')}" if free_pick.get('home_team') and free_pick.get('away_team') else free_pick.get('match', '')
            c_path = " ➔ ".join(str(s) for s in free_pick.get('playdoit_path', [])[:3])
            short_analysis = ""
            if free_pick.get('reasoning'):
                short_analysis = free_pick.get('reasoning').split('.')[0] + '.'

            vip_teasers_block = ""
            if len(dispatched_picks) > 1:
                vip_teasers_block = "\n🔒 <b>JOYAS EXCLUSIVAS EN JUEGO (SOLO CANAL VIP):</b>\n"
                for v_idx, vp in enumerate(dispatched_picks[1:], 2):
                    vp["is_free_pick"] = False
                    v_lg = html.escape(str(vp.get("league", "Deporte")))
                    v_od = html.escape(str(vp.get("market_odds_american", "")))
                    v_tm = html.escape(str(vp.get("time", "")))
                    vip_teasers_block += f"   • <b>Pick VIP #{v_idx}:</b> {v_lg} | ██████████ @ <code>{v_od}</code> ({v_tm})\n"

            free_text = f"""🌮 <b>REY TACO PICKS — JOYA GRATUITA OFICIAL</b> 👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 <b>SELECCIÓN ABIERTA ({window_label.upper()}):</b>

{free_pick.get('sport_icon')} <b>{html.escape(m_title)}</b> [{html.escape(free_pick.get('league', ''))}]
👉 <b>{html.escape(free_pick.get('pick', ''))}</b> @ <code>{free_pick.get('market_odds_american', '')}</code> ({free_pick.get('time', '')})
"""
            if free_pick.get('meaning'):
                free_text += f"💡 <i>{html.escape(free_pick.get('meaning'))}</i>\n"
            if c_path:
                free_text += f"🗺️ <i>Ruta: {html.escape(c_path)}</i>\n"
            if short_analysis:
                free_text += f"📊 <i>Análisis: {html.escape(short_analysis)}</i>\n"

            free_text += f"""{vip_teasers_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 <b>Récord Auditado:</b> <code>20W-7L (+52.6% ROI)</code> en Moneyline | <code>21W-12L (+28.1% ROI)</code> en NBA
👑 <b>Desbloquea los Picks VIP y el Parlay de Oro ($129/sem o $349/mes) 👇</b>"""

            telegram_api_call("sendMessage", {
                "chat_id": FREE_CHANNEL_ID,
                "text": free_text,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {"text": "👑 Desbloquear VIP ($129 / $349)", "url": "https://reytacopicks.com/#vip"},
                            {"text": "📱 Abrir Mini App", "url": "https://reytacopicks.com/mini-app.html?v=3"}
                        ],
                        [
                            {"text": "💬 Entrar al Canal VIP", "url": "https://t.me/+mmqMU1Gxqy04ZGMx"}
                        ]
                    ]
                }
            })

            # Iniciar solicitud de foto (individual o Parlay) con auto-publicación de Tarjeta Oficial en 5 min
            try:
                from backend.interactive_telegram_dispatcher import dispatch_interactive_pick
                dispatch_interactive_pick(free_pick, timeout_seconds=300)
            except Exception as e:
                print(f"⚠️ Error iniciando despacho interactivo con tarjeta: {e}")

        # Marcar la ventana como despachada en history para nunca duplicar
        history[window_dispatch_key] = {
            "dispatched_at": now_cdmx.isoformat(),
            "count": len(dispatched_picks),
            "picks": [p["ticket_id"] for p in dispatched_picks]
        }
        _save_history(history)

        # AUTO-REEL IA: Producir y despachar automáticamente el Reel con voz IA + Google Flow para el Pick #1 DESPUÉS de enviar la cartelera de texto
        try:
            from backend.auto_reel_producer import produce_and_dispatch_ai_reel
            produce_and_dispatch_ai_reel(dispatched_picks[0], mode="pick", send_telegram=True, publish_social=True)
        except Exception as e_reel:
            print(f"⚠️ [AUTO-REEL] No se pudo generar Reel de ventana: {e_reel}")

    # Aviso de ventana vacía: una sola vez, en la última hora de la ventana, para que el silencio nunca sea ambiguo
    notice_key = f"notice_empty_{now_cdmx.strftime('%Y%m%d')}_{window_key}"
    dispatched_key = f"window_{now_cdmx.strftime('%Y%m%d')}_{window_key}"
    if (not dispatched_picks and window_hours_left <= 1 and ADMIN_CHAT_ID
            and notice_key not in history and dispatched_key not in history):
        telegram_api_call("sendMessage", {
            "chat_id": ADMIN_CHAT_ID,
            "text": f"🌮 Rey Taco — {window_label}\n\nSin jugadas con valor en esta ventana. "
                    f"Los filtros de precio descartaron todo lo disponible. No es un fallo: preferimos no mandar "
                    f"nada a mandar una jugada con mala cuota. Las jugadas previas siguen en la Mini App.",
        })
        history[notice_key] = {"evaluated_at": now_cdmx.isoformat()}
        _save_history(history)

    print(f"\n🏁 Ciclo completado. {len(dispatched_picks)} nuevas jugadas despachadas a Telegram.")
    return dispatched_picks


if __name__ == "__main__":
    run_multisport_cadence_cycle(hours_ahead=12)

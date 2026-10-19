"""
backend/ladder_challenge_engine.py
==================================
Módulo especializado para el Reto Escalera Semanal de Rey Taco Picks.

REGLAS DE NEGOCIO ESTRICTAS (Autorizadas por Carlos):
1. Frecuencia: 1 vez por semana durante el fin de semana (Viernes a Domingo).
2. Ventana Horaria Estricta: Únicamente de 12:00 PM a 9:00 PM (12:00 - 21:00) CDMX.
   - Horarios de máxima afluencia y atención en redes sociales.
3. Rango de Momios Reales: 1.70 a 1.95 (Playdoit México).
4. Estructura de 3 Pasos Independientes:
   - Paso 1 (Viernes): Entrada $300 MXN ➔ Cobro ~$550 MXN (Abierto en Redes y Telegram).
   - Paso 2 (Sábado): Entrada ~$550 MXN ➔ Cobro ~$1,000 MXN (Gratis en Telegram Free).
   - Paso 3 (Domingo): Entrada ~$1,000 MXN ➔ Cobro ~$1,900 MXN (Exclusivo VIP).
5. No Sustituye Picks del VIP: Se registra como un slot adicional para no restar
   los 3 a 5 picks regulares diarios.
6. Deportes Permitidos: NFL (cero colegial), NBA, Tenis y Fútbol Élite (MLB suspendido institucionalmente).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backend.multisport_cadence_engine import (
    MEXICO_TZ,
    SPORT_METADATA,
    BANNED_LEAGUE_KEYWORDS,
    discover_upcoming_multisport_events,
    get_altenar_session,
)
from backend.interactive_telegram_dispatcher import telegram_api_call

LOGGER = logging.getLogger("reytaco.ladder")
REPO_ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = REPO_ROOT / "data" / "ladder_challenge_history.json"
ACTIVE_PICKS_FILE = REPO_ROOT / "data" / "active_private_picks.json"

TELEGRAM_FREE_LINK = "https://t.me/ReyTacoPicksFree"
WEBSITE_VIP_LINK = "https://reytacopicks.com"
CARLOS_ADMIN_CHAT_ID = "5912533842"


def strip_accents(text: Any) -> str:
    """Elimina acentos y tildes para evitar '?' en videos y plataformas."""
    if text is None:
        return ""
    s = str(text)
    replacements = {
        "ñ": "n", "Ñ": "N",
        "á": "a", "Á": "A",
        "é": "e", "É": "E",
        "í": "i", "Í": "I",
        "ó": "o", "Ó": "O",
        "ú": "u", "Ú": "U",
        "ü": "u", "Ü": "U",
        "¿": "", "¡": "",
        "“": '"', "”": '"', "‘": "'", "’": "'",
        "—": "-", "–": "-",
    }
    for k, v in replacements.items():
        s = s.replace(k, v)
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


# Parámetros del Reto (Paso 1 siempre gratis, Pasos 2 y 3 siempre exclusivos VIP)
LADDER_CONFIG = {
    4: {"step": 1, "entry": 300, "target": 555, "day_name": "Viernes", "channel": "public"},
    5: {"step": 2, "entry": 555, "target": 1000, "day_name": "Sabado", "channel": "vip_only"},
    6: {"step": 3, "entry": 1000, "target": 1900, "day_name": "Domingo", "channel": "vip_only"},
}
LADDER_PRIORITY_SPORTS = [67, 68, 75, 66]  # NBA, Tenis, NFL, Fútbol (MLB 70 eliminado)


def is_in_ladder_window(dt: datetime) -> bool:
    """Verifica si la hora CDMX está dentro de la ventana de alta afluencia (12:00 PM a 9:00 PM)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_cdmx = dt.astimezone(MEXICO_TZ)
    # 12:00 PM a 9:00 PM (12 a 20 inclusive, es decir antes de las 21:00)
    return 12 <= dt_cdmx.hour < 21


def is_ladder_day(dt: datetime) -> bool:
    """Verifica si el día corresponde a la escalera de fin de semana (Viernes=4, Sábado=5, Domingo=6)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_cdmx = dt.astimezone(MEXICO_TZ)
    return dt_cdmx.weekday() in LADDER_CONFIG


def get_current_ladder_step_config(dt: datetime) -> Optional[Dict[str, Any]]:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_cdmx = dt.astimezone(MEXICO_TZ)
    return LADDER_CONFIG.get(dt_cdmx.weekday())


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


def format_explicit_pick(selection_name: str, market_name: str = "") -> str:
    """
    Garantiza que la selección nunca sea ambigua y esté 100% libre de acentos
    (ej. convierte 'Menos de 11.5' en 'Menos de 11.5 Tiros de Esquina (Corners)', o agrega el mercado).
    """
    sel = (selection_name or "").strip()
    mkt = (market_name or "").strip()
    if not sel:
        return strip_accents(mkt or "Seleccion Oficial")

    sel_low = sel.lower()
    mkt_low = mkt.lower()

    # 1. Mercados Over / Under (Más de / Menos de)
    if any(k in sel_low for k in ("más de", "mas de", "menos de", "over", "under")):
        has_unit = any(
            u in sel_low
            for u in (
                "esquina", "córner", "corner", "gol", "punto", "carrera",
                "juego", "set", "tarjeta", "remate", "tiro", "yarda",
                "rebote", "triple", "asistencia", "hit", "strikeout",
            )
        )
        if not has_unit:
            if any(c in mkt_low for c in ("esquina", "corner", "córner")):
                return strip_accents(f"{sel} Tiros de Esquina (Corners)")
            if "gol" in mkt_low:
                return strip_accents(f"{sel} Goles")
            if any(p in mkt_low for p in ("punto", "point")):
                return strip_accents(f"{sel} Puntos")
            if any(r in mkt_low for r in ("carrera", "run")):
                return strip_accents(f"{sel} Carreras")
            if any(j in mkt_low for j in ("juego", "game")):
                return strip_accents(f"{sel} Juegos")
            if "set" in mkt_low:
                return strip_accents(f"{sel} Sets")
            if any(t in mkt_low for t in ("tarjeta", "card")):
                return strip_accents(f"{sel} Tarjetas")
            if any(rm in mkt_low for rm in ("remate", "tiro a puerta")):
                return strip_accents(f"{sel} Remates a Puerta")
            if mkt:
                return strip_accents(f"{sel} ({mkt})")

    # 2. Empate No Acción / Draw No Bet
    if any(k in mkt_low for k in ("no válida", "no valida", "draw no bet", "empate no")):
        if "empate" not in sel_low and "acción" not in sel_low and "accion" not in sel_low:
            return strip_accents(f"{sel} (Empate No Accion)")

    # 3. Hándicap / Spread
    if any(k in mkt_low for k in ("hándicap", "handicap", "spread")):
        if "(0)" in sel or "(+0)" in sel or "(-0)" in sel:
            if not any(e in sel_low for e in ("empate", "draw no bet", "dnb")):
                return strip_accents(f"{sel} - Handicap 0 (Empate No Accion)")
        elif not any(h in sel_low for h in ("hándicap", "handicap", "spread", "puntos", "goles", "draw no bet", "dnb", "empate")):
            return strip_accents(f"{sel} (Handicap)")

    # 4. Ganador / Moneyline cuando solo viene el nombre del equipo/jugador
    if any(k in mkt_low for k in ("1x2", "ganador", "moneyline")):
        if not any(g in sel_low for g in ("gana", "ganador", "moneyline", "directo", "empate")):
            return strip_accents(f"{sel} a Ganar")

    return strip_accents(sel)


def evaluate_and_dispatch_ladder_step(force: bool = False, step_override: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Evalúa y despacha el paso correspondiente del Reto Escalera si está en ventana activa.

    REGLA DE NEGOCIO ESTRICTA (Autorizada por Carlos):
    - Viernes (weekday 4): Paso 1 (Entrada $300 ➔ Cobro ~$555, Abierto en Telegram Free y Redes).
    - Sábado  (weekday 5): Paso 2 (Entrada $555 ➔ Cobro ~$1,000, Exclusivo VIP / Privado).
    - Domingo (weekday 6): Paso 3 (Entrada $1,000 ➔ Cobro ~$1,900, Exclusivo VIP / Privado).
    
    Sábado y Domingo NUNCA deben repetir el Paso 1 ni publicarse abiertos en canales gratuitos.
    """
    now_cdmx = datetime.now(MEXICO_TZ)
    
    # 1. Guardia de día de la semana
    if not is_ladder_day(now_cdmx) and not force and step_override is None:
        LOGGER.info("Reto Escalera: Hoy no es dia de escalera (activo Viernes a Domingo).")
        return None

    # 2. Guardia de ventana de alta afluencia (12:00 PM a 9:00 PM CDMX)
    if not is_in_ladder_window(now_cdmx) and not force:
        LOGGER.info(
            "Reto Escalera: Fuera de la ventana autorizada de alta afluencia (12:00 PM - 9:00 PM CDMX). "
            "Hora actual: %s", now_cdmx.strftime("%H:%M:%S")
        )
        return None

    # Asignación estricta según el día de la semana o override manual
    weekday = now_cdmx.weekday()
    if step_override in (1, 2, 3):
        step = step_override
        cfg = next((c for c in LADDER_CONFIG.values() if c["step"] == step), LADDER_CONFIG[4])
        day_name = cfg["day_name"]
        channel_type = cfg["channel"]
        entry_monto = cfg["entry"]
        target_monto = cfg["target"]
    elif weekday in LADDER_CONFIG:
        cfg = LADDER_CONFIG[weekday]
        step = cfg["step"]
        day_name = cfg["day_name"]
        channel_type = cfg["channel"]
        entry_monto = cfg["entry"]
        target_monto = cfg["target"]
    else:
        # Fallback si se fuerza en un día fuera del fin de semana (Lunes a Jueves)
        step = 1
        day_name = "Viernes"
        channel_type = "public"
        entry_monto = 300
        target_monto = 555

    retry_label = ""
    today_iso = now_cdmx.strftime("%Y-%m-%d")
    history = _load_history()

    step_key = f"ladder_{today_iso}_step_{step}"
    if step_key in history and not force:
        LOGGER.info("Reto Escalera: El Paso %d de hoy ya fue despachado previamente.", step)
        return None

    LOGGER.info("🪜 Reto Escalera: Buscando seleccion de alta certeza para el Paso %d (%s)...", step, day_name)

    # 3. Descubrir eventos próximos en Playdoit en la ventana de alta afluencia
    session = get_altenar_session()
    discovered = discover_upcoming_multisport_events(session, hours_ahead=8)
    if not discovered:
        LOGGER.warning("Reto Escalera: No se pudieron consultar eventos de Playdoit.")
        return None

    # 4. Priorizar deportes con mayor Win Rate auditado: NBA (67), Tenis Singles (68), NFL (75), Fútbol Hándicap (66)
    priority_order = LADDER_PRIORITY_SPORTS
    all_events = []
    for sid in priority_order:
        all_events.extend(discovered.get(sid, []))

    candidate = None
    for ev in all_events:
        sid = ev.get("sport_id")
        champ_lower = (ev.get("champ_name") or "").lower()
        ev_name = ev.get("name") or ""
        if any(banned in champ_lower for banned in BANNED_LEAGUE_KEYWORDS):
            continue
        # Vetar Tenis Dobles e ITF/Challenger
        if sid == 68 and ("/" in ev_name or any(k in champ_lower for k in ("dobles", "doubles", "itf", "challenger"))):
            continue

        time_cdmx_str = ev.get("time_cdmx", "")
        if ":" in time_cdmx_str:
            try:
                hour_part = int(time_cdmx_str.split(":")[0])
                if hour_part < 12 or hour_part > 22:
                    continue
            except ValueError:
                pass

        from backend.multisport_cadence_engine import extract_deep_props_markets
        markets = extract_deep_props_markets(ev.get("id"), session)
        if not markets:
            continue

        for mkt in markets:
            dec_odds = float(mkt.get("decimal_odds") or 0.0)
            if not (1.65 <= dec_odds <= 1.92):
                continue
            mkt_name = (mkt.get("market_name") or "").lower()
            sel_name = (mkt.get("selection_name") or "").lower()

            # Prohibir combos y totales generales de goles/puntos (-17.2% ROI)
            if any(b in mkt_name for b in ("y total", "& total", "primero gol", "primer gol", "ambos")):
                continue
            is_total = any(t in mkt_name or t in sel_name for t in ("total", "más de", "mas de", "menos de", "over", "under"))
            is_corner = any(c in mkt_name or c in sel_name for c in ("esquina", "corner"))
            if is_total and not is_corner:
                continue
            if "empate" in sel_name and "no valida" not in mkt_name and "doble" not in mkt_name:
                continue

            # En Fútbol (66), PROHIBIDO 1X2 plano (Ganador de partido simple sin colchón)
            if sid == 66 and any(k in mkt_name for k in ("1x2", "ganador")):
                if not any(k in mkt_name for k in ("no válida", "no valida", "draw no bet", "empate no", "hándicap", "handicap")):
                    continue

            # Mercados de alta efectividad auditada (Moneyline 2 vías 74.1% WR, Hándicap con colchón, DNB, Doble Oportunidad, Córners)
            is_high_wr = (
                (sid in (67, 68, 75) and any(k in mkt_name for k in ("ganador", "moneyline", "hándicap", "handicap", "spread")))
                or (sid == 66 and any(k in mkt_name for k in ("no válida", "no valida", "draw no bet", "empate no", "hándicap", "handicap", "esquina", "corner", "doble oportunidad", "doble")))
            )
            if is_high_wr:
                candidate = {
                    "event": ev,
                    "market": mkt,
                    "decimal_odds": dec_odds,
                    "american_odds": mkt.get("american_odds", "-120"),
                }
                break
        if candidate:
            break

    if not candidate:
        LOGGER.info("Reto Escalera: No se encontró una jugada de alta efectividad (1.65 - 1.92) en esta revisión.")
        return None

    ev = candidate["event"]
    mkt = candidate["market"]
    odds_dec = candidate["decimal_odds"]
    odds_ame = candidate["american_odds"]
    payout_calc = int(round(entry_monto * odds_dec))

    sid = ev.get("sport_id")
    sport_key = "nba" if sid == 67 else ("tennis" if sid == 68 else ("nfl" if sid == 75 else ("mlb" if sid == 70 else "futbol")))
    sport_icon = SPORT_METADATA.get(sid, {}).get("icon", "🏆")
    parts = [p.strip() for p in (ev.get("name") or "").replace(" vs. ", " vs ").split(" vs ")]
    home_t = parts[0] if len(parts) >= 2 else ev.get("name", "")
    away_t = parts[1] if len(parts) >= 2 else ""

    ticket_id = f"RT-{now_cdmx.strftime('%Y%m%d')}-LADDER-{step:02d}"
    explicit_pick_str = format_explicit_pick(mkt.get("selection_name", ""), mkt.get("market_name", ""))

    ladder_pick = {
        "ticket_id": ticket_id,
        "event_id": str(ev.get("id")),
        "home_team": strip_accents(home_t),
        "away_team": strip_accents(away_t),
        "match": strip_accents(ev.get("name")),
        "league": strip_accents(f"{sport_icon} {ev.get('champ_name')}"),
        "sport": sport_key,
        "sport_icon": sport_icon,
        "date_cdmx": today_iso,
        "time": f"{ev.get('time_cdmx')} CDMX",
        "time_cdmx": ev.get("time_cdmx"),
        "start_time_utc": ev.get("start_date_utc") or ev.get("datetime_utc"),
        "pick": explicit_pick_str,
        "market_name": strip_accents(mkt.get("market_name")),
        "altenar_market": strip_accents(mkt.get("market_name")),
        "altenar_selection": strip_accents(mkt.get("selection_name")),
        "market_odds_decimal": odds_dec,
        "market_odds_american": odds_ame,
        "minimum_odds_decimal": round(max(1.55, odds_dec - 0.06), 2),
        "minimum_odds_american": odds_ame,
        "stake_units": 1.0,
        "status": "active",
        "is_free_pick": (step == 1),
        "stadium": "",
        "is_ladder": True,
        "ladder_step": step,
        "ladder_retry_label": retry_label,
        "ladder_entry": entry_monto,
        "ladder_target": target_monto,
        "ladder_payout": payout_calc,
        "dispatched_at": now_cdmx.isoformat(),
    }

    # 5. Registrar en pick_tracking.json para liquidación automática y guardar en active_private_picks.json
    try:
        record_pick(ladder_pick, window_key="tarde")
    except Exception as e:
        LOGGER.warning("No se pudo registrar ladder pick en pick_tracking: %s", e)

    _inject_ladder_pick_to_active(ladder_pick)

    # 6. Despachar mensaje a Telegram (Canales Free, VIP y Admin)
    _notify_telegram_channels(ladder_pick, channel_type)

    # 6.5 AUTO-REEL IA: Generar y enviar automáticamente el Reel con voz IA + Google Flow para el Reto Escalera
    try:
        from backend.auto_reel_producer import produce_and_dispatch_ai_reel
        produce_and_dispatch_ai_reel(ladder_pick, mode="ladder", send_telegram=True, publish_social=True)
    except Exception as e_reel:
        LOGGER.warning("No se pudo generar Reel automático de Reto Escalera: %s", e_reel)

    # 7. Registrar en historial
    history[step_key] = {
        "ticket_id": ticket_id,
        "match": ladder_pick["match"],
        "pick": ladder_pick["pick"],
        "step": step,
        "entry": entry_monto,
        "odds": odds_dec,
        "dispatched_at": now_cdmx.isoformat(),
    }
    _save_history(history)
    LOGGER.info("✅ Reto Escalera Paso %d despachado con éxito: %s (%s)", step, ticket_id, ladder_pick["match"])
    return ladder_pick


def _inject_ladder_pick_to_active(pick: Dict[str, Any]) -> None:
    """Inserta el pick del reto escalera en active_private_picks.json sin duplicar."""
    try:
        picks = []
        if ACTIVE_PICKS_FILE.exists():
            picks = json.loads(ACTIVE_PICKS_FILE.read_text(encoding="utf-8"))

        picks = [p for p in picks if p.get("ticket_id") != pick.get("ticket_id")]
        picks.insert(0, pick)

        ACTIVE_PICKS_FILE.parent.mkdir(parents=True, exist_ok=True)
        ACTIVE_PICKS_FILE.write_text(json.dumps(picks, indent=2, ensure_ascii=False), encoding="utf-8")

        for target_dir in [REPO_ROOT / "dist", REPO_ROOT / "frontend" / "public"]:
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                (target_dir / "active_private_picks.json").write_text(
                    json.dumps(picks, indent=2, ensure_ascii=False), encoding="utf-8"
                )
            except Exception:
                pass
        try:
            from scripts.sync_picks_r2 import upload_active_picks_to_r2
            upload_active_picks_to_r2(ACTIVE_PICKS_FILE)
        except Exception:
            pass
    except Exception as e:
        LOGGER.error("Error al inyectar reto escalera en active_private_picks: %s", e)


def _notify_telegram_channels(pick: Dict[str, Any], channel_type: str) -> None:
    """Envía el formato del Reto Escalera a Admin, Canal Free y Canal VIP según el paso."""
    import html
    from backend.interactive_telegram_dispatcher import FREE_CHANNEL_ID, VIP_CHANNEL_ID, dispatch_interactive_pick

    step = pick["ladder_step"]
    retry_lbl = pick.get("ladder_retry_label", "")
    entry = pick["ladder_entry"]
    payout = pick["ladder_payout"]
    match = html.escape(str(pick["match"]))
    league = html.escape(str(pick.get("league", "")))
    selection = html.escape(str(format_explicit_pick(str(pick.get("pick", "")), str(pick.get("market_name", "")))))
    mkt_name = html.escape(str(pick.get("market_name", "Mercado Oficial")))
    odds = html.escape(str(pick["market_odds_american"]))
    odds_dec = pick.get("market_odds_decimal", 1.80)
    time_str = html.escape(str(pick.get("time_cdmx", "")))

    full_msg = f"""🪜 <b>RETO ESCALERA FIN DE SEMANA • PASO {step} DE 3{retry_lbl}</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 <b>META DEL RETO:</b> <code>$300 MXN ➔ $1,800+ MXN</code>

🏟️ <b>Evento:</b> {match} [{league}]
⏰ <b>Horario:</b> {time_str} CDMX
📌 <b>Mercado Playdoit:</b> {mkt_name}
👉 <b>Pronóstico Exacto:</b> <b>{selection}</b>
📊 <b>Cuota Playdoit:</b> <code>{odds}</code> ({odds_dec})
💵 <b>Inversión Paso {step}:</b> <code>${entry} MXN</code> ➔ <b>Retorno:</b> <code>${payout} MXN</code>

━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 <b>Motor de Alta Efectividad:</b> Basado en mercados de baja varianza (<code>74.1% Win Rate auditado</code>).
👑 <b>El Paso 1 es 100% Gratis • Los Pasos 2 y 3 ($540 ➔ $1,800+ MXN) son exclusivos del Canal VIP:</b>"""

    kb_public = {
        "inline_keyboard": [
            [
                {"text": "👑 Desbloquear Pasos 2 y 3 VIP ($129)", "url": "https://reytacopicks.com/#vip"},
                {"text": "📱 Ver Mini App", "url": "https://reytacopicks.com/mini-app.html?v=3"}
            ]
        ]
    }

    # 1. Siempre enviar al Canal VIP la jugada completa
    if VIP_CHANNEL_ID:
        telegram_api_call("sendMessage", {
            "chat_id": VIP_CHANNEL_ID,
            "text": full_msg,
            "parse_mode": "HTML",
            "reply_markup": kb_public,
        })

    # 1b. Enviar también al chat privado de la novia de Carlos (8996443105)
    try:
        from backend.interactive_telegram_dispatcher import resolve_girlfriend_chat_id
        gf_chat_id = resolve_girlfriend_chat_id()
        if gf_chat_id:
            telegram_api_call("sendMessage", {
                "chat_id": gf_chat_id,
                "text": full_msg,
                "parse_mode": "HTML",
                "reply_markup": kb_public,
            })
    except Exception:
        pass

    # 2. En el Canal Gratuito: SOLO el Paso 1 es abierto; Pasos 2 y 3 bloqueados como Teaser VIP
    if FREE_CHANNEL_ID:
        if step == 1:
            telegram_api_call("sendMessage", {
                "chat_id": FREE_CHANNEL_ID,
                "text": full_msg,
                "parse_mode": "HTML",
                "reply_markup": kb_public,
            })
        else:
            teaser_vip = f"""🔒 <b>RETO ESCALERA • PASO {step} DE 3 EN JUEGO (${entry} ➔ ${payout} MXN)</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 Ya cobramos el Paso 1 gratis y hoy jugamos el <b>Paso {step} por ${payout} MXN</b> (Exclusivo Canal VIP).

🏟️ <b>Liga:</b> {league} | ⏰ <b>Horario:</b> {time_str} CDMX
📊 <b>Cuota Playdoit:</b> <code>{odds}</code> ({odds_dec})
🎯 <b>Selección:</b> 🔒 <b>[EXCLUSIVO MIEMBROS VIP]</b>

👉 <b>Desbloquea los Pasos 2 y 3 del Reto Escalera y toda la cartelera VIP por solo $129 MXN (Pase 7 Días):</b>"""
            telegram_api_call("sendMessage", {
                "chat_id": FREE_CHANNEL_ID,
                "text": teaser_vip,
                "parse_mode": "HTML",
                "reply_markup": kb_public,
            })

    # 3. Enviar a Carlos con solicitud interactiva de foto (individual o Parlay) y auto-tarjeta en 5 min
    try:
        dispatch_interactive_pick(pick, timeout_seconds=300)
    except Exception:
        telegram_api_call("sendMessage", {
            "chat_id": CARLOS_ADMIN_CHAT_ID,
            "text": f"👑 <b>[RETO ESCALERA DISPARADO]</b>\n\n{full_msg}",
            "parse_mode": "HTML",
        })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Despachador del Reto Escalera Rey Taco Picks")
    parser.add_argument("--force", action="store_true", help="Forzar evaluacion ignorando horario y duplicados")
    parser.add_argument("--step", type=int, choices=[1, 2, 3], help="Forzar paso especifico (1, 2 o 3)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    evaluate_and_dispatch_ladder_step(force=args.force, step_override=args.step)


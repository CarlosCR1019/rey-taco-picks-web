"""
backend/interactive_telegram_dispatcher.py
=========================================
Despachador interactivo para Telegram con confirmación previa y fallback de 5 minutos.

Flujo:
1. Envía el pronóstico cuantitativo pre-aprobado al chat privado del Administrador (`TELEGRAM_ADMIN_ID`)
   con botones interactivos:
   - [ ✅ Publicar Ahora ]
   - [ ❌ Descartar Pick ]
2. Si el Administrador hace clic en "Publicar Ahora", se envía de inmediato al canal público
   (`TELEGRAM_FREE_CHANNEL_ID`) y se cancela el temporizador.
3. Si el Administrador hace clic en "Descartar", se anula la publicación y se registra el veto.
4. Si transcurren 5 minutos (300 segundos) sin respuesta, el temporizador en segundo plano
   publica automáticamente el pronóstico al canal público y edita el mensaje del administrador
   notificando: "⏰ Publicado automáticamente tras 5 minutos sin respuesta".
5. Sella el evento `PICK_PUBLISHED` en el Ledger Criptográfico.
"""

import os
import sys
import time
import json
import threading
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Any, Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=REPO_ROOT / ".env")
load_dotenv(dotenv_path=BASE_DIR / ".env")

from backend.audit_ledger import record_pick_published, AUDIT_LEDGER_PATH

MEXICO_TZ = ZoneInfo("America/Mexico_City")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_ID") or os.getenv("TELEGRAM_CHAT_ID")
FREE_CHANNEL_ID = os.getenv("TELEGRAM_FREE_CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL_ID")
VIP_CHANNEL_ID = os.getenv("TELEGRAM_VIP_CHANNEL_ID")

TIMEOUT_SECONDS = 300  # 5 minutos reglamentarios

# Registro en memoria de tickets pendientes
# ticket_id -> {"status": "pending"|"published"|"discarded", "timer": Thread, "admin_msg_id": int, ...}
PENDING_DISPATCHES: Dict[str, Dict[str, Any]] = {}
DISPATCH_LOCK = threading.Lock()


def telegram_api_call(method: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ejecuta una llamada segura a la API de Telegram con timeout y reintentos."""
    if not TELEGRAM_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN no configurado.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            res_body = response.read().decode("utf-8")
            return json.loads(res_body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"❌ Error HTTP Telegram ({method}): {e.code} - {err_body}")
        return None
    except Exception as e:
        print(f"❌ Error de conexión Telegram ({method}): {e}")
        return None


PENDING_PICKS_FILE = REPO_ROOT / "data" / "pending_picks_waiting_photo.json"


def save_pending_pick_waiting_photo(pick: Dict[str, Any]):
    """Guarda un pick en disco esperando obligatoriamente la foto de Playdoit."""
    PENDING_PICKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if PENDING_PICKS_FILE.exists():
        try:
            with open(PENDING_PICKS_FILE, "r", encoding="utf-8") as f:
                current = json.load(f)
        except Exception:
            current = {}
    current[pick["ticket_id"]] = {
        "status": "waiting_photo",
        "pick": pick,
        "created_at": datetime.now(MEXICO_TZ).isoformat()
    }
    with open(PENDING_PICKS_FILE, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)


def get_latest_waiting_pick() -> Optional[Dict[str, Any]]:
    """Obtiene el último pick pendiente que está esperando foto de Playdoit."""
    if not PENDING_PICKS_FILE.exists():
        return None
    try:
        with open(PENDING_PICKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        waiting = [v for v in data.values() if v.get("status") == "waiting_photo"]
        if waiting:
            waiting.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return waiting[0]["pick"]
    except Exception:
        return None
    return None


def mark_pick_photo_received(ticket_id: str, photo_filename: str, is_parlay_ticket: bool = False):
    """Marca que el pick ya recibió su foto de Playdoit (individual o en parlay)."""
    if not PENDING_PICKS_FILE.exists():
        return
    try:
        with open(PENDING_PICKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if ticket_id in data:
            data[ticket_id]["status"] = "photo_received"
            data[ticket_id]["photo_filename"] = photo_filename
            data[ticket_id]["is_parlay_ticket"] = is_parlay_ticket
            data[ticket_id]["received_at"] = datetime.now(MEXICO_TZ).isoformat()
            with open(PENDING_PICKS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error marking pick photo: {e}")


def load_pending_pick_by_id(ticket_id: str) -> Optional[Dict[str, Any]]:
    """Carga un pick pendiente desde disco para compartir estado entre procesos (daemon y listener)."""
    if not PENDING_PICKS_FILE.exists():
        return None
    try:
        with open(PENDING_PICKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(ticket_id)
    except Exception:
        return None


def update_pending_pick_status(ticket_id: str, status: str, extra: Optional[Dict[str, Any]] = None) -> None:
    if not PENDING_PICKS_FILE.exists():
        return
    try:
        with open(PENDING_PICKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if ticket_id in data:
            data[ticket_id]["status"] = status
            if extra:
                data[ticket_id].update(extra)
            with open(PENDING_PICKS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error updating pick status on disk: {e}")


def resolve_team_group_id() -> str:
    """Obtiene el ID del grupo de trabajo con la novia de Carlos (-5369214121)."""
    team_file = REPO_ROOT / "data" / "team_group_id.json"
    if team_file.exists():
        try:
            data = json.loads(team_file.read_text(encoding="utf-8"))
            gid = data.get("team_group_id") or data.get("chat_id")
            if gid:
                return str(gid)
        except Exception:
            pass
    return (
        os.getenv("TIKTOK_EDITORIAL_GROUP_ID")
        or os.getenv("TELEGRAM_TIKTOK_CHAT_ID")
        or "-5369214121"
    )


def resolve_girlfriend_chat_id() -> str:
    """Obtiene el ID del chat privado de la novia de Carlos (Lleny: 8996443105)."""
    team_file = REPO_ROOT / "data" / "team_group_id.json"
    if team_file.exists():
        try:
            data = json.loads(team_file.read_text(encoding="utf-8"))
            gf_id = data.get("user_girlfriend_id")
            if gf_id:
                return str(gf_id)
        except Exception:
            pass
    return os.getenv("TELEGRAM_GIRLFRIEND_CHAT_ID") or "8996443105"


def _get_explicit_pick(pick: Dict[str, Any]) -> str:
    raw_sel = str(pick.get("pick") or pick.get("selection") or "Selección Oficial").strip()
    raw_mkt = str(pick.get("market_name") or pick.get("altenar_market") or pick.get("mercado") or "").strip()
    try:
        from backend.ladder_challenge_engine import format_explicit_pick
        return format_explicit_pick(raw_sel, raw_mkt)
    except Exception:
        return raw_sel


def send_photo_request_email(pick: Dict[str, Any]) -> bool:
    """Envía recordatorio por correo vía Resend a Carlos solicitando la foto del boleto (individual o en parlay)."""
    import html
    resend_key = os.getenv("RESEND_API_KEY", "").strip()
    if not resend_key:
        print("ℹ️ RESEND_API_KEY no configurada; se omite envío de correo.")
        return False

    from_addr = os.getenv("RESEND_FROM_EMAIL", "alertas@reytacopicks.com").strip()
    if "<" not in from_addr:
        from_addr = f"Rey Taco Picks <{from_addr}>"
    email_to = os.getenv("USER_EMAIL") or os.getenv("ADMIN_ALERT_EMAIL") or "carlosds1017@gmail.com"

    ticket_id = str(pick.get("ticket_id", "RT-PICK"))
    match_name = f"{pick.get('home_team', '')} vs {pick.get('away_team', '')}".strip(" vs ") or str(pick.get("match", "Partido"))
    league_str = str(pick.get("league", ""))
    pick_str = _get_explicit_pick(pick)
    odds_ame = str(pick.get("market_odds_american", ""))
    odds_dec = str(pick.get("market_odds_decimal", ""))
    min_odds = str(pick.get("minimum_odds_american") or pick.get("minimum_odds_decimal") or odds_ame)
    time_str = str(pick.get("time", ""))
    path_val = pick.get("playdoit_path")
    if isinstance(path_val, list):
        route_str = " ➔ ".join(str(s) for s in path_val)
    else:
        route_str = str(path_val or "Deportes ➔ Partido ➔ Mercado")

    subject = f"📸 [Rey Taco] Foto de Pick ({ticket_id}): {match_name}"
    text_body = (
        f"Hola Carlos,\n\n"
        f"Se generó una nueva jugada verificada en Rey Taco Picks:\n"
        f"• Ticket ID: {ticket_id}\n"
        f"• Partido: {match_name} ({league_str})\n"
        f"• Selección: {pick_str}\n"
        f"• Cuota Playdoit: {odds_ame} ({odds_dec}) | Mínima: {min_odds}\n"
        f"• Horario: {time_str}\n"
        f"• Ruta Playdoit: {route_str}\n\n"
        f"👉 Si la metiste en Playdoit (sola o combinada dentro de un Parlay), envía la captura de tu boleto al bot de Telegram.\n"
        f"⏰ Si en 5 minutos no subes captura manual, el bot publicará automáticamente con la Tarjeta Oficial generada.\n"
    )

    html_body = f"""
    <div style="font-family: Arial, sans-serif; background-color: #0b132b; color: #f8fafc; padding: 24px; border-radius: 14px; max-width: 600px; margin: 0 auto; border: 2px solid #f59e0b;">
        <h2 style="color: #f59e0b; margin-top: 0;">🌮👑 Rey Taco Picks — Solicitud de Boleto</h2>
        <p style="color: #cbd5e1; font-size: 15px;">Hola <b>Carlos</b>, se acaba de generar una nueva selección oficial. Si la vas a meter sola o combinada en un <b>Parlay</b> en Playdoit, sube tu captura en Telegram:</p>
        <div style="background-color: #162238; padding: 16px; border-radius: 10px; border-left: 4px solid #10b981; margin: 16px 0;">
            <p style="margin: 6px 0;">🎟️ <b>Ticket ID:</b> <code>{html.escape(ticket_id)}</code></p>
            <p style="margin: 6px 0;">🏆 <b>Liga:</b> {html.escape(league_str)}</p>
            <p style="margin: 6px 0;">🏟️ <b>Partido:</b> <b>{html.escape(match_name)}</b></p>
            <p style="margin: 6px 0; font-size: 17px; color: #facc15;">🎯 <b>Pronóstico: {html.escape(pick_str)}</b></p>
            <p style="margin: 6px 0;">📊 <b>Cuota Playdoit:</b> <b>{html.escape(odds_ame)}</b> ({html.escape(odds_dec)}) &nbsp;|&nbsp; 🛡️ <b>Mínima:</b> {html.escape(min_odds)}</p>
            <p style="margin: 6px 0;">⏰ <b>Horario:</b> {html.escape(time_str)}</p>
            <p style="margin: 6px 0; color: #94a3b8; font-size: 13px;">🗺️ <b>Ruta Playdoit:</b> {html.escape(route_str)}</p>
        </div>
        <p style="font-size: 14px; color: #e2e8f0;">
            📸 <b>¿La metiste sola o en Parlay?</b> Envía la foto del boleto al bot de Telegram (puedes tocar <b>[🎰 La metí en Parlay]</b> o mandar la imagen directo).<br><br>
            ⏰ <b>Auto-publicación en 5 min:</b> Si estás ocupado, no te preocupes: en 5 minutos el bot publicará automáticamente con la <b>Tarjeta Oficial 1080x1080</b> y también la enviará al grupo con tu novia.
        </p>
    </div>
    """

    payload = {
        "from": from_addr,
        "to": [email_to],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {resend_key}",
            "Content-Type": "application/json",
            "User-Agent": "resend-python/2.0.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            print(f"📧 ✅ Correo Resend enviado a {email_to} para {ticket_id} (ID: {resp_data.get('id')}).")
            return True
    except urllib.error.HTTPError as e:
        err_txt = e.read().decode("utf-8", errors="ignore")
        print(f"⚠️ Error HTTP Resend ({e.code}): {err_txt}")
        return False
    except Exception as e:
        print(f"⚠️ Error enviando correo por Resend: {e}")
        return False



def render_official_prematch_card(pick: Dict[str, Any]) -> Optional[Path]:
    """Genera una Tarjeta Oficial 1080x1080 en PNG/JPG cuando se publica sin captura manual."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        W, H = 1080, 1080
        im = Image.new("RGB", (W, H), (7, 16, 33))
        draw = ImageDraw.Draw(im)

        def _font(sz: int, bold: bool = False):
            cands = [
                "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
            for fp in cands:
                if os.path.exists(fp):
                    try:
                        return ImageFont.truetype(fp, size=sz)
                    except Exception:
                        pass
            return ImageFont.load_default()

        gold = (245, 158, 11)
        green = (16, 185, 129)
        white = (248, 250, 252)
        yellow = (250, 204, 21)
        slate = (148, 163, 184)

        draw.rounded_rectangle([(28, 28), (W - 28, H - 28)], radius=32, outline=gold, width=4)
        draw.rounded_rectangle([(60, 180), (W - 60, 820)], radius=26, fill=(16, 27, 49), outline=green, width=3)

        draw.text((W // 2, 85), "REY TACO PICKS • CARTELERA VERIFICADA", fill=gold, font=_font(26, True), anchor="mm")
        draw.text((W // 2, 135), "SELECCIÓN OFICIAL PLAYDOIT", fill=white, font=_font(40, True), anchor="mm")

        league_str = str(pick.get("league", "LIGA OFICIAL"))[:48]
        draw.rounded_rectangle([(110, 215), (W - 110, 270)], radius=14, fill=(6, 78, 59))
        draw.text((W // 2, 242), league_str.upper(), fill=(52, 211, 153), font=_font(22, True), anchor="mm")

        match_str = f"{pick.get('home_team', '')} vs {pick.get('away_team', '')}".strip(" vs ") or str(pick.get("match", "Partido"))
        draw.text((W // 2, 345), match_str[:42], fill=white, font=_font(36, True), anchor="mm")

        pick_str = _get_explicit_pick(pick)[:52]
        pick_font_sz = 36 if len(pick_str) > 30 else 44
        draw.text((W // 2, 465), pick_str, fill=yellow, font=_font(pick_font_sz, True), anchor="mm")

        odds_ame = pick.get("market_odds_american", "-110")
        odds_dec = pick.get("market_odds_decimal", "1.90")
        stake_u = pick.get("stake_units", "1.0")
        draw.text((W // 2, 565), f"Cuota Playdoit: {odds_ame} ({odds_dec})  |  Stake: {stake_u} U", fill=white, font=_font(30, True), anchor="mm")

        min_odds = pick.get("minimum_odds_american") or pick.get("minimum_odds_decimal") or odds_ame
        draw.text((W // 2, 645), f"Cuota Mínima Aceptable: {min_odds}  •  Horario: {pick.get('time', '')}", fill=slate, font=_font(24, False), anchor="mm")

        tid = pick.get("ticket_id", "RT-VERIFIED")
        draw.text((W // 2, 745), f"Ticket ID: {tid}  •  Sellado SHA-256", fill=(52, 211, 153), font=_font(22, True), anchor="mm")

        draw.rounded_rectangle([(90, 870), (W - 90, 980)], radius=20, fill=gold)
        draw.text((W // 2, 912), "AUDITORÍA EN VIVO & VIP EN REYTACOPICKS.COM", fill=(7, 16, 33), font=_font(26, True), anchor="mm")
        draw.text((W // 2, 952), "74% Win Rate en Moneyline • +28.1% ROI en NBA • +23.1% ROI en Tenis", fill=(20, 20, 20), font=_font(20, True), anchor="mm")

        out_dir = REPO_ROOT / "data" / "cards"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"card_{tid.replace('/', '_')}.jpg"
        im.save(out_path, "JPEG", quality=93)
        return out_path
    except Exception as e:
        print(f"⚠️ Error renderizando tarjeta oficial pre-partido: {e}")
        return None


def send_local_photo_to_channel(chat_id: str | int, photo_path: Path, caption: str) -> bool:
    if not TELEGRAM_TOKEN or not photo_path.exists():
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            files = {"photo": (photo_path.name, f, "image/jpeg")}
            data = {"chat_id": chat_id, "caption": caption[:1000], "parse_mode": "HTML"}
            r = requests.post(url, data=data, files=files, timeout=30)
            if r.status_code == 200:
                return True
            print(f"⚠️ Error sendPhoto local ({r.status_code}): {r.text}")
    except Exception as e:
        print(f"⚠️ Error enviando foto local a {chat_id}: {e}")
    return False


def format_public_channel_message(pick: Dict[str, Any], is_parlay_ticket: bool = False) -> str:
    """Genera el mensaje verificado para el canal público de Telegram (<1000 chars y HTML-safe para sendPhoto)."""
    import html
    is_parlay = pick.get("is_parlay", False) or bool(pick.get("legs"))
    ticket_id = html.escape(str(pick.get("ticket_id", "RT-VERIFIED")))

    if is_parlay:
        legs = pick.get("legs", [])
        legs_text = ""
        for i, leg in enumerate(legs, 1):
            h = html.escape(str(leg.get("home_team", "")))
            a = html.escape(str(leg.get("away_team", "")))
            lg = html.escape(str(leg.get("league", "")))
            pk = html.escape(_get_explicit_pick(leg))
            od = html.escape(str(leg.get("odds_american", leg.get("odds_decimal", ""))))
            tm = html.escape(str(leg.get("time", "")))
            legs_text += f"🔹 <b>#{i}:</b> {h} vs {a} ({lg})\n   🎯 <b>{pk}</b> @ <code>{od}</code> | ⏰ {tm}\n"

        msg = f"""👑 <b>REY TACO PICKS — PARLAY VERIFICADO</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🎟️ <b>Ticket ID:</b> <code>{ticket_id}</code>
{legs_text.strip()}

📊 <b>Cuota Total Playdoit:</b> <code>{html.escape(str(pick.get('market_odds_american', pick.get('market_odds_decimal'))))}</code>
⚖️ <b>Stake:</b> {pick.get('stake_units', '1.0')} U
━━━━━━━━━━━━━━━━━━━━━━━━━━
👉 <b>VIP & Auditoría en vivo:</b> https://reytacopicks.com/#vip"""
        return msg[:1000]

    h_team = html.escape(str(pick.get("home_team", "")))
    a_team = html.escape(str(pick.get("away_team", "")))
    match_line = f"{h_team} vs {a_team}" if (h_team and a_team) else html.escape(str(pick.get("match", "Partido")))
    league_str = html.escape(str(pick.get("league", "")))
    time_str = html.escape(str(pick.get("time", "")))
    pick_str = html.escape(_get_explicit_pick(pick))
    mkt_str = html.escape(str(pick.get("market_name") or pick.get("altenar_market") or ""))
    mkt_line = f"📌 <b>Mercado:</b> {mkt_str}\n" if mkt_str else ""
    odds_str = html.escape(str(pick.get("market_odds_american", pick.get("market_odds_decimal", ""))))
    min_odds_str = html.escape(str(pick.get("minimum_odds_american", pick.get("minimum_odds_decimal", odds_str))))
    stake_str = html.escape(str(pick.get("stake_units", "1.0")))

    raw_reason = str(pick.get("reasoning") or "").strip()
    if len(raw_reason) > 240:
        raw_reason = raw_reason[:237] + "..."
    reasoning_block = f"\n🧠 <b>Análisis:</b> <i>{html.escape(raw_reason)}</i>\n" if raw_reason else ""

    parlay_badge = "\n🎰 <b>MODALIDAD BOLETO:</b> <i>Jugada metida también dentro de nuestro Parlay Oficial en Playdoit.</i>\n" if (is_parlay_ticket or pick.get("in_admin_parlay")) else ""

    msg = f"""👑 <b>REY TACO PICKS — SELECCIÓN VERIFICADA</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🎟️ <b>Ticket:</b> <code>{ticket_id}</code>
🏟️ <b>Partido:</b> {match_line}
🏆 <b>Liga:</b> {league_str} | ⏰ {time_str}

{mkt_line}🎯 <b>Pronóstico:</b> <b>{pick_str}</b>
📊 <b>Cuota Playdoit:</b> <code>{odds_str}</code> | 🛡️ <b>Mínima:</b> <code>{min_odds_str}</code>
⚖️ <b>Stake:</b> {stake_str} U{parlay_badge}{reasoning_block}━━━━━━━━━━━━━━━━━━━━━━━━━━
💎 <b>¿Quieres todos los picks del día y el Parlay VIP?</b>
👉 https://reytacopicks.com/#vip"""
    return msg[:1000]


def format_admin_approval_message(pick: Dict[str, Any]) -> str:
    """Genera el mensaje interactivo para Carlos pidiendo foto (individual o Parlay) con fallback de 5 min."""
    import html
    is_parlay = pick.get("is_parlay", False) or bool(pick.get("legs"))
    ticket_id = html.escape(str(pick.get("ticket_id", "")))

    if is_parlay:
        legs = pick.get("legs", [])
        legs_str = "\n".join([f"  • {html.escape(str(l.get('home_team')))} vs {html.escape(str(l.get('away_team')))}: <b>{html.escape(_get_explicit_pick(l))}</b> @ {html.escape(str(l.get('odds_american')))}" for l in legs])
        summary = f"🎰 <b>PARLAY ({len(legs)} Selecciones):</b>\n{legs_str}"
    else:
        summary = f"🏟️ <b>Evento:</b> {html.escape(str(pick.get('home_team')))} vs {html.escape(str(pick.get('away_team')))} ({html.escape(str(pick.get('league')))})\n⏰ <b>Horario:</b> {html.escape(str(pick.get('time')))} CDMX\n🎯 <b>Pick:</b> <b>{html.escape(_get_explicit_pick(pick))}</b> @ {html.escape(str(pick.get('market_odds_american')))}"

    ev_stake_line = f"⚖️ <b>Stake:</b> {pick.get('stake_units', '1.0')} U"
    meaning_block = f"\n💡 <b>¿Qué significa?:</b>\n<i>{html.escape(str(pick.get('meaning')))}</i>\n" if pick.get('meaning') else ""

    path_val = pick.get('playdoit_path')
    if isinstance(path_val, list):
        path_str = "\n".join([f"  {idx+1}. {html.escape(str(step))}" for idx, step in enumerate(path_val)])
        path_block = f"\n🗺️ <b>Ruta en Playdoit:</b>\n{path_str}\n"
    elif isinstance(path_val, str) and path_val:
        path_block = f"\n🗺️ <b>Ruta Playdoit:</b> {html.escape(path_val)}\n"
    else:
        path_block = ""

    return f"""🚨 <b>[REVISIÓN REY TACO] NUEVA JUGADA GENERADA</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🎟️ <b>Ticket ID:</b> <code>{ticket_id}</code>
{summary}

📊 <b>Cuota Playdoit:</b> <code>{html.escape(str(pick.get('market_odds_american')))}</code> ({pick.get('market_odds_decimal')})
🛡️ <b>Mínima Aceptable:</b> {html.escape(str(pick.get('minimum_odds_american')))} | {ev_stake_line}
{meaning_block}{path_block}━━━━━━━━━━━━━━━━━━━━━━━━━━
📸 <b>OPCIONES DE PUBLICACIÓN (5 MINUTOS):</b>
1️⃣ <b>Si la metiste sola o en Parlay:</b> Envía la captura de tu boleto de Playdoit aquí (si la metiste en Parlay, puedes tocar primero <b>[🎰 La metí en Parlay]</b> o enviar la foto directo).
2️⃣ <b>1 Solo Tap:</b> Toca <b>[✅ Publicar Ya]</b> para lanzarla de inmediato con la Tarjeta Oficial generada.
3️⃣ <b>Automático (5 min):</b> Si estás ocupado y no subes foto en 5 minutos, se publicará automáticamente con la Tarjeta Oficial."""


def execute_publish_to_channel(
    ticket_id: str,
    photo_file_id: Optional[str] = None,
    reason: str = "MANUAL_APPROVAL",
    is_parlay_ticket: bool = False
) -> bool:
    """Publica al canal de Telegram con foto de Playdoit o con la Tarjeta Oficial auto-generada."""
    pick = None
    admin_msg_id = None

    with DISPATCH_LOCK:
        item = PENDING_DISPATCHES.get(ticket_id)
        if item:
            if item.get("status") in ("published", "discarded"):
                return False
            item["status"] = "published"
            timer = item.get("timer")
            if timer:
                try:
                    timer.cancel()
                except Exception:
                    pass
            pick = item.get("pick")
            admin_msg_id = item.get("admin_msg_id")

    if not pick:
        disk_item = load_pending_pick_by_id(ticket_id)
        if not disk_item or disk_item.get("status") in ("published", "discarded"):
            return False
        pick = disk_item.get("pick")
        is_parlay_ticket = is_parlay_ticket or bool(disk_item.get("is_parlay_ticket"))

    if not pick:
        return False

    update_pending_pick_status(ticket_id, "published", {"published_reason": reason, "is_parlay_ticket": is_parlay_ticket})

    channel_dest = FREE_CHANNEL_ID or ADMIN_CHAT_ID
    if not channel_dest:
        print("⚠️ No hay canal configurado para publicar.")
        return False

    pub_msg = format_public_channel_message(pick, is_parlay_ticket=is_parlay_ticket)
    success = False

    card_path = None
    if photo_file_id:
        res = telegram_api_call("sendPhoto", {
            "chat_id": channel_dest,
            "photo": photo_file_id,
            "caption": pub_msg,
            "parse_mode": "HTML"
        })
        success = bool(res and res.get("ok"))
    else:
        card_path = render_official_prematch_card(pick)
        if card_path and card_path.exists():
            success = send_local_photo_to_channel(channel_dest, card_path, pub_msg)
        if not success:
            res = telegram_api_call("sendMessage", {
                "chat_id": channel_dest,
                "text": pub_msg,
                "parse_mode": "HTML"
            })
            success = bool(res and res.get("ok"))

    # Enviar directamente al chat privado de la novia de Carlos (8996443105)
    gf_chat_id = resolve_girlfriend_chat_id()
    if gf_chat_id and str(gf_chat_id) != str(channel_dest):
        try:
            gf_header = f"💝 <b>NUEVO PICK REY TACO</b> 🌮👑\n\n{pub_msg}"
            if photo_file_id:
                telegram_api_call("sendPhoto", {
                    "chat_id": gf_chat_id,
                    "photo": photo_file_id,
                    "caption": gf_header[:1000],
                    "parse_mode": "HTML"
                })
            elif card_path and card_path.exists():
                send_local_photo_to_channel(gf_chat_id, card_path, gf_header[:1000])
            else:
                telegram_api_call("sendMessage", {
                    "chat_id": gf_chat_id,
                    "text": gf_header,
                    "parse_mode": "HTML"
                })
            print(f"💝 ✅ Pick enviado al chat privado de tu novia ({gf_chat_id}).")
        except Exception as e_gf:
            print(f"⚠️ Error enviando pick al privado de tu novia ({gf_chat_id}): {e_gf}")

    if success:
        print(f"📢 ✅ [DESPACHO EXITOSO] Ticket {ticket_id} publicado en {channel_dest} ({reason}).")
        try:
            record_pick_published(ticket_id, channel="TELEGRAM_FREE", ledger_path=AUDIT_LEDGER_PATH)
        except Exception as e:
            print(f"⚠️ Error registrando en ledger: {e}")

        if admin_msg_id and ADMIN_CHAT_ID:
            mode_txt = "⏰ Publicado automáticamente tras 5 min con Tarjeta Oficial" if "AUTO" in reason else "✅ Publicado con Tarjeta Oficial"
            updated_admin_text = f"""👑 <b>[PUBLICADO CON ÉXITO] TICKET {ticket_id}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
📢 {mode_txt} (enviado también al privado de tu novia).
🕒 {datetime.now(MEXICO_TZ).strftime('%H:%M:%S')} CDMX"""
            telegram_api_call("editMessageText", {
                "chat_id": ADMIN_CHAT_ID,
                "message_id": admin_msg_id,
                "text": updated_admin_text,
                "parse_mode": "HTML"
            })

    return success


def execute_discard_pick(ticket_id: str) -> bool:
    """Cancela la jugada y registra el descarte."""
    admin_msg_id = None
    with DISPATCH_LOCK:
        item = PENDING_DISPATCHES.get(ticket_id)
        if item:
            item["status"] = "discarded"
            timer = item.get("timer")
            if timer:
                try:
                    timer.cancel()
                except Exception:
                    pass
            admin_msg_id = item.get("admin_msg_id")

    update_pending_pick_status(ticket_id, "discarded")
    print(f"🚫 ❌ [DESPACHO CANCELADO] Ticket {ticket_id} descartado por el Administrador.")

    if admin_msg_id and ADMIN_CHAT_ID:
        updated_text = f"""❌ <b>[PICK DESCARTADO] TICKET {ticket_id}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
🚫 El Administrador canceló la jugada. No se publicará."""
        telegram_api_call("editMessageText", {
            "chat_id": ADMIN_CHAT_ID,
            "message_id": admin_msg_id,
            "text": updated_text,
            "parse_mode": "HTML"
        })

    return True


def _auto_publish_after_timeout(ticket_id: str):
    """Callback del temporizador de 5 minutos: si sigue esperando foto, publica con Tarjeta Oficial."""
    disk_item = load_pending_pick_by_id(ticket_id)
    if disk_item and disk_item.get("status") != "waiting_photo":
        return
    print(f"⏰ [AUTO-PUBLISH 5 MIN] Tiempo agotado esperando foto manual para {ticket_id}. Publicando con Tarjeta Oficial...")
    execute_publish_to_channel(ticket_id, photo_file_id=None, reason="AUTO_TIMEOUT_5MIN")


def dispatch_interactive_pick(pick: Dict[str, Any], timeout_seconds: int = TIMEOUT_SECONDS) -> bool:
    """
    Inicia el flujo interactivo de despacho:
    - Pide foto a Carlos por Telegram y por Correo (individual o Parlay).
    - Ofrece botón [✅ Publicar Ya] con 1 solo tap y botón [🎰 La metí en Parlay].
    - Si pasan 5 minutos (300s) sin captura manual, publica automáticamente con la Tarjeta Oficial generada.
    """
    ticket_id = pick.get("ticket_id")
    if not ticket_id:
        print("⚠️ Pick sin Ticket ID. No se puede despachar.")
        return False

    save_pending_pick_waiting_photo(pick)
    # NOTA: No se envían correos antes del partido. El correo se envía al finalizar el partido si la jugada se cobra.

    if not ADMIN_CHAT_ID:
        print("ℹ️ No hay TELEGRAM_ADMIN_ID configurado.")
        return False

    admin_msg = format_admin_approval_message(pick)

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Publicar (Tarjeta Oficial)", "callback_data": f"pub_{ticket_id}"},
                {"text": "🎰 La metí en Parlay", "callback_data": f"parlay_{ticket_id}"}
            ],
            [
                {"text": "📱 Mini App", "web_app": {"url": "https://reytacopicks.com/mini-app.html"}},
                {"text": "❌ Descartar", "callback_data": f"disc_{ticket_id}"}
            ]
        ]
    }

    res = telegram_api_call("sendMessage", {
        "chat_id": ADMIN_CHAT_ID,
        "text": admin_msg,
        "parse_mode": "HTML",
        "reply_markup": keyboard
    })

    if not res or not res.get("ok"):
        print("⚠️ Fallo enviando mensaje al admin.")
        return False

    msg_id = res["result"]["message_id"]

    timer = threading.Timer(timeout_seconds, _auto_publish_after_timeout, args=(ticket_id,))
    timer.daemon = True
    timer.start()

    with DISPATCH_LOCK:
        PENDING_DISPATCHES[ticket_id] = {
            "status": "waiting_photo",
            "pick": pick,
            "admin_msg_id": msg_id,
            "timer": timer,
            "created_at": time.time()
        }

    print(f"🔔 [DESPACHO INTERACTIVO] Solicitud enviada a Carlos ({ADMIN_CHAT_ID}) con auto-publicación en {timeout_seconds}s.")
    return True


def poll_telegram_callbacks(duration_seconds: int = 300):
    """Escucha activa de respuestas de botones durante la ventana de decisión."""
    if not TELEGRAM_TOKEN:
        return

    offset = 0
    start_time = time.time()
    print(f"🎧 [CALLBACK LISTENER] Escuchando interacción del Administrador por {duration_seconds}s...")

    while (time.time() - start_time) < duration_seconds:
        with DISPATCH_LOCK:
            pending_count = sum(1 for v in PENDING_DISPATCHES.values() if v.get("status") == "waiting_photo")
        if pending_count == 0:
            break

        updates = telegram_api_call("getUpdates", {"offset": offset, "timeout": 5})
        if updates and updates.get("ok") and updates.get("result"):
            for update in updates["result"]:
                offset = update["update_id"] + 1

                if "callback_query" in update:
                    cb = update["callback_query"]
                    cb_id = cb["id"]
                    data = cb.get("data", "")
                    user_id = str(cb.get("from", {}).get("id", ""))

                    if ADMIN_CHAT_ID and user_id != str(ADMIN_CHAT_ID):
                        telegram_api_call("answerCallbackQuery", {
                            "callback_query_id": cb_id,
                            "text": "⛔ No autorizado.",
                            "show_alert": True
                        })
                        continue

                    if data.startswith("pub_"):
                        tid = data.replace("pub_", "")
                        execute_publish_to_channel(tid, reason="MANUAL_APPROVAL")
                        telegram_api_call("answerCallbackQuery", {
                            "callback_query_id": cb_id,
                            "text": "📢 ¡Pick publicado con Tarjeta Oficial!"
                        })

                    elif data.startswith("parlay_"):
                        tid = data.replace("parlay_", "")
                        update_pending_pick_status(tid, "waiting_photo", {"is_parlay_ticket": True})
                        telegram_api_call("answerCallbackQuery", {
                            "callback_query_id": cb_id,
                            "text": "🎰 Marcado como Parlay. Envía aquí la captura de tu Parlay de Playdoit."
                        })

                    elif data.startswith("disc_"):
                        tid = data.replace("disc_", "")
                        execute_discard_pick(tid)
                        telegram_api_call("answerCallbackQuery", {
                            "callback_query_id": cb_id,
                            "text": "❌ Pick descartado. No se publicará."
                        })

        time.sleep(1)


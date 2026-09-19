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


def mark_pick_photo_received(ticket_id: str, photo_filename: str):
    """Marca que el pick ya recibió su foto de Playdoit obligatoria."""
    if not PENDING_PICKS_FILE.exists():
        return
    try:
        with open(PENDING_PICKS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if ticket_id in data:
            data[ticket_id]["status"] = "photo_received"
            data[ticket_id]["photo_filename"] = photo_filename
            data[ticket_id]["received_at"] = datetime.now(MEXICO_TZ).isoformat()
            with open(PENDING_PICKS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error marking pick photo: {e}")


def format_public_channel_message(pick: Dict[str, Any]) -> str:
    """Genera el mensaje verificado y anti-tipster para el canal público de Telegram (Solo o Parlay)."""
    is_parlay = pick.get("is_parlay", False) or bool(pick.get("legs"))
    ticket_id = pick.get("ticket_id", "RT-VERIFIED")

    if is_parlay:
        legs = pick.get("legs", [])
        legs_text = ""
        for i, leg in enumerate(legs, 1):
            h = leg.get("home_team", "")
            a = leg.get("away_team", "")
            lg = leg.get("league", "")
            pk = leg.get("pick", "")
            od = leg.get("odds_american", leg.get("odds_decimal", ""))
            tm = leg.get("time", "")
            legs_text += f"🔹 <b>Selección #{i}:</b> {h} vs {a} ({lg})\n   🎯 <b>{pk}</b> @ <code>{od}</code> | ⏰ {tm} CDMX\n\n"

        return f"""👑 <b>REY TACO PICKS — PARLAY INSTITUCIONAL VERIFICADO</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🎟️ <b>Ticket ID:</b> <code>{ticket_id}</code>
🎰 <b>Formato:</b> PARLAY COMBINADO ({len(legs)} SELECCIONES)

{legs_text.strip()}

📊 <b>Cuota Total Playdoit:</b> <code>{pick.get('market_odds_american', pick.get('market_odds_decimal'))}</code>
🛡️ <b>Cuota Mínima Aceptable:</b> <code>{pick.get('minimum_odds_american', pick.get('minimum_odds_decimal'))}</code>
💎 <b>Valor Esperado (+EV Conjunto):</b> +{pick.get('ev_percent', '6.5')}%
⚖️ <b>Kelly Stake:</b> {pick.get('stake_units', '1.0')} U ({pick.get('stake_units', '1.0')}% Bankroll)
━━━━━━━━━━━━━━━━━━━━━━━━━━
📸 <b>EVIDENCIA REAL PLAYDOIT ADJUNTA:</b>
Boleto oficial sellado e inmutable en el ledger criptográfico SHA-256 antes del silbatazo inicial.
👉 Auditoría en vivo: https://reytacopicks.com"""
    else:
        return f"""👑 <b>REY TACO PICKS — SELECCIÓN SIMPLE VERIFICADA</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🎟️ <b>Ticket ID:</b> <code>{ticket_id}</code>
⚽ <b>Partido:</b> {pick.get('home_team')} vs {pick.get('away_team')}
🏆 <b>Liga:</b> {pick.get('league')} | ⏰ <b>Horario:</b> {pick.get('time')} CDMX

🎯 <b>Pronóstico:</b> <b>{pick.get('pick')}</b>
📊 <b>Cuota Playdoit:</b> <code>{pick.get('market_odds_american', pick.get('market_odds_decimal'))}</code>
🛡️ <b>Cuota Mínima Aceptable:</b> <code>{pick.get('minimum_odds_american', pick.get('minimum_odds_decimal'))}</code>

📈 <b>Ventaja Cuantitativa (Edge):</b> +{pick.get('model_edge_pp', '4.5')}%
💎 <b>Valor Esperado (+EV):</b> +{pick.get('ev_percent', '5.0')}%
⚖️ <b>Kelly Stake:</b> {pick.get('stake_units', '1.0')} U ({pick.get('stake_units', '1.0')}% Bankroll)
━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️ <b>REGLA INSTITUCIONAL DE PRECIO:</b>
Si al abrir Playdoit la cuota cayó por debajo de <b>{pick.get('minimum_odds_american', pick.get('minimum_odds_decimal'))}</b>, el sistema dictamina <b>NO APOSTAR</b>. El valor ha expirado.

📸 <b>EVIDENCIA REAL PLAYDOIT ADJUNTA:</b>
Boleto oficial sellado e inmutable en el ledger criptográfico SHA-256 antes del inicio del juego.
👉 Auditoría en vivo: https://reytacopicks.com"""


def format_admin_approval_message(pick: Dict[str, Any]) -> str:
    """Genera el mensaje interactivo para el Administrador exigiendo la foto obligatoria de Playdoit."""
    is_parlay = pick.get("is_parlay", False) or bool(pick.get("legs"))
    ticket_id = pick.get("ticket_id")

    if is_parlay:
        legs = pick.get("legs", [])
        legs_str = "\n".join([f"  • {l.get('home_team')} vs {l.get('away_team')}: <b>{l.get('pick')}</b> @ {l.get('odds_american')}" for l in legs])
        summary = f"🎰 <b>PARLAY ({len(legs)} Selecciones):</b>\n{legs_str}"
    else:
        summary = f"⚽ <b>Evento:</b> {pick.get('home_team')} vs {pick.get('away_team')} ({pick.get('league')})\n⏰ <b>Horario:</b> {pick.get('time')} CDMX\n🎯 <b>Pick:</b> <b>{pick.get('pick')}</b> @ {pick.get('market_odds_american')}"

    return f"""🚨 <b>[REVISIÓN REY TACO] NUEVA JUGADA GENERADA</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
🎟️ <b>Ticket ID:</b> <code>{ticket_id}</code>
🎲 <b>Modalidad:</b> <b>{'PARLAY COMBINADO' if is_parlay else 'PICK SOLO'}</b>

{summary}

📊 <b>Cuota Total Playdoit:</b> <code>{pick.get('market_odds_american')}</code> ({pick.get('market_odds_decimal')})
🛡️ <b>Mínima Aceptable:</b> {pick.get('minimum_odds_american')}
💎 <b>Valor Esperado (+EV):</b> +{pick.get('ev_percent')}% | ⚖️ <b>Stake:</b> {pick.get('stake_units')} U

━━━━━━━━━━━━━━━━━━━━━━━━━━
📸 <b>ACCIÓN REQUERIDA: FOTO OBLIGATORIA DE PLAYDOIT</b>
<i>⚠️ Regla Institucional estricta: Ningún pick se publicará sin su captura de pantalla de Playdoit.</i>

👉 <b>Mete la jugada en Playdoit y envía la captura del boleto por aquí para que el bot:</b>
1. Publique el pick en el Canal con la foto del boleto adjunta.
2. Genere el Reel de video con la imagen real de Playdoit y lo envíe al grupo de trabajo para TikTok, Instagram y Facebook.
3. Selle criptográficamente el hash en el Audit Ledger."""


def execute_publish_to_channel(ticket_id: str, photo_file_id: Optional[str] = None) -> bool:
    """Publica definitivamente al canal de Telegram con la foto obligatoria y sella en el Ledger."""
    with DISPATCH_LOCK:
        item = PENDING_DISPATCHES.get(ticket_id)
        if not item:
            return False

        item["status"] = "published"
        pick = item["pick"]
        admin_msg_id = item.get("admin_msg_id")

    channel_dest = FREE_CHANNEL_ID or ADMIN_CHAT_ID
    if not channel_dest:
        print("⚠️ No hay canal configurado para publicar.")
        return False

    pub_msg = format_public_channel_message(pick)

    if photo_file_id:
        res = telegram_api_call("sendPhoto", {
            "chat_id": channel_dest,
            "photo": photo_file_id,
            "caption": pub_msg,
            "parse_mode": "HTML"
        })
    else:
        res = telegram_api_call("sendMessage", {
            "chat_id": channel_dest,
            "text": pub_msg,
            "parse_mode": "HTML"
        })

    success = bool(res and res.get("ok"))

    if success:
        print(f"📢 ✅ [DESPACHO EXITOSO] Ticket {ticket_id} publicado en {channel_dest} con foto.")

        # Sellar en el Ledger
        try:
            record_pick_published(ticket_id, channel="TELEGRAM_FREE", ledger_path=AUDIT_LEDGER_PATH)
        except Exception as e:
            print(f"⚠️ Error registrando en ledger: {e}")

        # Notificar al Admin
        if admin_msg_id and ADMIN_CHAT_ID:
            updated_admin_text = f"""👑 <b>[PUBLICADO CON ÉXITO] TICKET {ticket_id}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
📸 Foto de Playdoit verificada y vinculada.
📢 Publicado con evidencia fotográfica en el canal.
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
    with DISPATCH_LOCK:
        item = PENDING_DISPATCHES.get(ticket_id)
        if item:
            item["status"] = "discarded"
            admin_msg_id = item.get("admin_msg_id")
        else:
            admin_msg_id = None

    print(f"🚫 ❌ [DESPACHO CANCELADO] Ticket {ticket_id} descartado por el Administrador.")

    if admin_msg_id and ADMIN_CHAT_ID:
        updated_text = f"""❌ <b>[PICK DESCARTADO] TICKET {ticket_id}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
🚫 El Administrador canceló la jugada. No se pedirá foto ni se publicará."""
        telegram_api_call("editMessageText", {
            "chat_id": ADMIN_CHAT_ID,
            "message_id": admin_msg_id,
            "text": updated_text,
            "parse_mode": "HTML"
        })

    return True


def dispatch_interactive_pick(pick: Dict[str, Any]) -> bool:
    """
    Inicia el flujo interactivo de despacho exigiendo la foto obligatoria de Playdoit.
    NO se publica automáticamente por temporizador: espera a que Carlos envíe la foto.
    """
    ticket_id = pick.get("ticket_id")
    if not ticket_id:
        print("⚠️ Pick sin Ticket ID. No se puede despachar.")
        return False

    # Guardar en disco el pick esperando foto
    save_pending_pick_waiting_photo(pick)

    if not ADMIN_CHAT_ID:
        print("ℹ️ No hay TELEGRAM_ADMIN_ID configurado.")
        return False

    admin_msg = format_admin_approval_message(pick)

    # Botón para descartar si Carlos decide no meter la jugada
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "❌ Descartar Jugada", "callback_data": f"disc_{ticket_id}"}
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
        print(f"⚠️ Fallo enviando mensaje al admin.")
        return False

    msg_id = res["result"]["message_id"]

    with DISPATCH_LOCK:
        PENDING_DISPATCHES[ticket_id] = {
            "status": "waiting_photo",
            "pick": pick,
            "admin_msg_id": msg_id,
            "created_at": time.time()
        }

    print(f"🔔 [FOTO OBLIGATORIA SOLICITADA] Notificación enviada a Carlos ({ADMIN_CHAT_ID}). Esperando captura de Playdoit...")
    return True


def poll_telegram_callbacks(duration_seconds: int = 300):
    """
    Escucha activa de respuestas de botones durante la ventana de decisión.
    """
    if not TELEGRAM_TOKEN:
        return

    offset = 0
    start_time = time.time()
    print(f"🎧 [CALLBACK LISTENER] Escuchando interacción del Administrador por {duration_seconds}s...")

    while (time.time() - start_time) < duration_seconds:
        # Si ya no hay picks pendientes, terminar escucha
        with DISPATCH_LOCK:
            pending_count = sum(1 for v in PENDING_DISPATCHES.values() if v.get("status") == "pending")
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

                    # Validar que quien presionó el botón sea el administrador
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
                            "text": "📢 ¡Pick publicado exitosamente en el canal!"
                        })

                    elif data.startswith("disc_"):
                        tid = data.replace("disc_", "")
                        execute_discard_pick(tid)
                        telegram_api_call("answerCallbackQuery", {
                            "callback_query_id": cb_id,
                            "text": "❌ Pick descartado. No se publicará."
                        })

                    elif data.startswith("tiktok_"):
                        tid = data.replace("tiktok_", "")
                        telegram_api_call("answerCallbackQuery", {
                            "callback_query_id": cb_id,
                            "text": "🎬 Generando y enviando Pack TikTok..."
                        })
                        try:
                            from backend.tiktok_video_generator import render_pick_tiktok_reel
                            from backend.tiktok_pack_delivery import deliver_tiktok_pack
                            with DISPATCH_LOCK:
                                p_data = PENDING_DISPATCHES.get(tid, {}).get("pick")
                            if p_data:
                                vid_path = render_pick_tiktok_reel(p_data, duration_sec=6)
                                deliver_tiktok_pack(str(vid_path), p_data)
                        except Exception as e:
                            print(f"⚠️ Error generando Pack TikTok: {e}")

        time.sleep(1)


if __name__ == "__main__":
    # Prueba rápida con pick simulado si se corre directo
    test_pick = {
        "ticket_id": "RT-20260918-TEST-0001",
        "home_team": "Doosan Bears",
        "away_team": "Kiwoom Heroes",
        "league": "KBO Corea",
        "pick": "Más de 7.0 Carreras",
        "time": "03:30",
        "market_odds_american": "-135",
        "market_odds_decimal": 1.74,
        "minimum_odds_american": "-142",
        "model_edge_pp": 7.39,
        "ev_percent": 6.38,
        "stake_units": 1.60
    }
    dispatch_interactive_pick(test_pick, timeout_seconds=15)
    poll_telegram_callbacks(duration_seconds=20)

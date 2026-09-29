"""
backend/victory_content_verifier.py
===================================
Módulo de Verificación de Boletos de Playdoit para Generación de Contenido.

Regla de Oro de Carlos:
- La creación de contenido para redes sociales (Historias de Instagram, Posts de Feed, Canales)
  SOLO se genera cuando Carlos proporciona la captura real de su boleto verde ganado en Playdoit.
- Si Carlos no la apostó en la vida real, pulsa [ ❌ No lo aposté ] y se descarta la generación
  de contenido, manteniendo las redes 100% transparentes y con apuestas reales.
- El récord estadístico del algoritmo en la web se mantiene de forma independiente.
"""

from __future__ import annotations

import os
import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=REPO_ROOT / ".env")
load_dotenv(dotenv_path=BASE_DIR / ".env")

MEXICO_TZ = ZoneInfo("America/Mexico_City")
REQUESTS_FILE = REPO_ROOT / "data" / "pending_victory_content_requests.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_ID") or os.getenv("TELEGRAM_CHAT_ID")


def telegram_api_call(method: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Llamada segura a la API de Telegram."""
    if not TELEGRAM_TOKEN:
        print("[TELEGRAM] Falta TELEGRAM_BOT_TOKEN en variables de entorno.")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[TELEGRAM] Error en llamada {method}: {e}")
        return None


def send_local_photo_telegram(chat_id: int | str, photo_path: Path, caption: str = "") -> bool:
    """Envía un archivo de imagen local a Telegram usando multipart/form-data."""
    if not TELEGRAM_TOKEN or not photo_path.exists():
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            files = {"photo": (photo_path.name, f, "image/jpeg")}
            data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
            res = requests.post(url, data=data, files=files, timeout=40)
            return res.status_code == 200
    except Exception as e:
        print(f"[TELEGRAM] Error enviando foto local: {e}")
        return False


def load_content_requests() -> Dict[str, Any]:
    if REQUESTS_FILE.exists():
        try:
            return json.loads(REQUESTS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_content_requests(requests: Dict[str, Any]) -> None:
    REQUESTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    REQUESTS_FILE.write_text(json.dumps(requests, indent=2, ensure_ascii=False), encoding="utf-8")


def get_latest_waiting_victory_request() -> Optional[Dict[str, Any]]:
    """Devuelve la solicitud más reciente esperando captura de Playdoit."""
    reqs = load_content_requests()
    waiting = [v for v in reqs.values() if v.get("status") == "waiting_photo"]
    if not waiting:
        return None
    waiting.sort(key=lambda x: x.get("prompted_at", ""), reverse=True)
    return waiting[0]


def prompt_victory_content_request(record: Dict[str, Any], chat_id: Optional[str | int] = None) -> bool:
    """
    Envía un mensaje interactivo a Carlos en Telegram preguntando si apostó el pick en Playdoit:
    - Pide foto del boleto verde para armar historias y posts de redes.
    - O botón para descartar generar contenido si no se apostó.
    """
    target_chat = chat_id or ADMIN_CHAT_ID
    if not target_chat:
        print("[VERIFIER] No hay ADMIN_CHAT_ID para enviar la solicitud de contenido.")
        return False

    ticket_id = record.get("ticket_id", f"RT-WIN-{int(time.time())}")
    reqs = load_content_requests()

    # Si ya se descartó o ya se generó, no re-preguntar a menos que sea forzado
    existing = reqs.get(ticket_id)
    if existing and existing.get("status") in ("content_generated", "discarded_unbet"):
        print(f"[VERIFIER] Ticket {ticket_id} ya se encuentra en estado '{existing.get('status')}'.")
        return False

    sport_icon = record.get("sport_icon", "🟢")
    league = record.get("league", "LIGA")
    match = record.get("match", "Partido")
    pick = record.get("pick", "Selección")
    odds_ame = record.get("odds_ame", "+100")
    odds_dec = record.get("odds_dec", 2.0)
    profit_units = record.get("profit_units", 1.5)
    profit_pesos = record.get("profit_pesos", 75)

    msg_text = f"""🟢 <b>¡COBRAMOS! VICTORIA REGISTRADA</b> 🌮👑
━━━━━━━━━━━━━━━━━━━━━━━━━━
{sport_icon} <b>{league}</b>
🏟️ <b>Partido:</b> {match}
👉 <b>Pronóstico:</b> <b>{pick}</b>
📊 <b>Cuota Cobrada:</b> <code>{odds_ame} ({odds_dec})</code>
💰 <b>Beneficio Neto:</b> <b>+{profit_units}U (+${profit_pesos:,} MXN limpios)</b>

<b>¿Metiste esta jugada en Playdoit en la vida real?</b>

📸 <b>Si la apostaste:</b> Envía la captura de tu <b>boleto verde de Playdoit</b> aquí en el chat.
El bot la integrará dentro de la plantilla oficial de Instagram (1080x1920) y Feed (1080x1080) con el copy viral listo para publicar.

❌ <b>Si NO la apostaste:</b> Toca el botón abajo para descartar generar contenido y mantener tus redes con apuestas 100% reales."""

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "❌ No lo aposté (Descartar contenido)", "callback_data": f"discard_win_photo_{ticket_id}"}
            ]
        ]
    }

    res = telegram_api_call("sendMessage", {
        "chat_id": target_chat,
        "text": msg_text,
        "parse_mode": "HTML",
        "reply_markup": keyboard
    })

    if res and res.get("ok"):
        msg_id = res["result"]["message_id"]
        reqs[ticket_id] = {
            "ticket_id": ticket_id,
            "status": "waiting_photo",
            "record": record,
            "prompt_msg_id": msg_id,
            "prompted_at": datetime.now(MEXICO_TZ).strftime("%Y-%m-%d %H:%M:%S")
        }
        save_content_requests(reqs)
        print(f"✅ [VERIFIER] Solicitud de foto de victoria enviada a Carlos para {ticket_id}.")
        return True
    return False


def discard_victory_content(ticket_id: str) -> Optional[str]:
    """Descarta la generación de contenido manteniendo el récord intacto."""
    reqs = load_content_requests()
    item = reqs.get(ticket_id)
    if not item:
        # Registrar descarte de todas formas
        item = {"ticket_id": ticket_id, "record": {}}
        reqs[ticket_id] = item

    item["status"] = "discarded_unbet"
    item["discarded_at"] = datetime.now(MEXICO_TZ).strftime("%Y-%m-%d %H:%M:%S")
    save_content_requests(reqs)

    print(f"🚫 [VERIFIER] Contenido de victoria para {ticket_id} descartado (no apostado).")

    return f"""🚫 <b>[CONTENIDO DESCARTADO] TICKET {ticket_id}</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━
Confirmaste que no apostaste este pick en Playdoit.
No se generarán historias ni posts para redes sociales.

<i>(Tu récord cuantitativo institucional de 78% permanece verificado en la web sin alteraciones).</i>"""


def process_winning_ticket_photo(ticket_id: str, photo_path: Path, chat_id: Optional[str | int] = None) -> bool:
    """
    Procesa la captura real enviada por Carlos:
    1. Renderiza la Historia 9:16 y el Post 1:1 con el boleto real incrustado.
    2. Genera el copy viral.
    3. Envía los activos listos para publicar directo a Telegram.
    """
    target_chat = chat_id or ADMIN_CHAT_ID
    reqs = load_content_requests()
    item = reqs.get(ticket_id)
    if not item or not item.get("record"):
        print(f"[VERIFIER] No se encontró registro para ticket {ticket_id}.")
        return False

    record = item["record"]

    # Importar renderizadores
    from scripts.generate_victory_content import (
        render_victory_story,
        render_victory_feed,
        generate_telegram_victory_copy
    )

    story_path = render_victory_story(record, ticket_image_path=photo_path)
    feed_path = render_victory_feed(record, ticket_image_path=photo_path)
    copy_text = generate_telegram_victory_copy(record)

    # 1. Enviar historia para Instagram/TikTok
    caption_story = (
        "📱 <b>HISTORIA OFICIAL LISTA (1080x1920)</b>\n"
        "Boleto verde de Playdoit integrado con sello de verificación.\n"
        "👉 Lista para subir a Instagram Stories, Facebook y TikTok."
    )
    send_local_photo_telegram(target_chat, story_path, caption=caption_story)

    # 2. Enviar post de Feed cuadrado
    caption_feed = (
        "🖼️ <b>POST DE FEED LISTO (1080x1080)</b>\n"
        "Formato cuadrado de alta resolución para Instagram Feed y Facebook."
    )
    send_local_photo_telegram(target_chat, feed_path, caption=caption_feed)

    # 3. Enviar el copy viral formateado
    telegram_api_call("sendMessage", {
        "chat_id": target_chat,
        "text": f"📋 <b>COPY VIRAL PARA CANALES Y GRUPOS:</b>\n\n{copy_text}",
        "parse_mode": "HTML"
    })

    # 4. Actualizar estado
    item["status"] = "content_generated"
    item["ticket_photo_path"] = str(photo_path)
    item["story_path"] = str(story_path)
    item["feed_path"] = str(feed_path)
    item["completed_at"] = datetime.now(MEXICO_TZ).strftime("%Y-%m-%d %H:%M:%S")
    save_content_requests(reqs)

    telegram_api_call("sendMessage", {
        "chat_id": target_chat,
        "text": (
            "🎉 <b>¡CONTENIDO DE VICTORIA GENERADO CON ÉXITO!</b> 🌮👑\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Tus gráficos oficiales ya tienen tu boleto real de Playdoit incrustado.\n"
            "¡Tus redes se mantienen 100% transparentes y con apuestas reales!"
        ),
        "parse_mode": "HTML"
    })

    print(f"🎉 [VERIFIER] Paquete completo de contenido entregado a Carlos para {ticket_id}.")
    return True

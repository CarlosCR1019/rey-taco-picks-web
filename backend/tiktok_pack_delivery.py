"""
backend/tiktok_pack_delivery.py
===============================
Módulo de Entrega del Pack TikTok vía Telegram (Opción A).

Flujo de Trabajo:
1. Recibe el video vertical 9:16 (.mp4) y los datos auditados del pick/parlay.
2. Genera el texto optimizado para el algoritmo de TikTok:
   - Gancho viral de alta retención (anti-tipster / cuantitativo).
   - Datos del pick (cuota, cuota mínima, valor esperado +EV, Ticket ID).
   - Llamado a la acción (CTA al link en bio / cartelera gratuita).
   - 6-8 hashtags estratégicos de tendencia deportiva.
3. Envía directamente por Telegram:
   a) El archivo de video .mp4 listo para descargar al carrete del móvil.
   b) La tarjeta de instrucciones paso a paso (3 clics) para la novia de Carlos.
   c) El mensaje exclusivo con el texto exacto en bloque de código para que con UN SOLO TOQUE en Telegram lo copie al portapapeles.

Destinatario configurable:
- Variable de entorno `TELEGRAM_TIKTOK_CHAT_ID` (si es un chat privado con ella o un grupo compartido).
- Si no está definida, usa `TELEGRAM_ADMIN_ID` o `TELEGRAM_CHAT_ID` (chat de Carlos).
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import requests

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=REPO_ROOT / ".env")
load_dotenv(dotenv_path=BASE_DIR / ".env")

logger = logging.getLogger("TikTokPackDelivery")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_ID") or os.getenv("TELEGRAM_CHAT_ID")
TEAM_GROUP_FILE = REPO_ROOT / "data" / "team_group_id.json"


def resolve_target_chat_id() -> str:
    """Resuelve el chat de destino: grupo del equipo con Carlos y su novia, o admin."""
    if TEAM_GROUP_FILE.exists():
        try:
            data = json.loads(TEAM_GROUP_FILE.read_text(encoding="utf-8"))
            if data.get("team_group_id"):
                return str(data["team_group_id"])
        except Exception:
            pass
    return os.getenv("TELEGRAM_TIKTOK_CHAT_ID") or str(ADMIN_CHAT_ID or "")

TIKTOK_CHAT_ID = resolve_target_chat_id()
BIO_URL = "https://reytacopicks.com"



def build_tiktok_caption(pick: Dict[str, Any]) -> str:
    """
    Construye la descripción perfecta para el algoritmo de TikTok:
    - Gancho impactante en las primeras 2 líneas.
    - Explicación de valor matemático (no fijas).
    - Llamado a la acción.
    - Hashtags de alto alcance.
    """
    home = pick.get("home_team", "Local")
    away = pick.get("away_team", "Visitante")
    league = pick.get("league", "Liga MX")
    selection = pick.get("pick", "Selección")
    odds = pick.get("market_odds_american") or pick.get("market_odds_decimal", "1.90")
    min_odds = pick.get("minimum_odds_american") or pick.get("minimum_odds_decimal", "1.75")
    ev = pick.get("ev_percent", 5.0)
    ticket_id = pick.get("ticket_id", "RT-VERIFIED")

    caption = (
        f"⚠️ ¿Te dijeron que era 'fija'? La trampa de las cuotas explicada con Inteligencia Artificial 🌮👑\n\n"
        f"⚽ {home} vs {away} ({league})\n"
        f"🎯 Pick Cuantitativo: {selection}\n"
        f"💰 Cuota Playdoit: {odds}\n"
        f"🛡️ Cuota Mínima: {min_odds} (Si cae de aquí: NO APOSTAR)\n"
        f"📈 Valor Esperado (+EV): +{ev}%\n"
        f"🎫 Ticket Auditado: {ticket_id}\n\n"
        f"En Rey Taco Picks no vendemos humo ni acertijos. Analizamos ineficiencias de mercado con modelos estadísticos y sellamos cada pick antes del silbatazo inicial.\n\n"
        f"👉 Cartelera completa y picks gratis en el link del perfil 🔗\n\n"
        f"#LigaMX #ApuestasDeportivas #PicksDeportivos #ReyTacoPicks #InteligenciaArtificial #Parley #ApuestasMexico #FYP #Viral"
    )
    return caption


def send_telegram_message(chat_id: str, text: str, parse_mode: str = "HTML") -> Optional[Dict[str, Any]]:
    """Envía un mensaje de texto por Telegram."""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN no configurado.")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        return resp.json()
    except Exception as e:
        logger.error(f"Error enviando mensaje a Telegram: {e}")
        return None


def send_telegram_video(
    chat_id: str,
    video_path: str,
    caption: str = "",
    parse_mode: str = "HTML"
) -> Optional[Dict[str, Any]]:
    """
    Sube un video MP4 a Telegram usando multipart/form-data.
    """
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN no configurado.")
        return None

    v_path = Path(video_path)
    if not v_path.exists():
        logger.error(f"El archivo de video no existe: {video_path}")
        return None

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
    data = {
        "chat_id": chat_id,
        "caption": caption[:1024] if caption else "",  # Límite de caption en Telegram video
        "parse_mode": parse_mode,
        "supports_streaming": "true"
    }

    try:
        with open(v_path, "rb") as video_file:
            files = {"video": (v_path.name, video_file, "video/mp4")}
            logger.info(f"Subiendo video a Telegram ({v_path.stat().st_size / (1024*1024):.2f} MB)...")
            resp = requests.post(url, data=data, files=files, timeout=60)
            result = resp.json()
            if result.get("ok"):
                logger.info("✅ Video subido exitosamente a Telegram.")
                return result
            else:
                logger.error(f"Error en respuesta de Telegram: {result}")
                return None
    except Exception as e:
        logger.error(f"Excepción subiendo video: {e}")
        return None


def deliver_tiktok_pack(
    video_path: str,
    pick: Dict[str, Any],
    destination_chat_id: Optional[str] = None
) -> bool:
    """
    Despacha el paquete completo de publicación de TikTok a Telegram:
    1. Video .mp4 con preview.
    2. Tarjeta amigable con instrucciones simples para la novia de Carlos.
    3. Bloque de texto para copiar con un solo toque.
    """
    target = destination_chat_id or TIKTOK_CHAT_ID
    if not target:
        logger.error("No hay chat_id destino para el TikTok Pack.")
        return False

    v_path = Path(video_path)
    if not v_path.exists():
        logger.error(f"Video no encontrado: {video_path}")
        return False

    caption_tiktok = build_tiktok_caption(pick)
    ticket_id = pick.get("ticket_id", "RT-VERIFIED")
    home = pick.get("home_team", "")
    away = pick.get("away_team", "")

    # 1. Subir el video con un caption identificador
    video_summary = (
        f"🎬 <b>NUEVO CONTENIDO LISTO — OMNICANAL 3 EN 1</b> 🌮👑\n"
        f"⚽ <b>{home} vs {away}</b>\n"
        f"🎟️ Ticket: <code>{ticket_id}</code>\n"
        f"🌐 <i>Mismo video y mismo copy para TikTok, Instagram y Facebook.</i>"
    )
    res_vid = send_telegram_video(chat_id=target, video_path=str(v_path), caption=video_summary)
    if not res_vid or not res_vid.get("ok"):
        logger.error("Fallo al enviar el video a Telegram.")
        return False

    # 2. Tarjeta con las instrucciones claras para la publicación omnicanal
    instructions_msg = (
        f"📱 <b>GUÍA DE PUBLICACIÓN OMNICANAL (TIKTOK · INSTA · FACEBOOK)</b> 🌮👑\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"El contenido es el <b>mismo para las 3 redes</b>. Con 1 solo video y 1 solo texto abarcan todo:\n\n"
        f"📥 <b>Paso 1:</b> Guarda el video de arriba en la galería de tu celular.\n\n"
        f"🎵 <b>TikTok:</b>\n"
        f"• Toca <b>+ (Subir)</b>, selecciona el video y pega el texto de abajo.\n"
        f"• <i>Tip Algoritmo:</i> Si agregas sonido en tendencia, ponlo al 10% de volumen.\n\n"
        f"📸 <b>Instagram Reels:</b>\n"
        f"• Sube el video como Reel y pega el mismo texto.\n"
        f"• <i>Tip Acelerador:</i> Activa la opción <b>'Recomendar en Facebook'</b> para que se publique automáticamente en Facebook sin hacer nada extra.\n\n"
        f"📘 <b>Facebook:</b>\n"
        f"• Si no tienes vinculada la cuenta, súbelo como Facebook Reel a la página oficial con el mismo copy.\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 <i>Toca el recuadro de abajo para copiar el texto completo (1 toque):</i>"
    )
    send_telegram_message(chat_id=target, text=instructions_msg)


    # 3. Mensaje copiable con UN SOLO TOQUE (usando formato <code>)
    # En la app de Telegram en iOS y Android, al tocar texto dentro de <code> se copia al instante.
    clean_copy_block = f"<code>{caption_tiktok}</code>"
    send_telegram_message(chat_id=target, text=clean_copy_block)

    logger.info(f"✨ Pack TikTok enviado con éxito al chat {target}.")
    return True


if __name__ == "__main__":
    sample_pick = {
        "ticket_id": "RT-20260918-TIKTOK-001",
        "home_team": "América",
        "away_team": "Guadalajara",
        "league": "Liga MX",
        "pick": "Más de 8.5 Tiros de Esquina",
        "market_odds_american": "-115",
        "minimum_odds_american": "-125",
        "ev_percent": 6.8,
        "time": "21:00"
    }
    sample_video = REPO_ROOT / "lab" / "reel_cinematografico.mp4"
    if sample_video.exists():
        print(f"Probando envío de Pack TikTok con {sample_video}...")
        deliver_tiktok_pack(str(sample_video), sample_pick)
    else:
        print(f"Video {sample_video} no encontrado.")

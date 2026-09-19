import os
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

try:
    from backend.payment_review import classify_receipt
    from backend.membership_admin import is_active_subscription
except ModuleNotFoundError:  # Allows `python backend/ticket_listener.py`.
    from payment_review import classify_receipt
    from membership_admin import is_active_subscription

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")


TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
VIP_CHANNEL_ID = os.getenv("TELEGRAM_VIP_CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL_ID")
FREE_CHANNEL_ID = os.getenv("TELEGRAM_FREE_CHANNEL_ID", "")
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_ID") or os.getenv("TELEGRAM_CHAT_ID") or "0")
SUPABASE_ADMIN_USER_ID = os.getenv("SUPABASE_ADMIN_USER_ID", "")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TICKETS_DIR = PROJECT_ROOT / "frontend" / "public" / "tickets"
RECEIPTS_DIR = Path(
    os.getenv("PRIVATE_RECEIPTS_DIR", PROJECT_ROOT / "backend" / "private_receipts")
)
TICKETS_DIR.mkdir(parents=True, exist_ok=True)
RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

OFFSET_FILE = os.path.join(os.path.dirname(__file__), ".telegram_offset")

def get_offset():
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE, "r") as f:
            try:
                return int(f.read().strip())
            except Exception:
                return 0
    return 0

def save_offset(offset):
    with open(OFFSET_FILE, "w") as f:
        f.write(str(offset))

def telegram_api(method, payload):
    """Llamada genérica segura a la API de Telegram."""
    if not TELEGRAM_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"Error Telegram API ({method}): {e}")
        return None

TEAM_GROUP_FILE = PROJECT_ROOT / "data" / "team_group_id.json"

def get_team_group_id():
    """Recupera el chat_id del grupo privado de coordinación del equipo."""
    if TEAM_GROUP_FILE.exists():
        try:
            data = json.loads(TEAM_GROUP_FILE.read_text(encoding="utf-8"))
            return data.get("team_group_id")
        except Exception:
            return None
    return None

def save_team_group_id(chat_id, title=""):
    """Persiste el ID del grupo privado para envío directo de material y reels."""
    try:
        TEAM_GROUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        TEAM_GROUP_FILE.write_text(json.dumps({
            "team_group_id": chat_id,
            "title": title,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, indent=2), encoding="utf-8")
        print(f"👥 Grupo de equipo guardado: '{title}' (ID: {chat_id})")
    except Exception as e:
        print(f"⚠️ Error guardando team group ID: {e}")

def enviar_video_telegram(chat_id, video_path, caption="", parse_mode="HTML"):
    """Envía un archivo de video MP4 directamente a un chat o grupo de Telegram."""
    if not TELEGRAM_TOKEN or not Path(video_path).exists():
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendVideo"
        with open(video_path, "rb") as f:
            files = {"video": (Path(video_path).name, f, "video/mp4")}
            data = {"chat_id": chat_id, "caption": caption}
            if parse_mode:
                data["parse_mode"] = parse_mode
            res = requests.post(url, data=data, files=files, timeout=60)
            return res.status_code == 200
    except Exception as e:
        print(f"Error enviando video a {chat_id}: {e}")
        return False

def enviar_foto_local_telegram(chat_id, photo_path, caption="", parse_mode="HTML"):
    """Envía una imagen JPEG/PNG local directamente a un chat o grupo de Telegram."""
    if not TELEGRAM_TOKEN or not Path(photo_path).exists():
        return False
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            files = {"photo": (Path(photo_path).name, f, "image/jpeg")}
            data = {"chat_id": chat_id, "caption": caption}
            if parse_mode:
                data["parse_mode"] = parse_mode
            res = requests.post(url, data=data, files=files, timeout=40)
            return res.status_code == 200
    except Exception as e:
        print(f"Error enviando foto a {chat_id}: {e}")
        return False

def procesar_comandos_suite(chat_id, raw_text, texto) -> bool:
    """Procesa comandos de la suite de contenido, copies, stories, carruseles, alertas y banca."""
    # 1. COPIES & HASHTAGS VIRALES PARA REDES
    if texto.startswith(('/copy', 'copy')):
        partes = raw_text.split(maxsplit=1)
        tema = partes[1] if len(partes) > 1 else "ligamx"
        try:
            from backend.viral_copy_assistant import get_copy_for_theme
            msg = get_copy_for_theme(tema)
            responder(chat_id, msg)
        except Exception as e:
            responder(chat_id, f"⚠️ Error generando copy: {e}")
        return True

    elif texto in ('/hashtags', '/tags', 'hashtags', 'tags'):
        try:
            from backend.viral_copy_assistant import get_general_hashtags
            responder(chat_id, get_general_hashtags())
        except Exception as e:
            responder(chat_id, f"⚠️ Error obteniendo hashtags: {e}")
        return True

    # 2. GENERADOR DE STORIES VERTICALES 9:16 (1080x1920)
    elif texto in ('/story', '/cartelera', 'story', 'cartelera'):
        responder(chat_id, "🎨 <b>Generando Historia Vertical de Cartelera (1080x1920 px)...</b>")
        try:
            from backend.generate_daily_stories import render_daily_story
            story_path = render_daily_story()
            caption_story = (
                "🌮👑 <b>CARTELERA DEL DÍA — HISTORIA VERTICAL (1080x1920)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "📱 Descarga esta imagen y súbela directo a <b>Instagram Stories & Facebook Stories</b> con el sticker de link a reytacopicks.com.\n\n"
                "<i>Diseño optimizado para alta retención visual.</i>"
            )
            enviar_foto_local_telegram(chat_id, story_path, caption=caption_story)
        except Exception as e:
            responder(chat_id, f"⚠️ Error generando story: {e}")
        return True

    # 3. GENERADOR DE CARRUSEL INSTAGRAM (4 SLIDES)
    elif texto in ('/carrusel', '/carousel', 'carrusel', 'carousel'):
        responder(chat_id, "📚 <b>Generando Carrusel Educativo para Instagram Feed (4 Slides 1080x1350)...</b>")
        try:
            from backend.generate_instagram_carousel import generate_instagram_carousel
            slides = generate_instagram_carousel()
            for i, s_path in enumerate(slides, 1):
                caption_slide = f"📸 <b>Slide {i} de {len(slides)}</b> — Carrusel Rey Taco Picks"
                enviar_foto_local_telegram(chat_id, s_path, caption=caption_slide)
            responder(chat_id, "✅ <b>Carrusel completo entregado.</b> Listo para publicar como álbum en Instagram con formato 4:5.")
        except Exception as e:
            responder(chat_id, f"⚠️ Error generando carrusel: {e}")
        return True

    # 4. ALERTA DE MERCADO PLAYDOIT (+EV Y DESFASE)
    elif texto in ('/alerta_mercado', '/mercado', '/desfase', 'alerta_mercado'):
        try:
            from backend.market_scanner import get_random_or_latest_market_alert
            alert = get_random_or_latest_market_alert()
            responder(chat_id, alert.to_telegram_alert())
        except Exception as e:
            responder(chat_id, f"⚠️ Error escaneando mercado: {e}")
        return True

    # 5. CIERRE DE JORNADA & RECAP NOCTURNO
    elif texto in ('/recap', '/cierre', '/balance_hoy', 'recap'):
        try:
            from backend.daily_recap_engine import calculate_daily_summary, format_daily_recap_telegram, format_instagram_story_copy
            summary = calculate_daily_summary()
            msg_telegram = format_daily_recap_telegram(summary)
            msg_ig = format_instagram_story_copy(summary)
            responder(chat_id, msg_telegram)
            responder(chat_id, f"📋 <b>TEXTO LISTO PARA HISTORIA DE INSTAGRAM:</b>\n<code>{msg_ig}</code>")
        except Exception as e:
            responder(chat_id, f"⚠️ Error calculando recap: {e}")
        return True

    # 6. PARLAY VIVO & SUGERENCIA DE CASHOUT
    elif texto in ('/cashout', '/parlay_vivo', 'cashout'):
        try:
            from backend.live_parlay_monitor import check_active_live_parlays
            parlays = check_active_live_parlays()
            for p in parlays:
                responder(chat_id, p.format_cashout_alert())
        except Exception as e:
            responder(chat_id, f"⚠️ Error consultando parlays vivos: {e}")
        return True

    # 7. CALCULADORA DE BANCA (KELLY)
    elif texto.startswith(('/banca', '/bankroll', 'banca')):
        partes = raw_text.split()
        monto = 2000.0
        if len(partes) > 1:
            try:
                monto = float(partes[1].replace("$", "").replace(",", ""))
            except Exception:
                monto = 2000.0
        
        u_cons = monto * 0.010
        u_mod = monto * 0.015
        u_agr = monto * 0.020
        max_stake = monto * 0.030

        resp = (
            f"🏦 <b>CALCULADORA DE BANCA INSTITUCIONAL</b> 🌮👑\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>Bankroll Total en Playdoit:</b> ${monto:,.2f} MXN\n\n"
            f"⚖️ <b>TAMAÑO RECOMENDADO DE 1 UNIDAD (1 U):</b>\n"
            f"• 🛡️ <b>Conservador (1.0%):</b> <code>${u_cons:,.2f} MXN</code> (Recomendado para novatos)\n"
            f"• ⚖️ <b>Moderado / Rey Taco (1.5%):</b> <code>${u_mod:,.2f} MXN</code> (Estrategia oficial)\n"
            f"• 🚀 <b>Dinámico (2.0%):</b> <code>${u_agr:,.2f} MXN</code> (Alta tolerancia)\n\n"
            f"🚫 <b>LÍMITE MÁXIMO POR JUGADA:</b> <code>${max_stake:,.2f} MXN</code> (3.0% del capital)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>Regla sagrada: Jamás subas el valor de la unidad para perseguir una pérdida. "
            f"La ventaja matemática (+EV) se cobra con paciencia y constancia.</i>"
        )
        responder(chat_id, resp)
        return True

    return False

def get_updates(offset=0):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset={offset}&timeout=20"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data.get('result', [])
    except TimeoutError:
        return []
    except Exception as e:
        if 'timed out' in str(e).lower():
            return []
        print(f"Error obteniendo updates: {e}")
        return []

def procesar_nuevo_miembro(message):
    """Detecta cuando el bot o nuevos integrantes entran al grupo de coordinación."""
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_title = chat.get("title", "Grupo Rey Taco")
    chat_type = chat.get("type", "")
    
    if chat_type not in ("group", "supergroup") or not chat_id:
        return

    save_team_group_id(chat_id, chat_title)
    
    bienvenida = (
        "🌮👑 <b>¡GRUPO DE PRODUCCIÓN & ENTREGAS CONECTADO!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "¡Hola Carlos y bienvenida! 👑🌮\n\n"
        "Este grupo ha quedado registrado automáticamente como el <b>Canal Oficial de Entrega de Contenido</b>.\n\n"
        "Por aquí les estaré compartiendo en directo:\n"
        "🎬 <b>Videos y Reels con música</b> para TikTok, Instagram y Facebook.\n"
        "📊 <b>Reportes cuantitativos y auditoría SHA-256</b>.\n"
        "🎯 <b>Alertas de picks y valor (+EV)</b> en tiempo real.\n\n"
        "<i>¡El bot está activo 24/7 en la nube listo para trabajar con ustedes!</i> 🚀"
    )
    responder(chat_id, bienvenida)
    
    if ADMIN_CHAT_ID and chat_id != ADMIN_CHAT_ID:
        responder(
            ADMIN_CHAT_ID,
            f"🔔 <b>¡Nuevo grupo de equipo conectado!</b>\n"
            f"• <b>Título:</b> {chat_title}\n"
            f"• <b>ID:</b> <code>{chat_id}</code>\n"
            f"Registrado con éxito para entrega de videos y material."
        )


def download_photo(file_id, save_path):
    """Descarga una foto de Telegram usando el file_id."""
    try:
        res = telegram_api("getFile", {"file_id": file_id})
        if res and res.get('ok'):
            file_path = res['result']['file_path']
            download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            urllib.request.urlretrieve(download_url, save_path)
            return True
        return False
    except Exception as e:
        print(f"Error descargando foto: {e}")
        return False

def reenviar_a_canal(file_id, caption=""):
    """Reenvía la foto a AMBOS canales: Canal VIP y Canal Gratuito."""
    canales = list(set([c for c in [VIP_CHANNEL_ID, FREE_CHANNEL_ID, CHANNEL_ID] if c]))
    for cid in canales:
        try:
            telegram_api("sendPhoto", {
                "chat_id": cid,
                "photo": file_id,
                "caption": caption or "🏆 ¡Ticket Ganador! Otra victoria más para Rey Taco Picks 👑🌮"
            })
            print(f"   📢 Foto de ticket enviada exitosamente a canal {cid}.")
        except Exception as e:
            print(f"   ⚠️ Error enviando a canal {cid}: {e}")

def responder(chat_id, texto, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": texto}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return telegram_api("sendMessage", payload)

def responder_bienvenida(chat_id):
    """Envía mensaje institucional de bienvenida con botones de navegación a Stripe."""
    texto = (
        "👑 <b>REY TACO PICKS — SPORTS INTELLIGENCE & MODELOS CUANTITATIVOS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "¡Hola! Bienvenido al sistema institucional de <b>Rey Taco Picks</b> 🌮.\n\n"
        "Operamos con rigor matemático y analítica cuantitativa:\n"
        "📊 <b>Modelos +EV:</b> Detección algorítmica de cuotas desalineadas en Playdoit.\n"
        "🛡️ <b>Auditoría SHA-256:</b> Cada selección se sella antes del partido en un ledger inmutable. Cero picks borrados, 100% transparencia.\n"
        "⚖️ <b>Gestión Kelly:</b> Asignación rigurosa de banca por unidades.\n\n"
        "🔒 <b>Pagos y accesos 100% seguros y automatizados vía Stripe</b> (Tarjeta de Débito, Crédito, Apple Pay).\n\n"
        "👇 <b>Selecciona una opción del menú:</b>"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "👑 Planes VIP en Stripe ($129 / $349)", "callback_data": "menu_vip"},
                {"text": "📢 Canal Gratuito", "url": "https://t.me/ReyTacoPicksFree"}
            ],
            [
                {"text": "🎯 Picks de Hoy", "callback_data": "menu_picks"},
                {"text": "📊 Auditoría & Récord", "url": "https://reytacopicks.com/auditoria"}
            ],
            [
                {"text": "🌐 Web Oficial & Checkout", "url": "https://reytacopicks.com/#vip"},
                {"text": "💬 Soporte WhatsApp", "url": "https://wa.me/525639331102?text=Hola,%20tengo%20una%20duda%20sobre%20Rey%20Taco%20Picks"}
            ]
        ]
    }
    responder(chat_id, texto, keyboard)

def responder_vip(chat_id):
    """Presenta los planes oficiales 100% integrados y procesados en Stripe."""
    texto = (
        "👑 <b>PLANES VIP — REY TACO PICKS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Accede a nuestra cartera algorítmica completa de valor (+EV), córners, props de jugadores y alertas instantáneas.\n\n"
        "🎟️ <b>PASE SEMANAL (7 DÍAS) — $129 MXN</b>\n"
        "• Acceso total a todas las selecciones y ventanas por 7 días.\n"
        "• Pago único, sin renovaciones obligatorias.\n"
        "• Ideal para validar el rendimiento y metodología con bajo riesgo.\n\n"
        "👑 <b>VIP MENSUAL (RECOMENDADO) — $349 MXN / mes</b>\n"
        "• Cartera completa 24/7 (Fútbol europeo, Liga MX, MLB, KBO, NPB).\n"
        "• Cuota Mínima Aceptable, veto de cuota y stake Kelly fraccional.\n"
        "• Alertas prioritarias directas antes del movimiento de líneas.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 <b>PAGOS 100% SEGUROS & CIFRADOS CON STRIPE:</b>\n"
        "Todas las transacciones se realizan a través de la infraestructura global de <b>Stripe</b>.\n"
        "Acepta Tarjeta de Débito, Crédito, Apple Pay y Google Pay.\n\n"
        "⚡ <b>Activación Inmediata:</b> Al completar tu suscripción en línea, tu cuenta queda vinculada y tu acceso al Canal VIP se habilita automáticamente en segundos.\n\n"
        "👉 <b>Suscríbete en nuestra web oficial:</b>\n"
        "https://reytacopicks.com/#vip"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🎟️ Pagar Semanal $129 MXN (Stripe)", "url": "https://reytacopicks.com/#vip"},
                {"text": "👑 Suscribirme VIP $349 MXN (Stripe)", "url": "https://reytacopicks.com/#vip"}
            ],
            [
                {"text": "🌐 Checkout Seguro en la Web", "url": "https://reytacopicks.com/#vip"}
            ],
            [
                {"text": "📢 Canal Gratuito", "url": "https://t.me/ReyTacoPicksFree"},
                {"text": "🔙 Menú Principal", "callback_data": "menu_start"}
            ]
        ]
    }
    responder(chat_id, texto, keyboard)

def responder_picks(chat_id):
    """Informa dónde consultar la cartera diaria."""
    texto = (
        "🎯 <b>PRONÓSTICOS DE HOY — REY TACO PICKS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Publicamos nuestras selecciones en 4 ventanas estratégicas diarias (00:00, 06:00, 12:00 y 18:00 CDMX).\n\n"
        "📢 <b>Selección Gratuita del Día:</b>\n"
        "Se libera a diario en nuestro canal abierto:\n"
        "👉 @ReyTacoPicksFree\n\n"
        "👑 <b>Cartera Completa VIP:</b>\n"
        "Todas las selecciones con valor esperado positivo (+EV), cuota mínima y Kelly están disponibles en el <b>Canal VIP</b> y en la web:\n"
        "👉 https://reytacopicks.com"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📢 Ir al Canal Gratuito", "url": "https://t.me/ReyTacoPicksFree"},
                {"text": "👑 Adquirir VIP", "callback_data": "menu_vip"}
            ],
            [
                {"text": "🌐 Ver Cartelera en la Web", "url": "https://reytacopicks.com"},
                {"text": "🔙 Menú Principal", "callback_data": "menu_start"}
            ]
        ]
    }
    responder(chat_id, texto, keyboard)

def responder_auditoria(chat_id):
    """Explica el sistema de auditoría criptográfica SHA-256."""
    texto = (
        "🛡️ <b>SISTEMA DE AUDITORÍA CRIPTOGRÁFICA SHA-256</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "En <b>Rey Taco Picks</b> no vendemos certeza ni prometemos 100% de victorias mágicas. <b>Medimos valor y gestionamos riesgo</b>.\n\n"
        "🔗 <b>Trazabilidad Matemática:</b>\n"
        "• Cada pronóstico genera un bloque criptográfico SHA-256 encadenado ANTES del inicio del evento.\n"
        "• Incluye cuota de mercado, Cuota Mínima Aceptable y Edge (+EV).\n"
        "• Cero selecciones borradas, cero resultados alterados.\n"
        "• Calificación automatizada e imparcial mediante feeds oficiales.\n\n"
        "📊 Consulta el balance histórico, ROI y bloques en tiempo real:\n"
        "👉 https://reytacopicks.com/auditoria"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📊 Explorador de Auditoría", "url": "https://reytacopicks.com/auditoria"},
                {"text": "📢 Canal Gratuito", "url": "https://t.me/ReyTacoPicksFree"}
            ],
            [
                {"text": "🔙 Menú Principal", "callback_data": "menu_start"}
            ]
        ]
    }
    responder(chat_id, texto, keyboard)

def responder_ayuda(chat_id):
    """Canal directo de atención y soporte."""
    texto = (
        "💬 <b>ATENCIÓN AL CLIENTE & SOPORTE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "¿Tienes dudas sobre cómo seguir los pronósticos, métodos de pago o activar tu acceso VIP?\n\n"
        "Estamos listos para ayudarte de inmediato:\n"
        "📲 <b>WhatsApp:</b> +52 56 3933 1102\n"
        "🌐 <b>Web:</b> https://reytacopicks.com\n\n"
        "¡Bienvenido a la comunidad cuantitativa de Rey Taco Picks! 🌮👑"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "📲 Abrir Chat de WhatsApp", "url": "https://wa.me/525639331102?text=Hola,%20tengo%20una%20duda%20sobre%20Rey%20Taco%20Picks"},
                {"text": "👑 Planes VIP", "callback_data": "menu_vip"}
            ],
            [
                {"text": "🔙 Menú Principal", "callback_data": "menu_start"}
            ]
        ]
    }
    responder(chat_id, texto, keyboard)

def responder_publico(chat_id):
    """Alias para la respuesta de bienvenida general."""
    responder_bienvenida(chat_id)


def procesar_vinculacion_telegram(message, raw_text):
    """Consume a short-lived web token and binds this Telegram account once."""
    if not raw_text.startswith("/start link_"):
        return False
    if not supabase:
        responder(message.get("chat", {}).get("id"), "⚠️ La vinculación no está disponible en este momento.")
        return True
    user = message.get("from", {})
    token = raw_text.removeprefix("/start link_").strip()
    try:
        result = supabase.rpc("consume_telegram_link_token", {
            "raw_token": token,
            "new_telegram_id": str(user.get("id", "")),
            "new_telegram_username": user.get("username"),
        }).execute()
        linked = bool(result.data)
        responder(
            message.get("chat", {}).get("id"),
            "✅ Tu cuenta de Telegram quedó vinculada a Rey Taco Picks." if linked
            else "⚠️ El enlace expiró o ya fue utilizado. Genera uno nuevo desde tu cuenta web.",
        )
    except Exception as error:
        print(f"Error vinculando Telegram: {error}")
        responder(message.get("chat", {}).get("id"), "⚠️ No pudimos vincular la cuenta. Genera un enlace nuevo.")
    return True

def buscar_usuario_auth_por_correo(email):
    """Resolve an Auth user with the server-only admin API, not a profile column."""
    if not supabase:
        return None
    target = str(email).strip().lower()
    for page in range(1, 101):
        users = supabase.auth.admin.list_users(page=page, per_page=100)
        match = next((user for user in users if str(user.email or "").lower() == target), None)
        if match:
            return str(match.id)
        if len(users) < 100:
            break
    return None

def verificar_usuario_vip(telegram_id=None, username=None):
    """Verifica en Supabase si el usuario tiene suscripción VIP activa."""
    if not supabase:
        return False
    try:
        profile = None
        if telegram_id:
            res = supabase.table("profiles").select("id").eq("telegram_id", str(telegram_id)).limit(1).execute()
            profile = res.data[0] if res.data else None
        if profile:
            sub = supabase.rpc("is_active_subscriber", {"check_user": profile["id"]}).execute()
            return sub.data is True
    except Exception as e:
        print(f"Error verificando usuario VIP en Supabase: {e}")
    return False

def procesar_solicitud_union(join_req):
    """Procesa una solicitud de usuario para unirse al canal VIP con aprobación obligatoria."""
    user = join_req.get('from', {})
    chat = join_req.get('chat', {})
    user_id = user.get('id')
    username = user.get('username', 'Sin username')
    first_name = user.get('first_name', 'Usuario')
    chat_id = chat.get('id')

    print(f"\n🚪 [SOLICITUD DE UNIÓN] Usuario: {first_name} (@{username}, ID: {user_id}) en Canal {chat_id}")

    # Verificar si es VIP en Supabase
    es_vip = verificar_usuario_vip(telegram_id=user_id, username=username)

    if es_vip:
        # APROBAR AUTOMÁTICAMENTE
        telegram_api("approveChatJoinRequest", {"chat_id": chat_id, "user_id": user_id})
        responder(user_id, "👑 ¡Felicidades! Tu suscripción VIP fue verificada. Bienvenido al Canal VIP Oficial de Rey Taco Picks 🌮.")
        responder(ADMIN_CHAT_ID, f"✅ [VIP AUTO-APROBADO] @{username} ({first_name}, ID: {user_id}) fue aceptado automáticamente en el Canal VIP.")
        print(f"   ✅ Usuario {user_id} aprobado automáticamente.")
    else:
        # RECHAZAR O MANTENER PENDIENTE Y MANDARLE MENSAJE DE PAGO EN STRIPE
        telegram_api("declineChatJoinRequest", {"chat_id": chat_id, "user_id": user_id})
        
        # Enviar mensaje privado con datos de pago en Stripe
        msg_pago = (
            f"👑 ¡Hola <b>{first_name}</b>! Para ingresar al <b>Canal VIP Oficial de Rey Taco Picks</b> 🌮, necesitas una membresía activa procesada por Stripe.\n\n"
            "Elige tu modalidad con activación automática inmediata:\n"
            "🎟️ <b>Pase Semanal (7 días):</b> $129 MXN\n"
            "👑 <b>Suscripción Mensual VIP:</b> $349 MXN / mes\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔒 <b>PAGO 100% SEGURO CON STRIPE:</b>\n"
            "Paga en línea en segundos con Tarjeta de Débito, Crédito o Apple Pay:\n"
            "👉 https://reytacopicks.com/#vip\n\n"
            "⚡ <i>En cuanto tu pago es procesado por Stripe, tu acceso al Canal VIP se habilita automáticamente.</i>"
        )
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🎟️ Pagar Semanal ($129 MXN)", "url": "https://reytacopicks.com/#vip"},
                    {"text": "👑 Suscribirme al VIP ($349 MXN)", "url": "https://reytacopicks.com/#vip"}
                ],
                [
                    {"text": "📢 Canal Gratuito", "url": "https://t.me/ReyTacoPicksFree"},
                    {"text": "💬 Dudas por WhatsApp", "url": "https://wa.me/525639331102?text=Hola,%20tengo%20una%20duda%20para%20pagar%20mi%20VIP%20en%20Stripe"}
                ]
            ]
        }
        responder(user_id, msg_pago, keyboard, parse_mode="HTML")
        
        # Notificar a Carlos en privado
        responder(ADMIN_CHAT_ID, 
            f"ℹ️ <b>[SOLICITUD VIP CANAL]</b>\n\n"
            f"👤 <b>Usuario:</b> {first_name} (@{username})\n"
            f"🆔 <b>ID Telegram:</b> <code>{user_id}</code>\n"
            f"❌ <b>Estado:</b> Sin suscripción activa en Stripe.\n"
            f"🤖 Se le envió el enlace directo a Stripe en la web.",
            parse_mode="HTML"
        )
        print(f"   🚫 Solicitud de {user_id} denegada (sin suscripción Stripe).")

def procesar_nuevo_miembro(message):
    """Detecta si alguien entra al canal VIP sin autorización y lo expulsa."""
    chat = message.get('chat', {})
    chat_id = chat.get('id')
    
    # Solo auditar si es en el canal VIP
    if str(chat_id) == str(VIP_CHANNEL_ID):
        new_members = message.get('new_chat_members', [])
        for m in new_members:
            user_id = m.get('id')
            username = m.get('username', 'Sin username')
            first_name = m.get('first_name', 'Usuario')
            
            if user_id == ADMIN_CHAT_ID:
                continue
                
            es_vip = verificar_usuario_vip(telegram_id=user_id, username=username)
            if not es_vip:
                print(f"🚨 [EXPULSIÓN] Usuario no autorizado en canal VIP: {first_name} (@{username})")
                # Expulsar
                telegram_api("banChatMember", {"chat_id": chat_id, "user_id": user_id})
                telegram_api("unbanChatMember", {"chat_id": chat_id, "user_id": user_id})
                
                responder(ADMIN_CHAT_ID, 
                    f"🚫 [USUARIO EXPULSADO DEL CANAL VIP]\n\n"
                    f"👤 {first_name} (@{username}, ID: `{user_id}`)\n"
                    f"Fue expulsado automáticamente porque no tiene suscripción VIP pagada."
                )

def procesar_comprobante_cliente(update):
    """Procesa una foto recibida de un cliente en Telegram y lo orienta a Stripe."""
    message = update.get('message', {})
    user = message.get('from', {})
    chat_id = message.get('chat', {}).get('id')
    user_id = user.get('id', chat_id)
    username = user.get('username', 'Sin username')
    first_name = user.get('first_name', 'Usuario')
    photos = message.get('photo', [])
    
    if not photos:
        return
        
    best_photo = photos[-1]
    file_id = best_photo['file_id']
    save_path = RECEIPTS_DIR / f"comprobante_{user_id}_{int(time.time())}.jpg"
    
    print(f"\n💳 [IMAGEN RECIBIDA] de {first_name} (@{username}, ID: {user_id})")
    
    if download_photo(file_id, str(save_path)):
        texto_ocr = ""
        try:
            from PIL import Image
            import pytesseract
            img = Image.open(save_path)
            texto_ocr = pytesseract.image_to_string(img).lower()
        except Exception:
            pass
            
        review = classify_receipt(texto_ocr)
        review_id = None
        if supabase:
            try:
                linked_profile = supabase.table("profiles").select("id").eq(
                    "telegram_id", str(user_id)
                ).limit(1).execute()
                review_record = supabase.table("payment_reviews").insert({
                    "user_id": linked_profile.data[0]["id"] if linked_profile.data else None,
                    "telegram_id": str(user_id),
                    "telegram_username": username.replace("@", "").lower(),
                    "status": review.status,
                    "detected_amount": review.detected_amount,
                    "detected_bank": review.detected_bank,
                    "receipt_filename": save_path.name,
                }).execute()
                review_id = review_record.data[0]["id"] if review_record.data else None
            except Exception as e:
                print(f"   ⚠️ No se pudo registrar payment_reviews: {e}")

        plan_desc = {
            "weekly": "$129 MXN (Pase Semanal 7D)",
            "monthly": "$349 MXN (VIP Mensual)",
            "legacy_monthly": "$299 MXN (Legacy)",
        }.get(review.detected_plan, "No detectado en OCR")

        if ADMIN_CHAT_ID:
            telegram_api("sendPhoto", {
                "chat_id": ADMIN_CHAT_ID,
                "photo": file_id,
                "caption": (
                    "📩 <b>[IMAGEN/COMPROBANTE RECIBIDO]</b>\n"
                    f"👤 {first_name} (@{username}, ID: <code>{user_id}</code>)\n"
                    f"💵 <b>Plan detectado:</b> {plan_desc}\n"
                    f"🏦 <b>Banco detectado:</b> {'Sí' if review.detected_bank else 'No'}\n\n"
                    f"📝 ID Registro: <code>{review_id or 'no registrada'}</code>\n\n"
                    "ℹ️ Se le notificó al usuario que las activaciones son 100% en línea vía Stripe."
                ),
                "parse_mode": "HTML"
            })
        responder(
            user_id,
            "ℹ️ <b>PAGOS Y ACTIVACIÓN AUTOMÁTICA VÍA STRIPE</b>\n\n"
            "En <b>Rey Taco Picks</b> todas las membresías se activan de forma 100% automática e instantánea a través de <b>Stripe</b> para proteger tu compra con cifrado bancario.\n\n"
            "👉 <b>Activa tu membresía aquí:</b>\n"
            "https://reytacopicks.com/#vip\n\n"
            "Acepta Tarjeta de Débito, Crédito, Apple Pay y Google Pay. Al pagar, tu cuenta y acceso al Canal VIP se habilitan de inmediato.",
            reply_markup={
                "inline_keyboard": [
                    [{"text": "🔒 Ir a Pagar en Stripe", "url": "https://reytacopicks.com/#vip"}],
                    [{"text": "💬 Soporte WhatsApp", "url": "https://wa.me/525639331102?text=Hola,%20tengo%20una%20duda%20sobre%20mi%20pago"}]
                ]
            },
            parse_mode="HTML"
        )

def procesar_foto(update):
    """Procesa una foto recibida del admin."""
    message = update.get('message', {})
    chat_id = message.get('chat', {}).get('id')
    caption = message.get('caption', '')
    photos = message.get('photo', [])
    
    if not photos:
        return
    
    best_photo = photos[-1]
    file_id = best_photo['file_id']
    
    timestamp = int(time.time())
    filename = f"ticket_{timestamp}.jpg"
    save_path = os.path.join(TICKETS_DIR, filename)
    
    print(f"\n📸 Foto recibida de chat {chat_id}")
    
    if download_photo(file_id, save_path):
        print(f"   ✅ Guardada: {save_path}")
        
        manifest_path = os.path.join(TICKETS_DIR, "manifest.json")
        manifest_list = []
        if os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_list = json.load(f)
            except Exception:
                manifest_list = []
        if filename not in manifest_list:
            manifest_list.insert(0, filename)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_list, f, indent=2)
            print("   📁 manifest.json actualizado.")
        
        if supabase:
            try:
                supabase.table("tickets_ganadores").insert({
                    "archivo": filename,
                    "caption": caption or "Ticket Ganador",
                    "file_id": file_id,
                    "file_unique_id": best_photo.get("file_unique_id", ""),
                    "telegram_chat_id": chat_id,
                    "received_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
                print("   ✅ Registrado en Supabase.")
            except Exception as e:
                print(f"   ⚠️ Error en Supabase (tabla opcional): {e}")
        
        # 1. Verificar si hay un pick pendiente esperando obligatoriamente la foto de Playdoit
        try:
            from backend.interactive_telegram_dispatcher import (
                get_latest_waiting_pick,
                mark_pick_photo_received,
                format_public_channel_message
            )
            pending_pick = get_latest_waiting_pick()
        except Exception as e:
            print(f"⚠️ Error verificando picks pendientes: {e}")
            pending_pick = None

        if pending_pick:
            ticket_id = pending_pick.get("ticket_id", "RT-VERIFIED")
            mark_pick_photo_received(ticket_id, filename)
            
            # Publicar a los canales con la FOTO adjunta
            pub_caption = format_public_channel_message(pending_pick)
            canales = list(set([c for c in [VIP_CHANNEL_ID, FREE_CHANNEL_ID, CHANNEL_ID] if c]))
            for c in canales:
                telegram_api("sendPhoto", {
                    "chat_id": c,
                    "photo": file_id,
                    "caption": pub_caption,
                    "parse_mode": "HTML"
                })

            # Sellar en el Ledger Criptográfico
            try:
                from backend.audit_ledger import record_pick_published, AUDIT_LEDGER_PATH
                record_pick_published(ticket_id, channel="TELEGRAM_WITH_PHOTO", ledger_path=AUDIT_LEDGER_PATH)
            except Exception as e:
                print(f"⚠️ Error registrando en ledger: {e}")

            confirmacion = (
                f"🌮👑 <b>¡BOLETO DE PLAYDOIT VINCULADO & PUBLICADO!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎟️ <b>Ticket ID:</b> <code>{ticket_id}</code>\n"
                f"📸 <b>Foto oficial:</b> <code>{filename}</code>\n"
                f"📢 <b>Publicado en canales:</b> Con foto del boleto adjunta.\n"
                f"🔒 <b>Audit Ledger:</b> Sellado criptográficamente SHA-256.\n\n"
                f"<i>¡La regla de foto obligatoria se cumplió al 100%!</i> 🚀"
            )
            responder(chat_id, confirmacion)

            # Notificar también al grupo de equipo si es diferente
            t_gid = get_team_group_id()
            if t_gid and t_gid != chat_id:
                responder(t_gid, f"📸 <b>¡Nuevo pick verificado con foto de Playdoit!</b>\nTicket ID: <code>{ticket_id}</code>")

        else:
            # Flujo estándar de boleto libre (ganador o comprobante de auditoría)
            reenviar_a_canal(file_id, caption)
            responder(chat_id, f"✅ ¡Ticket guardado en la galería y publicado en el canal!\nArchivo: {filename}")
    else:
        responder(chat_id, "❌ Error al descargar la foto. Intenta de nuevo.")

def configurar_comandos_bot():
    """Registra el menú oficial de comandos en Telegram."""
    comandos = [
        {"command": "start", "description": "👑 Menú principal y bienvenida"},
        {"command": "vip", "description": "💎 Planes VIP ($129 y $349 MXN)"},
        {"command": "picks", "description": "🎯 Dónde ver los pronósticos de hoy"},
        {"command": "auditoria", "description": "🛡️ Registro y balance SHA-256"},
        {"command": "ayuda", "description": "💬 Contactar soporte por WhatsApp"},
    ]
    res = telegram_api("setMyCommands", {"commands": comandos})
    if res and res.get("ok"):
        print("   🤖 Menú de comandos registrado con éxito en Telegram.")

def procesar_callback_query(cb):
    """Maneja las pulsaciones de botones inline de navegación o aprobación de despacho."""
    cb_id = cb.get("id")
    data = cb.get("data", "")
    user = cb.get("from", {})
    user_id = str(user.get("id", ""))
    message = cb.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not data:
        return

    # Navegación para usuarios
    if data == "menu_start":
        responder_bienvenida(chat_id)
        telegram_api("answerCallbackQuery", {"callback_query_id": cb_id})
        return
    elif data == "menu_vip":
        responder_vip(chat_id)
        telegram_api("answerCallbackQuery", {"callback_query_id": cb_id})
        return
    elif data == "menu_picks":
        responder_picks(chat_id)
        telegram_api("answerCallbackQuery", {"callback_query_id": cb_id})
        return
    elif data == "menu_auditoria":
        responder_auditoria(chat_id)
        telegram_api("answerCallbackQuery", {"callback_query_id": cb_id})
        return

    # Botones de control administrativo para Carlos (Despacho interactivo)
    if data.startswith(("pub_", "disc_", "tiktok_")):
        if ADMIN_CHAT_ID and user_id != str(ADMIN_CHAT_ID):
            telegram_api("answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": "⛔ No autorizado.",
                "show_alert": True
            })
            return

        try:
            from backend.interactive_telegram_dispatcher import (
                execute_publish_to_channel,
                execute_discard_pick,
                PENDING_DISPATCHES,
                DISPATCH_LOCK
            )
            if data.startswith("pub_"):
                tid = data.replace("pub_", "")
                execute_publish_to_channel(tid, reason="MANUAL_APPROVAL")
                telegram_api("answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": "📢 ¡Pick publicado exitosamente en el canal!"
                })
            elif data.startswith("disc_"):
                tid = data.replace("disc_", "")
                execute_discard_pick(tid)
                telegram_api("answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": "❌ Pick descartado. No se publicará."
                })
            elif data.startswith("tiktok_"):
                tid = data.replace("tiktok_", "")
                telegram_api("answerCallbackQuery", {
                    "callback_query_id": cb_id,
                    "text": "🎬 Generando y enviando Pack TikTok..."
                })
                from backend.tiktok_video_generator import render_pick_tiktok_reel
                from backend.tiktok_pack_delivery import deliver_tiktok_pack
                with DISPATCH_LOCK:
                    p_data = PENDING_DISPATCHES.get(tid, {}).get("pick")
                if p_data:
                    vid_path = render_pick_tiktok_reel(p_data, duration_sec=6)
                    deliver_tiktok_pack(str(vid_path), p_data)
        except Exception as e:
            print(f"⚠️ Error procesando callback admin: {e}")
            telegram_api("answerCallbackQuery", {
                "callback_query_id": cb_id,
                "text": f"Error: {e}"
            })

def main():
    print("="*60)
    print("🛡️  REY TACO PICKS — Guardian & Ticket Listener 24/7")
    print("   Protección VIP: Rechazo automático de no-pagados activo")
    print("   Planes oficiales: $129 MXN (Semanal) | $349 MXN (Mensual)")
    print("   Admin ID:", ADMIN_CHAT_ID)
    print("="*60)
    
    configurar_comandos_bot()
    offset = get_offset()
    
    while True:
        try:
            updates = get_updates(offset)
            
            for update in updates:
                offset = update['update_id'] + 1
                save_offset(offset)
                
                # 0. EVENTO: Botón Inline presionado (Callback Query)
                if 'callback_query' in update:
                    procesar_callback_query(update['callback_query'])
                    continue

                # 1. EVENTO: Solicitud de entrada a canal privado (Request Admin Approval)
                if 'chat_join_request' in update:
                    procesar_solicitud_union(update['chat_join_request'])
                    continue

                # 2. EVENTO: Mensajes normales o fotos
                message = update.get('message', {})
                if not message:
                    continue

                # Detectar si alguien entró al canal
                if 'new_chat_members' in message:
                    procesar_nuevo_miembro(message)
                    continue

                chat_id = message.get('chat', {}).get('id')
                if not chat_id:
                    continue
                
                chat = message.get('chat', {})
                chat_type = chat.get('type', 'private')
                from_user = message.get('from', {})
                user_first_name = from_user.get('first_name', 'Usuario')
                user_username = from_user.get('username', '')
                raw_text = message.get('text', '').strip()
                texto = raw_text.lower()

                # A. MANEJO DE GRUPOS (Carlos + Novia + Bot)
                if chat_type in ('group', 'supergroup'):
                    save_team_group_id(chat_id, chat.get('title', 'Grupo Rey Taco'))
                    
                    # Si envían una captura de Playdoit en el grupo:
                    if 'photo' in message:
                        print(f"📸 Foto de Playdoit recibida en el grupo de trabajo {chat_id}")
                        procesar_foto(update)
                        continue

                    if texto in ('/reel', '/video', '/reels', '/videos', 'reel', 'video'):
                        reels_dir = REPO_ROOT / "data" / "reels"
                        mp4_files = sorted(reels_dir.glob("*.mp4"), key=os.path.getmtime, reverse=True) if reels_dir.exists() else []
                        if mp4_files:
                            latest_reel = mp4_files[0]
                            responder(chat_id, f"🎬 Compartiendo el último video generado (<code>{latest_reel.name}</code>)...")
                            enviar_video_telegram(chat_id, latest_reel, caption="🌮👑 <b>Rey Taco Picks — Reel Oficial con Audio & Música</b>")
                        else:
                            responder(chat_id, "ℹ️ No hay reels generados en este momento en la carpeta de medios.")
                    elif texto in ('/ganador', '/win', '/ticket_ganador'):
                        win_reel = REPO_ROOT / "data" / "reels" / "reel_playdoit_ganador_real.mp4"
                        if win_reel.exists():
                            caption_win = (
                                "✅ <b>TICKET GANADOR REAL • PLAYDOIT EN VIVO</b> 🌮👑\n"
                                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                "Captura real de Playdoit sin censura ni sellos. Celaya vs Tapachula cobrado con cuota 1.64.\n\n"
                                "📋 <b>COPIA RÁPIDA (TikTok / Instagram Reels / Facebook):</b>\n"
                                "<code>"
                                "Evidencia real en vivo directamente desde Playdoit 🌮👑\n\n"
                                "Así cobramos la victoria de Celaya frente a Tapachula con cuota 1.64 tras el 2-0 final. Cero corazonadas y cero humo: pura ventaja estadística calculada por Inteligencia Artificial y sellada antes del inicio.\n\n"
                                "Todos los tickets quedan grabados en nuestro ledger público SHA-256.\n\n"
                                "👉 Revisa la auditoría completa y únete al VIP en el link de nuestro perfil: reytacopicks.com\n\n"
                                "#Playdoit #ReyTacoPicks #ApuestasDeportivas #LigaDeExpansion #Celaya #PicksDeportivos #InteligenciaArtificial #ApuestasMexico"
                                "</code>"
                            )
                            enviar_video_telegram(chat_id, win_reel, caption=caption_win)
                        else:
                            responder(chat_id, "ℹ️ El reel de ticket ganador aún no está disponible.")
                    elif texto in ('/perdedor', '/loss', '/transparencia', '/ticket_perdedor'):
                        loss_reel = REPO_ROOT / "data" / "reels" / "reel_playdoit_perdedor_real.mp4"
                        if loss_reel.exists():
                            caption_loss = (
                                "🛡️ <b>TRANSPARENCIA RADICAL • TICKET NO ACERTADO PLAYDOIT</b> 🌮👑\n"
                                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                "Boleto real de Playdoit mostrando el resultado no acertado por un gol. Porque en Rey Taco Picks NUNCA borramos un pick.\n\n"
                                "📋 <b>COPIA RÁPIDA (TikTok / Instagram Reels / Facebook):</b>\n"
                                "<code>"
                                "¿Alguna vez has visto a un tipster publicar un ticket que se le cayó? Nosotros sí. 🛡️❌\n\n"
                                "En Rey Taco Picks la transparencia es radical: en este parlay de Playdoit con momio 2.67, Celaya cumplió ganando 2-0, pero el empate de Tigres nos dejó fuera por un solo gol.\n\n"
                                "El 99% de canales borran las fallas. Nosotros las publicamos porque la varianza deportiva existe y la disciplina matemática a largo plazo es lo único que genera ganancias reales (+EV).\n\n"
                                "👉 Auditoría pública y verificable en el link de nuestro perfil: reytacopicks.com\n\n"
                                "#Transparencia #ReyTacoPicks #Playdoit #Tigres #Varianza #ApuestasResponsables #ApuestasDeportivas #EstadisticaDeportiva"
                                "</code>"
                            )
                            enviar_video_telegram(chat_id, loss_reel, caption=caption_loss)
                        else:
                            responder(chat_id, "ℹ️ El reel de ticket perdedor aún no está disponible.")
                    elif texto in ('/pick_solo', '/simular_solo', 'pick_solo'):
                        try:
                            from backend.interactive_telegram_dispatcher import dispatch_interactive_pick
                            test_solo = {
                                "ticket_id": f"RT-{datetime.now(MEXICO_TZ).strftime('%Y%m%d')}-SOLO-001",
                                "is_parlay": False,
                                "home_team": "Juárez FC",
                                "away_team": "Tigres UANL",
                                "league": "Liga MX",
                                "time": "19:00",
                                "pick": "Tigres Ganador Directo",
                                "market_odds_decimal": 1.85,
                                "market_odds_american": "-118",
                                "minimum_odds_decimal": 1.75,
                                "minimum_odds_american": "-133",
                                "model_edge_pp": 5.4,
                                "ev_percent": 6.8,
                                "stake_units": 1.5,
                                "tactical_rationale": "Desfase en la cuota de victoria visitante frente al modelo de potencia ofensiva."
                            }
                            dispatch_interactive_pick(test_solo)
                            responder(chat_id, "📢 <b>Pick Solo enviado a Carlos</b> solicitando la foto obligatoria de Playdoit.")
                        except Exception as e:
                            responder(chat_id, f"⚠️ Error generando pick: {e}")
                    elif texto in ('/pick_parlay', '/simular_parlay', 'pick_parlay'):
                        try:
                            from backend.interactive_telegram_dispatcher import dispatch_interactive_pick
                            test_parlay = {
                                "ticket_id": f"RT-{datetime.now(MEXICO_TZ).strftime('%Y%m%d')}-PARLAY-001",
                                "is_parlay": True,
                                "legs": [
                                    {
                                        "home_team": "Club América",
                                        "away_team": "Chivas Guadalajara",
                                        "league": "Liga MX",
                                        "time": "21:05",
                                        "pick": "América Ganador Directo",
                                        "odds_american": "-115",
                                        "odds_decimal": 1.87
                                    },
                                    {
                                        "home_team": "Toluca",
                                        "away_team": "Santos Laguna",
                                        "league": "Liga MX",
                                        "time": "19:00",
                                        "pick": "Más de 2.5 Goles",
                                        "odds_american": "-140",
                                        "odds_decimal": 1.71
                                    }
                                ],
                                "market_odds_decimal": 3.20,
                                "market_odds_american": "+220",
                                "minimum_odds_decimal": 2.95,
                                "minimum_odds_american": "+195",
                                "model_edge_pp": 8.5,
                                "ev_percent": 9.2,
                                "stake_units": 1.5,
                                "tactical_rationale": "Parlay institucional de ventaja en xG de local en Liga MX."
                            }
                            dispatch_interactive_pick(test_parlay)
                            responder(chat_id, "📢 <b>Parlay Combinado enviado a Carlos</b> solicitando la foto obligatoria de Playdoit.")
                        except Exception as e:
                            responder(chat_id, f"⚠️ Error generando parlay: {e}")
                    elif texto in ('/status', 'status'):
                        responder(chat_id, "🤖 <b>Rey Taco Bot Cloud:</b> En línea 24/7 y listo para compartir contenido.")
                    elif procesar_comandos_suite(chat_id, raw_text, texto):
                        continue
                    # Si es chat normal del grupo entre Carlos y su novia, no interferir
                    continue

                # B. MANEJO DE MENSAJES PRIVADOS (Si NO es Carlos)
                if chat_id != ADMIN_CHAT_ID:
                    if 'photo' in message:
                        procesar_comprobante_cliente(update)
                    elif procesar_vinculacion_telegram(message, raw_text):
                        pass
                    else:
                        print(f"👤 Mensaje privado de {user_first_name} (@{user_username} | ID {chat_id}): '{raw_text}'")
                        
                        # Notificar inmediatamente a Carlos
                        if ADMIN_CHAT_ID:
                            responder(
                                ADMIN_CHAT_ID,
                                f"📩 <b>Mensaje directo al Bot:</b>\n"
                                f"• De: <b>{user_first_name}</b> (@{user_username or 'sin_user'} | ID: <code>{chat_id}</code>)\n"
                                f"• Mensaje: <i>\"{raw_text}\"</i>"
                            )
                        
                        if texto in ('/vip', '/precio', '/precios', '/planes', '/membresia', 'vip', 'precio', 'planes'):
                            responder_vip(chat_id)
                        elif texto in ('/picks', '/hoy', '/cartelera', 'picks', 'hoy'):
                            responder_picks(chat_id)
                        elif texto in ('/auditoria', '/record', '/historial', 'auditoria', 'record'):
                            responder_auditoria(chat_id)
                        elif texto in ('/ayuda', '/soporte', '/contacto', 'ayuda', 'soporte'):
                            responder_ayuda(chat_id)
                        else:
                            # Respuesta cordial reconociendo interacción
                            responder(
                                chat_id,
                                f"¡Hola {user_first_name}! 👋 Gracias por escribirle a <b>Rey Taco Picks</b> 🌮.\n\n"
                                f"Carlos ha sido notificado de tu mensaje. Si estás por unirte al grupo de coordinación del equipo, "
                                f"en cuanto me añadan al grupo les compartiré todo el material audiovisual y los reels listos con música. ¡Un gusto saludarte!"
                            )
                    continue

                
                # SI ES CARLOS (ADMIN MASTER):
                if 'photo' in message:
                    procesar_foto(update)
                elif 'text' in message:
                    raw_text = message.get('text', '').strip()
                    texto = raw_text.lower()
                    
                    if procesar_comandos_suite(chat_id, raw_text, texto):
                        continue

                    if texto in ('/start', '/admin', '/ayuda'):
                        responder(chat_id, 
                            "👑 <b>PANEL DE ADMINISTRACIÓN — CARLOS MASTER</b>\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            "📸 <b>Publicar Ticket Ganador:</b>\n"
                            "Envíame cualquier foto de ticket de Playdoit para vincular y sellar con SHA-256.\n\n"
                            "🎨 <b>SUITE DE CONTENIDO & REDES:</b>\n"
                            "• <code>/story</code> ➔ Genera historia vertical 9:16 (1080x1920) de cartelera\n"
                            "• <code>/carrusel</code> ➔ Genera carrusel de 4 diapositivas para Instagram Feed\n"
                            "• <code>/copy [tema]</code> ➔ Ganchos y texto rápido (ej. /copy ligamx, /copy parlay)\n"
                            "• <code>/hashtags</code> ➔ Bloques de etiquetas con máximo alcance\n"
                            "• <code>/recap</code> ➔ Cierre de jornada con balance, ROI y texto de historia\n\n"
                            "⚡ <b>ALERTAS DE MERCADO & BANCA:</b>\n"
                            "• <code>/alerta_mercado</code> ➔ Detecta desfase de cuotas en Playdoit\n"
                            "• <code>/cashout</code> ➔ Seguimiento de parlays vivos y cobertura\n"
                            "• <code>/banca 2000</code> ➔ Desglose y cálculo de unidades en pesos\n\n"
                            "🛡️ <b>GUARDIÁN DEL CANAL VIP & CONTROL:</b>\n"
                            "• <code>/status</code> ➔ Estado del bot y bloques del ledger\n"
                            "• <code>/aprobar USER_ID</code> ➔ Aprueba manualmente a un usuario\n"
                            "• <code>/expulsar USER_ID</code> ➔ Expulsa a un usuario no pagado"
                        )
                    elif texto == '/status':
                        try:
                            from backend.audit_ledger import get_ledger_state
                            state = get_ledger_state()
                            total_b = state.get("total_blocks", 0)
                            last_h = state.get("last_hash", "N/A")[:16]
                        except Exception:
                            total_b = "N/A"
                            last_h = "N/A"
                        responder(chat_id,
                            f"📊 <b>ESTADO DEL SISTEMA REY TACO</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🔗 <b>Bloques en Ledger:</b> {total_b}\n"
                            f"🎯 <b>Último Hash SHA-256:</b> <code>{last_h}...</code>\n"
                            f"📢 <b>Canal Gratuito:</b> <code>{FREE_CHANNEL_ID}</code>\n"
                            f"👑 <b>Canal VIP:</b> <code>{VIP_CHANNEL_ID}</code>\n"
                            f"🤖 <b>Bot Guardian:</b> Activo 24/7",
                            parse_mode="HTML"
                        )
                    elif texto.startswith('/aprobar '):
                        partes = raw_text.split()
                        if len(partes) >= 2:
                            target_id = int(partes[1].strip())
                            if verificar_usuario_vip(telegram_id=target_id):
                                telegram_api("approveChatJoinRequest", {"chat_id": VIP_CHANNEL_ID, "user_id": target_id})
                                responder(chat_id, f"✅ Usuario {target_id} APROBADO: membresía verificada.")
                            else:
                                responder(chat_id, f"⚠️ Usuario {target_id} no tiene una membresía activa; no fue aprobado.")
                    elif texto.startswith('/expulsar '):
                        partes = raw_text.split()
                        if len(partes) >= 2:
                            target_id = int(partes[1].strip())
                            telegram_api("banChatMember", {"chat_id": VIP_CHANNEL_ID, "user_id": target_id})
                            telegram_api("unbanChatMember", {"chat_id": VIP_CHANNEL_ID, "user_id": target_id})
                            responder(chat_id, f"🚫 Usuario {target_id} EXPULSADO del Canal VIP.")
                    elif texto.startswith('/vip '):
                        partes = raw_text.split()
                        if len(partes) == 3:
                            review_id = partes[1].strip()
                            target_email = partes[2].strip().lower()
                            if supabase and SUPABASE_ADMIN_USER_ID:
                                try:
                                    user_id = buscar_usuario_auth_por_correo(target_email)
                                    if not user_id:
                                        responder(chat_id, f"⚠️ No existe una cuenta para {target_email}.")
                                        continue
                                    result = supabase.rpc("approve_spei_review", {
                                        "review_id": review_id,
                                        "review_user": user_id,
                                        "reviewer": SUPABASE_ADMIN_USER_ID,
                                    }).execute()
                                    responder(chat_id, f"✅ SPEI aprobado y membresía activa para {target_email} hasta {result.data}.")
                                except Exception as e:
                                    responder(chat_id, f"⚠️ Error: {e}")
                            else:
                                responder(chat_id, "⚠️ Configura Supabase y SUPABASE_ADMIN_USER_ID antes de aprobar pagos.")
                        else:
                            responder(chat_id, "Uso: /vip REVISION_UUID correo@ejemplo.com")
                    elif texto.startswith('/rechazar '):
                        partes = raw_text.split()
                        if len(partes) == 2 and supabase and SUPABASE_ADMIN_USER_ID:
                            try:
                                result = supabase.rpc("reject_spei_review", {
                                    "review_id": partes[1].strip(),
                                    "reviewer": SUPABASE_ADMIN_USER_ID,
                                    "reason": "Rechazado manualmente",
                                }).execute()
                                responder(chat_id, "✅ Comprobante rechazado." if result.data else "⚠️ La revisión no estaba pendiente.")
                            except Exception as e:
                                responder(chat_id, f"⚠️ Error: {e}")
                    elif texto == '/usuarios':
                        if supabase:
                            try:
                                res = supabase.table("subscriptions").select("user_id,status,current_period_end,provider").order("current_period_end", desc=True).limit(20).execute()
                                if res.data:
                                    msg_users = "📋 MEMBRESÍAS RECIENTES:\n\n"
                                    for u in res.data:
                                        vip_icon = "👑 Activa" if is_active_subscription(u) else "⚪ Inactiva"
                                        msg_users += f"• {u.get('user_id')} · {u.get('provider')} ➔ {vip_icon}\n"
                                    responder(chat_id, msg_users)
                                else:
                                    responder(chat_id, "No hay membresías registradas aún.")
                            except Exception as e:
                                responder(chat_id, f"Error: {e}")
                    elif texto == '/tickets':
                        archivos = os.listdir(TICKETS_DIR)
                        fotos = [f for f in archivos if f.endswith(('.jpg', '.png', '.jpeg'))]
                        responder(chat_id, f"📸 Tickets guardados: {len(fotos)}")
                    elif texto in ('/reel', '/video', '/reels', '/videos'):
                        reels_dir = REPO_ROOT / "data" / "reels"
                        mp4_files = sorted(reels_dir.glob("*.mp4"), key=os.path.getmtime, reverse=True) if reels_dir.exists() else []
                        if mp4_files:
                            latest_reel = mp4_files[0]
                            responder(chat_id, f"🎬 Enviando el último video generado (<code>{latest_reel.name}</code>)...")
                            enviar_video_telegram(chat_id, latest_reel, caption="🌮👑 <b>Rey Taco Picks — Reel Oficial con Audio & Música</b>")
                            t_gid = get_team_group_id()
                            if t_gid and t_gid != chat_id:
                                enviar_video_telegram(t_gid, latest_reel, caption="🎬 <b>Nuevo Reel enviado para revisión del equipo</b>")
                        else:
                            responder(chat_id, "ℹ️ No hay reels generados aún en data/reels.")

                        
        except KeyboardInterrupt:
            print("\n🛑 Listener detenido.")
            break
        except Exception as e:
            print(f"Error en loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()


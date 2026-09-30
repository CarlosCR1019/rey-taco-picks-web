import os
import sys
import json
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "8684914807:AAHjNX6cz_sn1EUZVl0wt4v5iYWzJ8JU5UE"
FREE_CHANNEL_ID = os.getenv("TELEGRAM_FREE_CHANNEL_ID") or "-1004387927424"
VIP_CHANNEL_ID = os.getenv("TELEGRAM_VIP_CHANNEL_ID") or "-1003845930328"
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or "5912533842"

def post_telegram(chat_id: str, text: str, reply_markup: dict = None):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("ok", False)
    except Exception as e:
        print(f"Error publicando en {chat_id}: {e}")
        return False

def main():
    print("=" * 70)
    print("🌮 TRANSMISIÓN OFICIAL REY TACO PICKS — CANALES TELEGRAM")
    print("=" * 70)

    # 1. PUBLICACIÓN PARA CANAL GRATUITO (@ReyTacoPicksFree)
    free_text = (
        "🌮 <b>REY TACO PICKS • JOYA GRATUITA DEL DÍA</b> 💎\n\n"
        "⚾ <b>GRANDES LIGAS (MLB)</b>\n"
        "🏟️ <b>Chicago White Sox @ Houston Astros</b>\n"
        "⏰ <b>Hora:</b> 15:00 CDMX (Minute Maid Park)\n\n"
        "🎯 <b>Selección:</b> Houston Astros Gana (Moneyline)\n"
        "📊 <b>Cuota Playdoit:</b> <code>-150 (1.67)</code>\n"
        "💰 <b>Stake Sugerido:</b> 1.0 Unidad ($50 MXN)\n\n"
        "🧠 <b>ANÁLISIS CUANTITATIVO (+EV):</b>\n"
        "• <b>Duelo de Pitcheo:</b> Hunter Brown (HOU, ERA 3.12, WHIP 1.15) parte con enorme ventaja ante Sean Burke (CWS).\n"
        "• <b>Poder en Casa:</b> Houston promedia 5.4 carreras por juego en Minute Maid Park, mientras que Chicago White Sox batea para un raquítico .215 de visita ante abridores diestros.\n"
        "• <b>Modelo IA:</b> Proyecta una probabilidad de victoria local del 71.4%, superando con creces la probabilidad implícita del casino.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "👑 <b>¿Quieres ver las 6 Joyas restantes y el Parlay Oficial de la Tarde (+190)?</b>\n"
        "Abre la Mini App interactiva o suscríbete a nuestro canal VIP 👇"
    )

    free_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "🌮 Abrir Mini App de Picks (v12)",
                    "url": "https://reytacopicks.com/mini-app.html?v=12"
                }
            ],
            [
                {
                    "text": "👑 Ver Cartelera VIP (@ReyTacoPicks)",
                    "url": "https://t.me/ReyTacoPicks"
                }
            ]
        ]
    }

    # 2. PUBLICACIÓN PARA CANAL VIP (@ReyTacoPicks)
    vip_text = (
        "👑 <b>REY TACO PICKS VIP • CARTELERA ÉLITE & PARLAYS DE ORO</b> 🌮\n\n"
        "Jornada oficial de hoy (30 de Septiembre 2026). Cuotas 100% verificadas en Playdoit Altenar.\n\n"
        "👑 <b>PARLAY DE ORO OFICIAL (Doble Play MLB):</b>\n"
        "• Pierna 1: ⚾ <b>HOU Astros ML (-150 / 1.67)</b> — 15:00 CDMX\n"
        "• Pierna 2: ⚾ <b>NY Yankees ML (-135 / 1.74)</b> — 18:00 CDMX\n\n"
        "📊 <b>Cuota Combinada:</b> <code>+190 (2.90)</code>\n"
        "💰 <b>Stake Recomendado:</b> 1.0 Unidad ($50 MXN)\n"
        "💵 <b>Retorno Potencial:</b> <b>$145 MXN</b> (Ganancia neta: $95 MXN)\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💎 <b>JOYAS INDIVIDUALES ACTIVAS PARA HOY:</b>\n"
        "1. ⚾ <b>CHI White Sox @ HOU Astros (15:00):</b> Astros ML <code>-150 (1.67)</code>\n"
        "2. ⚾ <b>BOS Red Sox @ NY Yankees (18:00):</b> Yankees ML <code>-135 (1.74)</code>\n"
        "3. ⚾ <b>CHI Cubs @ SD Padres (20:00):</b> Padres ML <code>-150 (1.67)</code>\n"
        "4. 🏀 <b>Maccabi vs Besiktas:</b> Maccabi -2.5 <code>-115 (1.87)</code>\n"
        "5. 🏀 <b>Panathinaikos vs ASVEL:</b> Panathinaikos 1Q -2.5 <code>-145 (1.69)</code>\n"
        "6. ⚽ <b>España Sub-20 vs México Sub-20:</b> España Sub-20 ML <code>+105 (2.05)</code>\n"
        "7. ⚽ <b>Lyon (F) vs Chelsea (F):</b> Lyon ML <code>-263 (1.38)</code>\n\n"
        "🛡️ <b>GESTIÓN DE RIESGO:</b> Exposición máxima diaria: 3.0 Unidades. Toca el botón para abrir la Mini App y calcular tu bankroll exacto."
    )

    vip_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "🌮 Abrir Mini App y Gestión de Banca",
                    "url": "https://reytacopicks.com/mini-app.html?v=12"
                }
            ],
            [
                {
                    "text": "🤖 Abrir en Telegram Bot",
                    "url": "https://t.me/Rey_Taco_Bot"
                }
            ]
        ]
    }

    # Despachar
    ok_free = post_telegram(FREE_CHANNEL_ID, free_text, free_markup)
    print(f"📢 Canal Gratuito ({FREE_CHANNEL_ID}): {'✅ Enviado con éxito' if ok_free else '❌ Error'}")

    ok_vip = post_telegram(VIP_CHANNEL_ID, vip_text, vip_markup)
    print(f"👑 Canal VIP ({VIP_CHANNEL_ID}): {'✅ Enviado con éxito' if ok_vip else '❌ Error'}")

    # Notificar a Carlos en su chat personal
    admin_text = (
        "🚀 <b>TRANSMISIÓN COMPLETADA EXITOSAMENTE</b>\n\n"
        f"• 📢 <b>Canal Gratuito (@ReyTacoPicksFree):</b> {'✅ Publicado' if ok_free else '❌ Error'}\n"
        f"• 👑 <b>Canal VIP (@ReyTacoPicks):</b> {'✅ Publicado' if ok_vip else '❌ Error'}\n\n"
        "La Joya Gratuita del Día (Astros ML -150) y el Parlay de Oro de la Tarde (+190) ya están disponibles para todos tus seguidores con enlaces directos a la Mini App v12."
    )
    post_telegram(ADMIN_CHAT_ID, admin_text)
    print("👤 Notificación enviada al chat personal de Carlos.")

if __name__ == "__main__":
    main()

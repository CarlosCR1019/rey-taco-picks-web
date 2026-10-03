import os
import sys
import json
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or "8684914807:AAHjNX6cz_sn1EUZVl0wt4v5iYWzJ8JU5UE"
ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID") or "5912533842"
VIP_CHANNEL_ID = os.getenv("TELEGRAM_VIP_CHANNEL_ID") or "-1003845930328"

def send_consolidated_window():
    text = (
        "🌮 <b>REY TACO • CARTELERA OFICIAL DE PICKS PRIVADOS</b> 👑\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📅 <b>Ventana Activa: Sábado 3 Octubre (Tarde / Noche • 12:00 a 24:00 CDMX)</b>\n"
        "🎯 <i>Regla Estricta: Exactamente 5 Picks +EV Auditados en Playdoit</i>\n\n"
        "1️⃣ 🏀 <b>Liga ACB España</b> (13:00 CDMX)\n"
        "   <b>Manresa vs. CB Breogán</b>\n"
        "   👉 <b>Manresa & Sí 80 puntos</b> @ <code>-125 (1.80)</code>\n"
        "   <i>💡 Pace veloz en el Nou Congost con alta efectividad perimetral</i>\n\n"
        "2️⃣ 🏈 <b>NCAAF Colegial</b> (13:30 CDMX)\n"
        "   <b>Virginia @ Florida State</b>\n"
        "   👉 <b>Virginia Cavaliers a Ganar (ML)</b> @ <code>-120 (1.83)</code>\n"
        "   <i>💡 Virginia balanceado por tierra vs FSU en colapso ofensivo</i>\n\n"
        "3️⃣ ⚾ <b>MLB Grandes Ligas</b> (14:00 CDMX)\n"
        "   <b>ATL Braves @ LA Dodgers</b>\n"
        "   👉 <b>LA Dodgers (-0.5) Innings 1 a 5 (F5)</b> @ <code>-160 (1.63)</code>\n"
        "   <i>💡 Lineup estelar de Dodgers contundente en tercios tempranos</i>\n\n"
        "4️⃣ ⚽ <b>Brasileirao Serie A</b> (15:30 CDMX)\n"
        "   <b>Atlético-MG vs. Bragantino</b>\n"
        "   👉 <b>Ambos Equipos Anotan: Sí</b> @ <code>-140 (1.71)</code>\n"
        "   <i>💡 Arena MRV: Galo ofensivo pero vulnerable ante Bragantino vertical</i>\n\n"
        "5️⃣ ⚽ <b>Liga de Expansión MX</b> (19:00 CDMX)\n"
        "   <b>Atletico Morelia vs. Coyotes Tlaxcala</b>\n"
        "   👉 <b>Más de 2.5 goles (Total)</b> @ <code>-180 (1.56)</code>\n"
        "   <i>💡 Morelia promedia 2.1 goles de local vs Tlaxcala débil de visita</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Mini App Actualizada</b>: Toca el botón abajo para ver rutas exactas paso a paso en Playdoit 👇"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    targets = [
        ("Carlos (Admin)", ADMIN_CHAT_ID),
        ("Canal VIP", VIP_CHANNEL_ID)
    ]

    for label, chat_id in targets:
        button = {
            "text": "📱 Abrir Cartelera en la Mini App",
            "web_app": {"url": "https://reytacopicks.com/mini-app.html?v=12"}
        } if chat_id == ADMIN_CHAT_ID else {
            "text": "📱 Abrir Cartelera en la Mini App",
            "url": "https://reytacopicks.com/mini-app.html?v=12"
        }
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": {
                "inline_keyboard": [
                    [button]
                ]
            }
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(f"✅ Enviado a {label}: {data.get('ok')}")
        except Exception as e:
            print(f"❌ Error enviando a {label}: {e}")

if __name__ == "__main__":
    send_consolidated_window()

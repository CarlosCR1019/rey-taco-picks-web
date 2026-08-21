import os
import json
import time
import urllib.request
import sys
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = os.getenv("TELEGRAM_FREE_CHANNEL_ID")

def despachar_cola():
    queue_file = os.path.join(os.path.dirname(__file__), "channel_queue.json")
    if not os.path.exists(queue_file):
        return

    if not TELEGRAM_TOKEN or not CHANNEL_ID:
        print("Faltan credenciales de Telegram.")
        return

    try:
        with open(queue_file, "r", encoding="utf-8") as f:
            queue = json.load(f)

        # Legacy queue rows did not carry a visibility marker and may contain
        # premium selections. Purge them instead of guessing what is public.
        public_queue = [item for item in queue if item.get("visibility") == "public"]
        if len(public_queue) != len(queue):
            queue = public_queue
            with open(queue_file, "w", encoding="utf-8") as f:
                json.dump(queue, f, indent=2, ensure_ascii=False)
            print("🔒 Cola heredada purgada; solo se permiten filas marcadas como públicas.")

        now = time.time()
        modificado = False
        enviados_ahora = 0

        for item in queue:
            if not item.get("enviado") and item.get("timestamp_programado", 0) <= now:
                msg = item.get("mensaje")
                if msg:
                    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
                    data = json.dumps({"chat_id": CHANNEL_ID, "text": msg}).encode('utf-8')
                    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
                    try:
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            if resp.getcode() == 200:
                                print(f"📢 ✅ Pick programado enviado al canal: {item.get('partido')}")
                                item["enviado"] = True
                                modificado = True
                                enviados_ahora += 1
                                time.sleep(2)
                    except Exception as e:
                        print(f"⚠️ Error enviando pick {item.get('partido')}: {e}")

        if modificado:
            with open(queue_file, "w", encoding="utf-8") as f:
                json.dump(queue, f, indent=2, ensure_ascii=False)
        else:
            pendientes = sum(1 for x in queue if not x.get('enviado'))
            if pendientes > 0:
                print(f"⏳ Cola activa: {pendientes} picks pendientes para próximas horas.")

    except Exception as e:
        print(f"❌ Error en despachador: {e}")

if __name__ == "__main__":
    despachar_cola()

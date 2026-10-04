"""
scripts/run_multisport_daemon_vps.py
====================================
Daemon continuo 24/7 en el VPS para Rey Taco Picks:
- Escanea Fútbol, Fútbol Americano (NFL/NCAAF), Béisbol (MLB), Baloncesto (NBA/Euroliga).
- Se ejecuta cada 30 minutos o al inicio de cada ventana de cadencia CDMX (00, 06, 12, 18).
- Extrae cotizaciones reales de Playdoit Altenar API.
- Audita con Groq (openai/gpt-oss-120b).
- Envía las propuestas interactivas al Telegram de Carlos (5912533842).
- Mantiene registro de deduplicación persistente.
"""

import os
import sys
import time
import traceback
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.multisport_cadence_engine import run_multisport_cadence_cycle, get_current_cadence_window

MEXICO_TZ = ZoneInfo("America/Mexico_City")
CHECK_INTERVAL_SECONDS = 600  # 10 minutos entre revisiones


def main():
    print("=" * 80)
    print("🌮 INICIANDO DAEMON MULTIDEPORTE 24/7 (CADENCIA 6 HORAS) — REY TACO PICKS")
    print(f"🕒 Inicio: {datetime.now(MEXICO_TZ).strftime('%Y-%m-%d %H:%M:%S')} CDMX")
    print("=" * 80)

    while True:
        now_cdmx = datetime.now(MEXICO_TZ)
        w_key, w_label, _ = get_current_cadence_window(now_cdmx)
        print(f"\n🚀 Verificando ventana activa: {w_label} ({now_cdmx.strftime('%Y-%m-%d %H:%M:%S')} CDMX)...")
        
        try:
            # Ejecuta la ventana correspondiente (madrugada, mañana, tarde, noche)
            picks = run_multisport_cadence_cycle()
            if picks:
                print(f"✅ Ventana {w_key} procesada con éxito: {len(picks)} jugadas generadas y despachadas.")
            else:
                print(f"ℹ️ Ventana {w_key} ya despachada hoy o sin valor. Dormitando hasta siguiente chequeo.")
        except Exception as e:
            print(f"❌ Error inesperado en ciclo:")
            traceback.print_exc()

        print(f"💤 Esperando {CHECK_INTERVAL_SECONDS // 60} minutos...")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

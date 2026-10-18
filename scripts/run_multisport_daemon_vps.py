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

        # Evaluación del Reto Escalera de Fin de Semana (Viernes a Domingo, 12:00 PM a 9:00 PM CDMX)
        try:
            from backend.ladder_challenge_engine import evaluate_and_dispatch_ladder_step
            ladder_res = evaluate_and_dispatch_ladder_step()
            if ladder_res:
                print(f"🪜 [RETO ESCALERA] Paso {ladder_res.get('ladder_step')} despachado con éxito: {ladder_res.get('ticket_id')}")
        except Exception as e_ladder:
            print(f"⚠️ Error en evaluación del Reto Escalera: {e_ladder}")

        # Auditoría continua: Actualizar precios de cierre para CLV y liquidar apuestas terminadas
        try:
            from backend.pick_tracker import refresh_closing_prices
            from backend.pick_settlement import settle_pending
            refreshed = refresh_closing_prices(max_hours_ahead=12.0)
            settled = settle_pending(min_hours_after_start=2.5)
            if refreshed or settled:
                print(f"📈 [AUDITORÍA & SETTLEMENT] Precios CLV capturados: {refreshed} | Apuestas liquidadas: {settled}")
        except Exception as e:
            print(f"⚠️ Error en auditoría continua (CLV / Settlement): {e}")

        print(f"💤 Esperando {CHECK_INTERVAL_SECONDS // 60} minutos...")
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()

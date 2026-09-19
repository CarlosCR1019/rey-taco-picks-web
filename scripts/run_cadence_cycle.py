"""
scripts/run_cadence_cycle.py
============================
Script maestro para ejecutar el ciclo operativo de 6 horas de Rey Taco Picks.

Flujo de ejecución:
1. Extracción Universal Multideporte (Fútbol, KBO, NPB, Tenis de Mesa, Dardos, Baloncesto, etc.).
2. Particionado en disco en `data/sports/`.
3. Orquestación y evaluación cuantitativa de la ventana activa de 6 horas.
4. Despacho Interactivo de Telegram: Envío al Administrador con botón de confirmación y fallback de 5 min.
5. Sincronización criptográfica con el VPS en Helsinki (`204.168.247.173`).
"""

import os
import sys
import time
import argparse
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.playdoit_universal_scraper import run_universal_scrape
from backend.cadence_orchestrator import run_cadence_evaluation, get_current_window_key
from backend.interactive_telegram_dispatcher import (
    dispatch_interactive_pick,
    poll_telegram_callbacks,
    TIMEOUT_SECONDS
)

MEXICO_TZ = ZoneInfo("America/Mexico_City")
VPS_IP = "204.168.247.173"
SSH_KEY = r"C:\Users\carlo\.ssh\reytaco_vps_key"


def sync_with_vps():
    """Sincroniza el Ledger Criptográfico y la cartelera con el VPS en Helsinki."""
    print("\n🚀 [SINCRONIZACIÓN VPS] Respaldando en Helsinki (204.168.247.173)...")
    ledger_local = REPO_ROOT / "data" / "audit_ledger.jsonl"
    cartelera_local = REPO_ROOT / "data" / "cartelera_multisport.json"

    if not Path(SSH_KEY).exists():
        print("⚠️ Llave SSH no encontrada. Saltando SCP.")
        return

    try:
        if ledger_local.exists():
            cmd = f'scp -i "{SSH_KEY}" -o StrictHostKeyChecking=no "{ledger_local}" root@{VPS_IP}:/root/sports-props-collector/audit_ledger.jsonl'
            subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("   ✅ Audit Ledger SHA-256 sincronizado en el VPS.")

        if cartelera_local.exists():
            cmd2 = f'scp -i "{SSH_KEY}" -o StrictHostKeyChecking=no "{cartelera_local}" root@{VPS_IP}:/root/sports-props-collector/cartelera.json'
            subprocess.run(cmd2, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("   ✅ Cartelera Multideporte sincronizada en el VPS.")
    except Exception as e:
        print(f"⚠️ Error en sincronización SCP: {e}")


def main():
    parser = argparse.ArgumentParser(description="Rey Taco Picks — Ejecutor de Cadencia 6 Horas")
    parser.add_argument("--window", choices=["00-06", "06-12", "12-18", "18-24", "auto"], default="auto",
                        help="Ventana horaria a evaluar (default: auto según hora actual)")
    parser.add_argument("--skip-scrape", action="store_true", help="Usa los datos locales existentes sin re-escanear")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS, help="Segundos para el fallback de Telegram (default: 300s / 5 min)")
    args = parser.parse_args()

    win_key = get_current_window_key() if args.window == "auto" else args.window
    print("=" * 85)
    print(f"🌮 REY TACO PICKS — CICLO INSTITUCIONAL DE 6 HORAS [{win_key.upper()}]")
    print(f"🕒 Hora Actual CDMX: {datetime.now(MEXICO_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 85)

    # 1. Scraping Multideporte
    if not args.skip_scrape:
        print("\n📡 [FASE 1] Ejecutando Scraper Universal en Playdoit...")
        run_universal_scrape(headless=True)
    else:
        print("\n⏩ [FASE 1] Omitiendo scraping. Usando datos existentes en disco.")

    # 2. Orquestación Cuantitativa y Sellado en Ledger
    print("\n🎯 [FASE 2] Evaluando ventana operativa en Quant Engine...")
    eval_result = run_cadence_evaluation(window_key=win_key)

    approved = eval_result.get("approved_picks", [])

    # 3. Despacho Interactivo en Telegram con Botón y Temporizador
    if approved:
        print(f"\n📲 [FASE 3] Iniciando despacho interactivo para {len(approved)} picks aprobados...")
        for pick in approved:
            dispatch_interactive_pick(pick, timeout_seconds=args.timeout)

        # Escuchar botones del Administrador
        print(f"⏳ Esperando respuesta del Administrador (o fallback autónomo en {args.timeout}s)...")
        poll_telegram_callbacks(duration_seconds=args.timeout + 10)
    else:
        print("\n🚫 [FASE 3] No hay picks para despachar en esta ventana (Mercado cerrado o sin valor suficiente).")

    # 4. Sincronización con el VPS
    sync_with_vps()

    print("\n" + "=" * 85)
    print("🎉 CICLO OPERATIVO DE 6 HORAS COMPLETADO EXITOSAMENTE")
    print("=" * 85)


if __name__ == "__main__":
    main()

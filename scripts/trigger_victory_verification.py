"""
scripts/trigger_victory_verification.py
======================================
Disparador de Verificación de Foto de Boleto Playdoit para Generación de Contenido.

Uso:
  python scripts/trigger_victory_verification.py [--ticket TICKET_ID] [--demo]
"""

import sys
import argparse
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.victory_content_verifier import prompt_victory_content_request
from scripts.generate_victory_content import load_settled_history, register_victory

def main():
    parser = argparse.ArgumentParser(description="Disparar solicitud de foto Playdoit para contenido de victoria")
    parser.add_argument("--ticket", type=str, default="", help="Ticket ID específico")
    parser.add_argument("--demo", action="store_true", help="Crear una victoria de demostración para probar")
    args = parser.parse_args()

    if args.demo:
        print("🧪 Creando victoria demo de prueba...")
        record = register_victory(
            ticket_id="RT-20260929-MLB-VERDE-REAL",
            match_title="Boston Red Sox vs. NY Yankees",
            league="⚾ MLB Grandes Ligas",
            pick="Menos 6.0 carreras",
            odds_american="+100",
            odds_decimal=2.00,
            stake_units=2.0,
            user_bankroll=5000.0,
            sport_icon="⚾",
            is_parlay=False
        )
    elif args.ticket:
        hist = load_settled_history()
        picks = hist.get("settled_picks", [])
        record = next((p for p in picks if p.get("ticket_id") == args.ticket), None)
        if not record:
            print(f"❌ Ticket {args.ticket} no encontrado en settled_picks_history.json.")
            return
    else:
        # Tomar la victoria más reciente
        hist = load_settled_history()
        picks = [p for p in hist.get("settled_picks", []) if p.get("result") == "WON"]
        if not picks:
            print("⚠️ No hay victorias registradas en settled_picks_history.json. Usa --demo para crear una.")
            return
        record = picks[0]

    print(f"🚀 Solicitando foto a Carlos en Telegram para ticket: {record.get('ticket_id')} ({record.get('match')})...")
    ok = prompt_victory_content_request(record)
    if ok:
        print("✅ Solicitud enviada exitosamente con botón de descarte.")
    else:
        print("❌ Error enviando solicitud.")

if __name__ == "__main__":
    main()

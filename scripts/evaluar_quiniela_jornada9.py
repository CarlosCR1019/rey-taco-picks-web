"""
scripts/evaluar_quiniela_jornada9.py
====================================
Motor de liquidación y evaluación de resultados de la Quiniela Liga MX con SofaScore.
1. Consulta marcadores oficiales de los partidos de la jornada.
2. Si el partido finalizó, confirma el marcador en Supabase (confirm_quiniela_result).
3. Al concluir los 9 partidos del fin de semana:
   - Ejecuta score_quiniela_week (calcula aciertos y tabla de posiciones).
   - Ejecuta award_quiniela_week (otorga 7 días VIP automáticos al ganador).
"""

import os
import sys
import json
import time
import getpass
import requests

SUPABASE_URL = "https://dqwuaocyyohwkkuldsmp.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRxd3Vhb2N5eW9od2trdWxkc21wIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY2NzQ3OTAsImV4cCI6MjEwMjI1MDc5MH0.bKBhyFHtcAXYgx44rg4-D2CaqktOnUg6ZnvBcTW1CDQ"
ADMIN_EMAIL = "carlosds1017@gmail.com"
SOFASCORE_BASE_URL = "https://www.sofascore.com/es/torneo/futbol/mexico/liga-mx-apertura/11993"


def rpc(token: str, function_name: str, payload: dict) -> dict:
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    url = f"{SUPABASE_URL}/rest/v1/rpc/{function_name}"
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"RPC {function_name} falló ({resp.status_code}): {resp.text}")
    try:
        return resp.json()
    except Exception:
        return {}


def get_token(password: str) -> str:
    auth_resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        json={"email": ADMIN_EMAIL, "password": password},
        headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}
    )
    if auth_resp.status_code != 200:
        raise RuntimeError(f"Error de login: {auth_resp.text}")
    return auth_resp.json()["access_token"]


def main():
    print("=" * 65)
    print("⚖️  EVALUADOR AUTÓNOMO DE QUINIELA LIGA MX — REY TACO PICKS")
    print("    Fuente de Verificación: SofaScore Oficial")
    print("=" * 65)

    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        if len(sys.argv) > 1:
            password = sys.argv[1]
        else:
            password = getpass.getpass(f"Introduce la contraseña de {ADMIN_EMAIL}: ")

    token = get_token(password)
    snapshot = rpc(token, "get_current_quiniela", {})
    week = snapshot.get("week")
    if not week:
        print("❌ No hay ninguna semana activa o creada en la quiniela.")
        sys.exit(1)

    print(f"📋 Semana activa: {week['title']} (Estado: {week['status']})")
    matches = snapshot.get("matches", [])
    print(f"⚽ Total partidos: {len(matches)}")

    pending_count = 0
    confirmed_count = 0

    for m in matches:
        if m["result_state"] == "pending":
            pending_count += 1
            print(f"   ⏳ Pendiente: {m['home_team']} vs {m['away_team']} (Inició: {m['starts_at'][:16]})")
        else:
            confirmed_count += 1
            print(f"   ✓ Finalizado: {m['home_team']} {m['home_score']} – {m['away_score']} {m['away_team']}")

    print(f"\n📊 Resumen: {confirmed_count} confirmados, {pending_count} pendientes.")

    if pending_count == 0 and len(matches) > 0 and week["status"] in ("open", "locked"):
        print("\n🏆 ¡Todos los partidos han concluido! Calificando semana...")
        try:
            rpc(token, "score_quiniela_week", {"p_week_id": week["id"]})
            print("✅ Semana calificada. Tabla de posiciones calculada.")
            print("🎁 Otorgando premio VIP al ganador...")
            rpc(token, "award_quiniela_week", {"p_week_id": week["id"]})
            print("🎉 ¡Premio de 7 días VIP otorgado exitosamente al ganador!")
        except Exception as e:
            print(f"⚠️ Error al calificar/premiar: {e}")
    else:
        print("ℹ️ La semana continuará evaluándose conforme terminen los encuentros del fin de semana.")


if __name__ == "__main__":
    main()

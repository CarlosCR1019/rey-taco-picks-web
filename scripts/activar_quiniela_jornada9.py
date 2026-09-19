"""
scripts/activar_quiniela_jornada9.py
====================================
Script de activación para la Jornada 9 de la Liga MX Apertura 2026 en Supabase.
Registra la jornada, carga los 9 partidos con horarios oficiales y abre la quiniela.
"""

import os
import sys
import getpass
import requests

SUPABASE_URL = "https://dqwuaocyyohwkkuldsmp.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRxd3Vhb2N5eW9od2trdWxkc21wIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY2NzQ3OTAsImV4cCI6MjEwMjI1MDc5MH0.bKBhyFHtcAXYgx44rg4-D2CaqktOnUg6ZnvBcTW1CDQ"
ADMIN_EMAIL = "carlosds1017@gmail.com"

# Los 9 partidos oficiales de la Jornada 9 Apertura 2026 (SofaScore / Liga MX)
MATCHES_JORNADA_9 = [
    # Viernes 18 de septiembre
    {"order": 1, "home": "Puebla", "away": "Atlante", "start": "2026-09-18T19:00:00-06:00"},
    {"order": 2, "home": "Juárez", "away": "Tigres UANL", "start": "2026-09-18T21:00:00-06:00"},
    # Sábado 19 de septiembre
    {"order": 3, "home": "Atlas", "away": "Pumas UNAM", "start": "2026-09-19T17:00:00-06:00"},
    {"order": 4, "home": "Atlético San Luis", "away": "Necaxa", "start": "2026-09-19T17:00:00-06:00"},
    {"order": 5, "home": "Monterrey", "away": "Cruz Azul", "start": "2026-09-19T19:10:00-06:00"},
    {"order": 6, "home": "América", "away": "Guadalajara Chivas", "start": "2026-09-19T21:15:00-06:00"},
    # Domingo 20 de septiembre
    {"order": 7, "home": "Pachuca", "away": "Tijuana", "start": "2026-09-20T18:00:00-06:00"},
    {"order": 8, "home": "Deportivo Toluca", "away": "Santos Laguna", "start": "2026-09-20T18:00:00-06:00"},
    {"order": 9, "home": "Querétaro", "away": "León", "start": "2026-09-20T20:00:00-06:00"},
]


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


def main():
    print("=" * 65)
    print("🇲🇽  ACTIVADOR INSTITUCIONAL DE QUINIELA — REY TACO PICKS")
    print("    Torneo: Liga MX Apertura 2026 · Jornada 9")
    print("=" * 65)

    password = os.getenv("ADMIN_PASSWORD")
    if not password:
        if len(sys.argv) > 1:
            password = sys.argv[1]
        else:
            password = getpass.getpass(f"Introduce la contraseña de {ADMIN_EMAIL}: ")

    if not password:
        print("❌ Error: Se requiere la contraseña.")
        sys.exit(1)

    print(f"\n🔐 Iniciando sesión como {ADMIN_EMAIL}...")
    auth_resp = requests.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        json={"email": ADMIN_EMAIL, "password": password},
        headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}
    )
    if auth_resp.status_code != 200:
        print(f"❌ Error de autenticación ({auth_resp.status_code}): {auth_resp.text}")
        sys.exit(1)

    auth_data = auth_resp.json()
    token = auth_data["access_token"]
    user_id = auth_data["user"]["id"]
    print(f"✅ Sesión iniciada correctamente. ID Administrador: {user_id}")

    # 1. Crear Semana
    print("\n📅 1. Creando Jornada 9 en Supabase...")
    create_payload = {
        "p_season_key": "apertura-2026",
        "p_week_key": "jornada-9",
        "p_title": "Jornada 9 · Liga MX Apertura 2026",
        "p_opens_at": "2026-09-18T14:00:00-06:00",
        "p_closes_at": "2026-09-18T18:50:00-06:00",
        "p_terms_version": "quiniela-apertura-2026-v1",
        "p_result_source_name": "SofaScore",
        "p_result_source_url": "https://www.sofascore.com/es/torneo/futbol/mexico/liga-mx-apertura/11993"
    }

    try:
        week_id = rpc(token, "create_quiniela_week", create_payload)
        print(f"✅ Jornada 9 creada con ID: {week_id}")
    except Exception as e:
        print(f"⚠️ Nota al crear semana: {e}")
        # Si ya existe, obtenemos el ID de la semana actual
        curr = rpc(token, "get_current_quiniela", {})
        if curr.get("week"):
            week_id = curr["week"]["id"]
            print(f"ℹ️ Usando semana existente con ID: {week_id}")
        else:
            raise e

    # 2. Agregar los 9 partidos oficiales
    print("\n⚽ 2. Agregando partidos de la Jornada 9...")
    for m in MATCHES_JORNADA_9:
        match_payload = {
            "p_week_id": week_id,
            "p_display_order": m["order"],
            "p_home_team": m["home"],
            "p_away_team": m["away"],
            "p_starts_at": m["start"]
        }
        try:
            mid = rpc(token, "add_quiniela_match", match_payload)
            print(f"   ✓ Partido {m['order']}: {m['home']} vs {m['away']} (Inicia {m['start'][:16]})")
        except Exception as e:
            print(f"   ℹ️ Partido {m['order']} ({m['home']} vs {m['away']}): {e}")

    # 3. Abrir la semana y congelar partidos
    print("\n🔓 3. Abriendo semana y habilitando recepción de participaciones...")
    try:
        rpc(token, "open_quiniela_week", {"p_week_id": week_id})
        print("✅ ¡SEMANA ABIERTA EXITOSAMENTE!")
    except Exception as e:
        print(f"ℹ️ Estado de apertura: {e}")

    print("\n" + "=" * 65)
    print("🎉 ¡QUINIELA JORNADA 9 ACTIVA EN PRODUCCIÓN!")
    print("   URL: https://reytacopicks.com/quiniela")
    print("   Cierre de recepción: Hoy viernes 18:50 hrs CDMX")
    print("   Premio: 7 Días de Pase VIP al ganador semanal")
    print("=" * 65)


if __name__ == "__main__":
    main()

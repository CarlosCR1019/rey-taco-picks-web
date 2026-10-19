import os
import sys
import json
import re
import urllib.request
from pathlib import Path
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def fetch_live_event_context(event: dict) -> str:
    """Obtiene contexto real verificado con Gemini + Google Search Grounding."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        return ""

    sport = event.get("sport_name", "")
    champ = event.get("champ_name", "")
    name = event.get("name", "")
    time_cdmx = event.get("time_cdmx", "")
    date_cdmx = event.get("date_cdmx", "")

    prompt = (
        f"Proporciona contexto deportivo fáctico y métricas recientes para el partido de {sport} ({champ}): "
        f"'{name}' programado para {date_cdmx} a las {time_cdmx} CDMX.\n"
        f"Enfócate en:\n"
        f"1. Forma reciente de ambos equipos en sus últimos 5 juegos (goles/carreras/puntos anotados y recibidos).\n"
        f"2. Bajas confirmadas, lesiones críticas (ej. mariscal de campo, lanzador abridor, portero o goleador).\n"
        f"3. Rendimiento específico de local vs. visitante.\n"
        f"Responde en 3 viñetas concisas con números y datos duros comprobables. Sin pronósticos ni cuotas."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 8192}
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            parts = data.get("candidates", [])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            return text
    except Exception as e:
        print(f"⚠️ Error obteniendo contexto con Gemini Grounding: {e}")
        return ""


def verify_player_starter_status(player_name: str, team_name: str = "", match_name: str = "") -> tuple[bool, str]:
    """
    Verifica con Google Search Grounding si un jugador está sano, disponible y proyectado/confirmado
    para iniciar como TITULAR hoy. Si hay reporte de lesión, descanso, duda (GTD) o suplencia,
    retorna (False, motivo) para activar el fallback seguro del Parlay Bomba.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key or not player_name:
        return False, "Sin clave Gemini o nombre de jugador vacío"

    prompt = (
        f"Investiga el estado físico y estatus de alineación actual de '{player_name}' ({team_name}) "
        f"para el partido: '{match_name}'.\n"
        f"Preguntas clave:\n"
        f"1. ¿Está lesionado, con molestias o en protocolo médico?\n"
        f"2. ¿Está suspendido o en descanso programado?\n"
        f"3. ¿Es titular indiscutible confirmado/proyectado en el once inicial o quinteto abridor, o iniciará en la banca?\n\n"
        f"Responde estrictamente en formato JSON con estas claves:\n"
        f"{{\n"
        f'  "es_titular_seguro": true,\n'
        f'  "estado": "Titular Confirmado",\n'
        f'  "motivo": "Breve explicación en 1 frase"\n'
        f"}}"
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024}
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            parts = data.get("candidates", [])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            clean_txt = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
            m_json = re.search(r"\{[\s\S]*?\}", clean_txt)
            if m_json:
                try:
                    res_obj = json.loads(m_json.group(0))
                    is_safe = bool(res_obj.get("es_titular_seguro", False))
                    motivo = str(res_obj.get("motivo", ""))
                    return is_safe, motivo
                except Exception:
                    pass
            lower_txt = text.lower()
            if any(w in lower_txt for w in ["lesionado", "lesion", "duda", "questionable", "banca", "suplente", "descarte", "out"]):
                return False, f"Alerta médica en reporte: {text[:80]}"
            if any(w in lower_txt for w in ["titular", "disponible", "inicia", "starting"]):
                return True, "Titular proyectado sin alertas médicas"
    except Exception as e:
        print(f"⚠️ Error verificando estatus de jugador con Gemini: {e}")
        return False, f"Error en verificación: {e}"

    return False, "No se pudo confirmar titularidad al 100%"


if __name__ == "__main__":
    test_ev = {
        "sport_name": "Fútbol",
        "champ_name": "Liga de Expansión MX",
        "name": "Atletico Morelia vs. Coyotes Tlaxcala",
        "time_cdmx": "19:00",
        "date_cdmx": "2026-10-03"
    }
    print("Obteniendo contexto en vivo...")
    ctx = fetch_live_event_context(test_ev)
    print("\nCONTEXTO EXTRAÍDO:\n", ctx)

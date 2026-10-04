import os
import sys
import json
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
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            parts = data.get("candidates", [])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if "text" in p).strip()
            return text
    except Exception as e:
        return ""

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

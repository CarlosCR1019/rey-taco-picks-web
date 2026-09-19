import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from supabase import create_client

MEXICO_TZ = ZoneInfo("America/Mexico_City")
load_dotenv("backend/.env")
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
if not url or not key:
    load_dotenv(".env")
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

sb = create_client(url, key)

picks_data = [
    # --- VENTANA 1: MADRUGADA (00:00 a 06:00 CDMX) ---
    {
        "categoria": "Fútbol",
        "partido": "Chungnam Asan vs Cheonan City FC",
        "pick": "Más de 2.5",
        "cuota": "1.75",
        "confianza": "62% respaldo de datos",
        "razonamiento": "Copa de Corea con proyecciones ofensivas elevadas y alta tasa de conversión en transiciones rápidas (+EV 5.0%).",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "Copa de Corea",
        "mercado": "Totales de Goles (2.5)",
        "riesgo": "Moderado",
        "fecha_generacion": "2026-09-18",
        "fecha_evento": "2026-09-19",
        "horario": "Mañana 01:30 hrs",
        "visibility": "public"
    },
    {
        "categoria": "Fútbol",
        "partido": "Jeonnam Dragons vs Suwon FC",
        "pick": "Suwon FC",
        "cuota": "1.83",
        "confianza": "58% respaldo de datos",
        "razonamiento": "Suwon FC llega con diferencial xG superior (+0.45) e invicto de visitante (+EV 3.1%).",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "K-League",
        "mercado": "Línea de Dinero (1X2)",
        "riesgo": "Moderado",
        "fecha_generacion": "2026-09-18",
        "fecha_evento": "2026-09-19",
        "horario": "Mañana 01:30 hrs",
        "visibility": "subscriber"
    },
    # --- VENTANA 2: MAÑANA (06:00 a 12:00 CDMX) ---
    {
        "categoria": "Fútbol",
        "partido": "Brighton vs Arsenal",
        "pick": "Arsenal",
        "cuota": "1.70",
        "confianza": "64% respaldo de datos",
        "razonamiento": "Arsenal registra una solidez defensiva élite con solo 0.78 xG concedido por 90 min (+EV 5.5%).",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "Premier League",
        "mercado": "Línea de Dinero (1X2)",
        "riesgo": "Bajo",
        "fecha_generacion": "2026-09-18",
        "fecha_evento": "2026-09-19",
        "horario": "Mañana 08:00 hrs",
        "visibility": "public"
    },
    {
        "categoria": "Fútbol",
        "partido": "VfB Stuttgart vs Borussia Dortmund",
        "pick": "Más de 3.5",
        "cuota": "1.95",
        "confianza": "56% respaldo de datos",
        "razonamiento": "Dos de las ofensivas más agresivas de Europa promediando 3.82 xG conjunto (+EV 6.1%).",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "Bundesliga",
        "mercado": "Totales de Goles (3.5)",
        "riesgo": "Moderado",
        "fecha_generacion": "2026-09-18",
        "fecha_evento": "2026-09-19",
        "horario": "Mañana 10:30 hrs",
        "visibility": "subscriber"
    },
    # --- VENTANA 3: TARDE (12:00 a 18:00 CDMX) ---
    {
        "categoria": "Fútbol",
        "partido": "Sevilla FC vs FC Barcelona",
        "pick": "Menos de 3.5",
        "cuota": "2.05",
        "confianza": "54% respaldo de datos",
        "razonamiento": "Planteamiento de repliegue bajo en el Sánchez-Pizjuán con valor estadístico en línea alta (+EV 7.4%).",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "LaLiga",
        "mercado": "Totales de Goles (3.5)",
        "riesgo": "Moderado",
        "fecha_generacion": "2026-09-18",
        "fecha_evento": "2026-09-19",
        "horario": "Mañana 13:00 hrs",
        "visibility": "public"
    },
    {
        "categoria": "Fútbol",
        "partido": "Sporting Lisboa vs Arouca",
        "pick": "Sporting Lisboa",
        "cuota": "1.18",
        "confianza": "86% respaldo de datos",
        "razonamiento": "Inexpugnable local en el José Alvalade; base segura para acumulador de cuota institucional.",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "Primeira Liga",
        "mercado": "Línea de Dinero (1X2)",
        "riesgo": "Bajo",
        "fecha_generacion": "2026-09-18",
        "fecha_evento": "2026-09-19",
        "horario": "Mañana 13:30 hrs",
        "visibility": "subscriber"
    },
    # --- VENTANA 4: NOCHE (18:00 a 24:00 CDMX) ---
    {
        "categoria": "Fútbol",
        "partido": "América vs Guadalajara Chivas",
        "pick": "Menos de 2.5",
        "cuota": "2.00",
        "confianza": "55% respaldo de datos",
        "razonamiento": "Clásico Nacional de alta fricción táctica; 1.83 goles de promedio histórico en fase regular (+EV 6.7%).",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "Liga MX",
        "mercado": "Totales de Goles (2.5)",
        "riesgo": "Moderado",
        "fecha_generacion": "2026-09-18",
        "fecha_evento": "2026-09-19",
        "horario": "Mañana 21:15 hrs",
        "visibility": "public"
    },
    {
        "categoria": "Fútbol",
        "partido": "Monterrey vs Cruz Azul",
        "pick": "Más de 2.5",
        "cuota": "1.61",
        "confianza": "67% respaldo de datos",
        "razonamiento": "Duelo estelar en el Gigante de Acero con dos delanteras de alto volumen (+EV 4.9%).",
        "estado": "pendiente",
        "es_parlay": False,
        "liga": "Liga MX",
        "mercado": "Totales de Goles (2.5)",
        "riesgo": "Moderado",
        "fecha_generacion": "2026-09-18",
        "fecha_evento": "2026-09-19",
        "horario": "Mañana 19:10 hrs",
        "visibility": "subscriber"
    }
]

inserted_rows = []
for p in picks_data:
    # Check if exists
    existing = sb.table("picks").select("id").eq("partido", p["partido"]).eq("fecha_evento", p["fecha_evento"]).execute()
    if existing.data:
        print(f"Ya existe en base de datos: {p['partido']}")
        inserted_rows.append(existing.data[0])
    else:
        res = sb.table("picks").insert(p).execute()
        if res.data:
            print(f"Insertado exitosamente [{p['visibility'].upper()}]: {p['partido']} -> {p['pick']} @ {p['cuota']} ({p['horario']})")
            inserted_rows.append(res.data[0])
        else:
            print(f"Error insertando {p['partido']}")

print(f"\nTotal picks activos en cartera para el 19 de septiembre: {len(inserted_rows)}")

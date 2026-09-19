"""
scripts/scan_windows_schedule.py
Consulta los partidos reales programados para las ventanas:
- Ventana 1: 00:00 a 06:00 CDMX (18 de septiembre)
- Ventana 2: 06:00 a 12:00 CDMX (18 de septiembre)
"""
import requests
import json
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MEXICO_TZ = ZoneInfo("America/Mexico_City")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Origin": "https://www.sofascore.com",
    "Referer": "https://www.sofascore.com/"
}

# Consultar fecha de hoy/mañana (2026-09-18)
date_str = "2026-09-18"
url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date_str}"

try:
    r = requests.get(url, headers=headers, timeout=12)
    print(f"SofaScore API status: {r.status_code}")
    if r.status_code == 200:
        events = r.json().get("events", [])
        print(f"Total football events for {date_str}: {len(events)}")
        
        window_00_06 = []
        window_06_12 = []
        
        for ev in events:
            ts = ev.get("startTimestamp")
            if not ts:
                continue
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            dt_cdmx = dt_utc.astimezone(MEXICO_TZ)
            
            # Solo día 18 de septiembre en CDMX
            if dt_cdmx.day == 18:
                hour = dt_cdmx.hour
                home = ev.get("homeTeam", {}).get("name")
                away = ev.get("awayTeam", {}).get("name")
                tourn = ev.get("tournament", {}).get("name")
                category = ev.get("tournament", {}).get("category", {}).get("name", "")
                
                item = {
                    "match": f"{home} vs {away}",
                    "home": home,
                    "away": away,
                    "tournament": f"{category}: {tourn}",
                    "cdmx_time": dt_cdmx.strftime("%H:%M hrs CDMX"),
                    "hour": hour,
                    "timestamp": ts,
                    "event_id": ev.get("id")
                }
                
                if 0 <= hour < 6:
                    window_00_06.append(item)
                elif 6 <= hour < 12:
                    window_06_12.append(item)
                    
        print(f"\n🌙 Ventana 1 (00:00 - 06:00 CDMX): {len(window_00_06)} partidos")
        for i, m in enumerate(window_00_06[:10], 1):
            print(f"  [{i}] {m['cdmx_time']} | {m['tournament']} | {m['match']}")
            
        print(f"\n☀️ Ventana 2 (06:00 - 12:00 CDMX): {len(window_06_12)} partidos")
        for i, m in enumerate(window_06_12[:15], 1):
            print(f"  [{i}] {m['cdmx_time']} | {m['tournament']} | {m['match']}")
            
        with open("data/schedule_windows_18sep.json", "w", encoding="utf-8") as f:
            json.dump({"window_00_06": window_00_06, "window_06_12": window_06_12}, f, ensure_ascii=False, indent=2)
            
    else:
        print(f"Error o respuesta no 200: {r.text[:200]}")
except Exception as e:
    print(f"Excepción: {e}")

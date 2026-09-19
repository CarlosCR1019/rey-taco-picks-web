import requests
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MEXICO_TZ = ZoneInfo("America/Mexico_City")
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
}
date_str = "2026-09-19"
url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{date_str}"
r = requests.get(url, headers=headers, timeout=12)
print("Status:", r.status_code)
if r.status_code == 200:
    events = r.json().get("events", [])
    print(f"Total football matches on {date_str}: {len(events)}")
    
    windows = {"00-06": [], "06-12": [], "12-18": [], "18-24": []}
    for ev in events:
        ts = ev.get("startTimestamp")
        if not ts:
            continue
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(MEXICO_TZ)
        if dt.strftime("%Y-%m-%d") != date_str:
            continue
        h = dt.hour
        tourn = ev.get("tournament", {}).get("name", "")
        cat = ev.get("tournament", {}).get("category", {}).get("name", "")
        home = ev.get("homeTeam", {}).get("name", "")
        away = ev.get("awayTeam", {}).get("name", "")
        t_str = dt.strftime("%H:%M")
        match = f"{home} vs {away} [{cat}: {tourn}] @ {t_str} CDMX"
        if 0 <= h < 6:
            windows["00-06"].append(match)
        elif 6 <= h < 12:
            windows["06-12"].append(match)
        elif 12 <= h < 18:
            windows["12-18"].append(match)
        else:
            windows["18-24"].append(match)
            
    for k, v in windows.items():
        print(f"\n=== Ventana {k} ({len(v)} partidos) ===")
        for m in v[:8]:
            print("  *", m)

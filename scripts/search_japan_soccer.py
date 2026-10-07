import sys
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from curl_cffi import requests
from backend.multisport_cadence_engine import get_altenar_session

sys.stdout.reconfigure(encoding='utf-8')
MEXICO_TZ = ZoneInfo("America/Mexico_City")

session = get_altenar_session()
champ_ids = "3951,4173,4400"
overview_url = f"https://sb2frontend-altenar2.biahosted.com/api/widget/GetOverview?culture=es-ES&timezoneOffset=0&integration=playdoit2&deviceType=1&numFormat=en-GB&countryCode=MX&eventCount=0&sportId=66&champIds={champ_ids}&withLive=true"

res = session.get(overview_url, timeout=15)
if res.status_code == 200:
    events = res.json().get("events", [])
    print(f"Total Japanese soccer events: {len(events)}")
    for ev in events:
        sdate = ev.get("startDate", "")
        dt_utc = datetime.fromisoformat(sdate.replace("Z", "+00:00"))
        dt_cdmx = dt_utc.astimezone(MEXICO_TZ)
        print(f"ID: {ev.get('id')} | {ev.get('name')} | ChampId: {ev.get('champId')} | Date: {dt_cdmx.strftime('%Y-%m-%d %H:%M')} CDMX")
else:
    print(f"Error {res.status_code}")

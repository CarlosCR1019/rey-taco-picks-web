import json
from pathlib import Path

p = Path("data/cartelera_multisport.json")
if p.exists():
    events = json.loads(p.read_text(encoding="utf-8"))
    print(f"Total cached events: {len(events)}")
    afternoon = []
    for e in events:
        t = e.get("time", "")
        if t and ":" in t:
            try:
                parts = t.split(":")
                hour = int(parts[0])
                if 12 <= hour < 18:
                    afternoon.append(e)
            except Exception:
                pass
    print(f"Events in 12-18 window: {len(afternoon)}")
    for e in afternoon[:15]:
        print(f"{e.get('sport')} | {e.get('league')} | {e.get('time')} | {e.get('home_team')} vs {e.get('away_team')} | Odds: {e.get('odds_raw')}")

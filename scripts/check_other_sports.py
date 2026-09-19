import json

for sport_file in ["data/sports/tenis_mesa.json", "data/sports/dardos.json"]:
    data = json.load(open(sport_file, encoding="utf-8"))
    afternoon = []
    for e in data:
        t = e.get("time", "")
        if t and ":" in t:
            try:
                hour = int(t.split(":")[0])
                if 12 <= hour < 18:
                    afternoon.append(e)
            except:
                pass
    print(f"File: {sport_file} -> Afternoon events: {len(afternoon)}")
    for ev in afternoon[:5]:
        print(f"   {ev.get('time')} | {ev.get('home_team')} vs {ev.get('away_team')} | Odds: {ev.get('odds')}")

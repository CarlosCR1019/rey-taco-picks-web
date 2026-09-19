import json

for sport in ["futbol", "beisbol", "baloncesto", "tenis_mesa", "tenis"]:
    with open(f"data/sports/{sport}.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"\n=== {sport.upper()} ({len(data)} eventos) ===")
    for ev in data[:4]:
        clean_odds = [o.encode("ascii", "ignore").decode("ascii").strip() for o in ev.get("odds", [])]
        print(f"  * {ev.get('match')} | Hora: {ev.get('time')} | Cuotas: {clean_odds}")

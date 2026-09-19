import json

with open("data/baseball_playdoit.json", "r", encoding="utf-8") as f:
    events = json.load(f)

for ev in events:
    txt = ev.get("text", "")
    if "19/09" in txt and ev.get("odds"):
        print("="*60)
        print("LINES:", ev.get("lines"))
        clean_odds = [o.encode("ascii", "ignore").decode("ascii") for o in ev.get("odds", [])]
        print("ODDS:", clean_odds)

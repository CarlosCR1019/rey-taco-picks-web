import json

with open("data/baseball_playdoit.json", "r", encoding="utf-8") as f:
    events = json.load(f)

print(f"Total events in baseball_playdoit.json: {len(events)}")
matches = set()
for ev in events:
    text = ev.get("text", "")
    odds = [o.encode("ascii", "ignore").decode("ascii") for o in ev.get("odds", [])]
    lines = ev.get("lines", [])
    if len(lines) >= 3 and odds:
        # Find team names
        matches.add(lines[0] + " vs " + (lines[1] if len(lines) > 1 else ""))

print(f"Unique match candidates: {len(matches)}")
for m in list(matches)[:20]:
    print("  *", m)

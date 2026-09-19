import json

with open('data/cartelera_multisport.json', 'r', encoding='utf-8') as f:
    events = json.load(f)

seen = set()
unique_events = []
for e in events:
    m = e.get('match') or (e.get('home_team', '') + ' vs ' + e.get('away_team', ''))
    if m not in seen:
        seen.add(m)
        unique_events.append(e)

sat_events = [e for e in unique_events if '19/09' in e.get('date', '') or '19/09' in e.get('raw_text', '') or '19/09' in str(e.get('lines', ''))]

windows = {'00-06': [], '06-12': [], '12-18': [], '18-24': []}
for e in sat_events:
    t = e.get('time', '12:00')
    try:
        hour = int(t.split(':')[0])
    except Exception:
        hour = 12
    if 0 <= hour < 6:
        windows['00-06'].append(e)
    elif 6 <= hour < 12:
        windows['06-12'].append(e)
    elif 12 <= hour < 18:
        windows['12-18'].append(e)
    else:
        windows['18-24'].append(e)

for w, evs in windows.items():
    print(f"\n=================== VENTANA {w} ({len(evs)} eventos) ===================")
    for ev in evs:
        sp = ev.get('sport', '')
        lg = ev.get('league', '')
        ht = ev.get('home_team', '')
        at = ev.get('away_team', '')
        tm = ev.get('time', '')
        odds = [str(o).encode('ascii', 'ignore').decode('ascii') for o in ev.get('odds', [])]
        print(f"[{tm}] {sp} ({lg}): {ht} vs {at} | Odds: {odds[:4]}")

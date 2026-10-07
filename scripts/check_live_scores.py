import urllib.request
import json

headers = {'User-Agent': 'Mozilla/5.0'}
urls = [
    ('NBA', 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard'),
    ('MLB', 'https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard')
]

for sport, url in urls:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            print(f'=== {sport} Scoreboard ===')
            for ev in data.get('events', []):
                name = ev.get('name')
                status = ev.get('status', {}).get('type', {}).get('description')
                competitors = ev.get('competitions', [{}])[0].get('competitors', [])
                scores = [f"{c.get('team', {}).get('displayName')}: {c.get('score')}" for c in competitors]
                print(f"{name} | Status: {status} | Scores: {scores}")
    except Exception as e:
        print(f'{sport} Error:', e)

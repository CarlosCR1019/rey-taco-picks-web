import sys
from pathlib import Path
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import re

bb = json.load(open("data/baseball_playdoit.json", encoding="utf-8"))
tt = json.load(open("data/table_tennis_playdoit.json", encoding="utf-8"))

print(f"Total Baseball: {len(bb)} | Total Table Tennis: {len(tt)}")

print("\n" + "=" * 70)
print("⚾ BÉISBOL — LIGAS Y PARTIDOS EN PLAYDOIT")
print("=" * 70)
seen_bb = set()
for ev in bb:
    t = ev["text"]
    odds = " | ".join(ev["odds"][:4])
    # Filter out soccer banners
    if any(s in t for s in ["Bundesliga", "Premier League", "Liga J 2", "América", "Toluca", "Puebla"]):
        continue
    # Extract match
    lines = [l.strip() for l in t.split("//") if l.strip()]
    cleaned = " // ".join(lines[:6])
    if cleaned not in seen_bb and len(lines) >= 3:
        seen_bb.add(cleaned)
        print("  ->", cleaned)
        print("     ODDS:", odds)

print("\n" + "=" * 70)
print("🏓 TENIS DE MESA — LIGAS Y PARTIDOS EN PLAYDOIT")
print("=" * 70)
seen_tt = set()
for ev in tt:
    t = ev["text"]
    odds = " | ".join(ev["odds"][:4])
    if any(s in t for s in ["Bundesliga", "Premier League", "Liga J 2", "América", "Toluca"]):
        continue
    lines = [l.strip() for l in t.split("//") if l.strip()]
    cleaned = " // ".join(lines[:6])
    if cleaned not in seen_tt and len(lines) >= 3:
        seen_tt.add(cleaned)
        print("  ->", cleaned)
        print("     ODDS:", odds)

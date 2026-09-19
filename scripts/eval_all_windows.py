import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.cadence_orchestrator import run_cadence_evaluation
import json

summary = {}
for win in ["00-06", "06-12", "12-18", "18-24"]:
    res = run_cadence_evaluation(window_key=win)
    summary[win] = {
        "status": res.get("status"),
        "window_name": res.get("window_name"),
        "events": res.get("events_in_window", 0),
        "picks": res.get("approved_picks", [])
    }

print("\n" + "#"*70)
print("RESUMEN GLOBAL DE TODAS LAS VENTANAS:")
print("#"*70)
for win, data in summary.items():
    picks = data["picks"]
    print(f"\n[{win}] {data['window_name']}: {len(picks)} picks aprobados de {data['events']} eventos evaluados")
    for idx, p in enumerate(picks, 1):
        print(f"  {idx}. {p.get('sport')} | {p.get('match')}")
        print(f"     Selección: {p.get('pick')} @ {p.get('cuota')} | Horario: {p.get('time')} CDMX")
        print(f"     Ventaja (+EV): {p.get('ev_percent')}% | Confianza: {p.get('confianza')}")

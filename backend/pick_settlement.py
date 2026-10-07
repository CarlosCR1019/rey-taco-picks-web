"""
backend/pick_settlement.py
==========================
Liquida los picks de data/pick_tracking.json con marcadores finales reales y genera
el reporte de rendimiento (ROI, win rate, CLV) por deporte, mercado, rango de cuota y ventana.

Fuentes de resultados (gratuitas, accesibles desde el VPS):
- ESPN scoreboard: MLB (con entradas → permite liquidar F5), NBA, WNBA, NFL, NCAAF, fútbol.
- KBO oficial: eng.koreabaseball.com (DailySchedule)
- NPB oficial: npb.jp/bis/eng/{año}/games/gm{fecha}.html

Lo que no se puede liquidar con certeza (córners, props, medios tiempos, F5 de Asia,
mercados ambiguos) queda como MANUAL: nunca se adivina.

Uso:
    python backend/pick_settlement.py            # liquida pendientes
    python backend/pick_settlement.py --report   # imprime reporte
    python backend/pick_settlement.py --report --telegram   # y lo envía al admin
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

import requests

from backend.pick_tracker import load_tracking, save_tracking, norm, team_tokens, team_in_text, F5_KEYWORDS

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}
REPORT_FILE = REPO_ROOT / "data" / "pick_performance.json"
_cache: Dict[str, Any] = {}

NON_GRADABLE_KEYWORDS = ["esquina", "corner", "tarjeta", "remate", "tiro", "ponche", "jugador", "prop",
                         "anotador", "1er tiempo", "primer tiempo", "mitad", "cuarto", "periodo", "half",
                         "quarter", "primer inning", "1er inning", "par", "impar", "exacto"]


# ------------------------------------------------------------------ result sources
def _get(url: str) -> Optional[requests.Response]:
    if url in _cache:
        return _cache[url]
    try:
        r = requests.get(url, headers=UA, timeout=20)
        _cache[url] = r if r.status_code == 200 else None
    except Exception:
        _cache[url] = None
    return _cache[url]


def espn_path(sport: str, league: str) -> Optional[str]:
    lg = norm(league)
    if sport == "mlb":
        return "baseball/mlb" if "mlb" in lg else None
    if sport == "nba":
        if "wnba" in lg:
            return "basketball/wnba"
        return "basketball/nba" if "nba" in lg else None
    if sport == "nfl":
        if "ncaa" in lg or "college" in lg or "universit" in lg:
            return "football/college-football"
        return "football/nfl"
    if sport == "futbol":
        return "soccer/all"
    return None


def espn_games(path: str, day: datetime) -> List[Dict[str, Any]]:
    extra = "&groups=80&limit=400" if "college" in path else "&limit=400"
    r = _get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={day:%Y%m%d}{extra}")
    if not r:
        return []
    games = []
    for ev in r.json().get("events", []):
        try:
            comp = ev["competitions"][0]
            if not comp.get("status", ev.get("status", {})).get("type", {}).get("completed", False) and \
               not ev.get("status", {}).get("type", {}).get("completed", False):
                continue
            teams = {}
            for c in comp["competitors"]:
                t = c.get("team", {})
                names = " ".join(filter(None, [t.get("displayName"), t.get("shortDisplayName"), t.get("name"),
                                               t.get("location"), t.get("abbreviation")]))
                innings = [int(float(ls.get("value", 0))) for ls in c.get("linescores", []) or []]
                teams[c["homeAway"]] = {"name": t.get("displayName", ""), "alias": names,
                                        "score": int(float(c.get("score", 0))), "innings": innings}
            if "home" in teams and "away" in teams:
                games.append({"home": teams["home"], "away": teams["away"], "source": f"espn:{path}"})
        except Exception:
            continue
    return games


def kbo_games(day_kst: datetime) -> List[Dict[str, Any]]:
    r = _get("https://eng.koreabaseball.com/Schedule/DailySchedule.aspx")
    if not r:
        return []
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
    label = f"{day_kst:%m.%d}("
    i = txt.find(label)
    if i < 0:
        return []
    nxt = re.search(r"\d{2}\.\d{2}\([A-Z]{3}\)", txt[i + 8:])
    block = txt[i: i + 8 + (nxt.start() if nxt else 2000)]
    games = []
    for away, a_s, h_s, home in re.findall(r"\d{2}:\d{2} ([A-Z]+) (\d+):(\d+) ([A-Z]+)", block):
        games.append({"home": {"name": home, "alias": home, "score": int(h_s), "innings": []},
                      "away": {"name": away, "alias": away, "score": int(a_s), "innings": []},
                      "source": "kbo_official"})
    return games


def npb_games(day_jst: datetime) -> List[Dict[str, Any]]:
    r = _get(f"https://npb.jp/bis/eng/{day_jst:%Y}/games/gm{day_jst:%Y%m%d}.html")
    if not r:
        return []
    r.encoding = "utf-8"
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", r.text))
    txt = re.sub(r"(\|\s*)+", "| ", txt)
    games = []
    # Formato: | Local | 4 | Game 25 | Estadio | 7 | Visitante |
    for home, h_s, _venue, a_s, away in re.findall(
            r"\| ([A-Za-z.\- ]+?) \| (\d+) \| Game \d+ \| ([^|]+?) \| (\d+) \| ([A-Za-z.\- ]+?) \|", txt):
        games.append({"home": {"name": home, "alias": home, "score": int(h_s), "innings": []},
                      "away": {"name": away, "alias": away, "score": int(a_s), "innings": []},
                      "source": "npb_official"})
    return games


def _name_score(our: str, theirs_alias: str) -> float:
    a, b = team_tokens(our), team_tokens(theirs_alias)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / min(len(a), len(b))


def find_result(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        start = datetime.fromisoformat(str(p["start_time_utc"]).replace("Z", "+00:00"))
    except Exception:
        return None
    league = norm(p.get("league"))
    sport = p.get("sport")
    games: List[Dict[str, Any]] = []
    if sport == "mlb" and "kbo" in league:
        games = kbo_games(start + timedelta(hours=9))
    elif sport == "mlb" and ("npb" in league or "nippon" in league or "japon" in league):
        games = npb_games(start + timedelta(hours=9))
    else:
        path = espn_path(sport, p.get("league", ""))
        if path:
            for d in {(start - timedelta(hours=5)).date(), start.date()}:
                games += espn_games(path, datetime(d.year, d.month, d.day))
    home, away = p.get("home_team", ""), p.get("away_team", "")
    best, best_score = None, 0.0
    for g in games:
        s_direct = _name_score(home, g["home"]["alias"]) + _name_score(away, g["away"]["alias"])
        s_swap = _name_score(home, g["away"]["alias"]) + _name_score(away, g["home"]["alias"])
        if s_direct >= 1.0 and s_direct > best_score and _name_score(home, g["home"]["alias"]) > 0 \
                and _name_score(away, g["away"]["alias"]) > 0:
            best, best_score = {"hs": g["home"]["score"], "as": g["away"]["score"],
                                "hi": g["home"]["innings"], "ai": g["away"]["innings"], "source": g["source"]}, s_direct
        if s_swap >= 1.0 and s_swap > best_score and _name_score(home, g["away"]["alias"]) > 0 \
                and _name_score(away, g["home"]["alias"]) > 0:
            best, best_score = {"hs": g["away"]["score"], "as": g["home"]["score"],
                                "hi": g["away"]["innings"], "ai": g["home"]["innings"], "source": g["source"]}, s_swap
    return best


# ------------------------------------------------------------------------ grading
def is_non_gradable(text: str) -> bool:
    for k in NON_GRADABLE_KEYWORDS:
        if re.search(r"\b" + re.escape(k) + r"\b", text):
            return True
    return False


def _outcome(diff: float) -> str:
    return "WON" if diff > 0 else ("LOST" if diff < 0 else "VOID")


def grade(p: Dict[str, Any], res: Dict[str, Any]) -> Tuple[str, str]:
    text = p.get("altenar_selection") or p.get("pick") or ""
    market = (p.get("altenar_market") or "") + " " + (p.get("market_name") or "")
    pt_, mk = norm(p.get("pick", "") + " " + text), norm(market)
    home, away = p.get("home_team", ""), p.get("away_team", "")
    hs, as_ = res["hs"], res["as"]
    score_str = f"{home} {hs} - {as_} {away}"

    is_f5 = any(k in pt_ or k in mk for k in F5_KEYWORDS)
    if is_f5:
        if len(res.get("hi") or []) >= 5 and len(res.get("ai") or []) >= 5:
            hs, as_ = sum(res["hi"][:5]), sum(res["ai"][:5])
            score_str = f"F5: {home} {hs} - {as_} {away}"
        else:
            return "MANUAL", f"F5 sin entradas disponibles ({score_str})"
    elif is_non_gradable(pt_) or is_non_gradable(mk):
        return "MANUAL", f"mercado no liquidable automáticamente ({score_str})"

    sel = norm(text)
    tot = re.search(r"\b(mas|menos|over|under)\b(?:\s+de)?\s*(\d+(?:\.\d+)?)", sel)
    hcp = re.search(r"\(?([+-]\d+(?:\.\d+)?)\)?", sel)
    h_hits, a_hits = team_in_text(home, text), team_in_text(away, text)
    team_named = h_hits > 0 or a_hits > 0
    is_home = h_hits >= a_hits

    if tot:
        line = float(tot.group(2))
        over = tot.group(1) in ("mas", "over")
        team_total = team_named or ("equipo" in mk) or team_in_text(home, market) or team_in_text(away, market)
        if team_total:
            if not team_named:
                is_home = team_in_text(home, market) >= team_in_text(away, market)
            val = hs if is_home else as_
        else:
            val = hs + as_
        if (line * 2) % 1:
            return "MANUAL", f"línea asiática {line} ({score_str})"
        return _outcome((val - line) if over else (line - val)), f"{score_str} (línea {line})"

    if hcp and team_named:
        line = float(hcp.group(1))
        if (line * 2) % 1:
            return "MANUAL", f"hándicap asiático {line} ({score_str})"
        mine, opp = (hs, as_) if is_home else (as_, hs)
        return _outcome(mine + line - opp), f"{score_str} (hándicap {line:+})"

    if "empate" in sel and not team_named:
        return ("WON" if hs == as_ else "LOST"), score_str

    if team_named:
        mine, opp = (hs, as_) if is_home else (as_, hs)
        three_way = p.get("sport") == "futbol" or "1x2" in mk
        if "o empate" in sel or "doble" in mk:
            return ("WON" if mine >= opp else "LOST"), score_str
        if mine == opp:
            return ("LOST" if three_way else "VOID"), f"{score_str} (empate)"
        return ("WON" if mine > opp else "LOST"), score_str

    return "MANUAL", f"selección ambigua ({score_str})"


def settle_pending(min_hours_after_start: float = 2.0) -> int:
    data = load_tracking()
    now = datetime.now(timezone.utc)
    settled = 0
    for tid, p in data.items():
        if p.get("status") not in ("PENDING",):
            continue
        try:
            start = datetime.fromisoformat(str(p["start_time_utc"]).replace("Z", "+00:00"))
        except Exception:
            continue
        hours_since = (now - start).total_seconds() / 3600
        if hours_since < min_hours_after_start:
            continue
        res = find_result(p)
        if not res:
            if hours_since > 48:
                p["status"] = "MANUAL"
                p["result_detail"] = "sin marcador encontrado en 48h"
                settled += 1
            continue
        status, detail = grade(p, res)
        p["status"] = status
        p["result_detail"] = detail
        p["result_source"] = res["source"]
        p["settled_at_utc"] = now.isoformat()
        stake, odds = float(p.get("stake_units") or 1), float(p.get("odds_taken") or 0)
        p["profit_units"] = (round(stake * (odds - 1), 3) if status == "WON" else
                             -stake if status == "LOST" else 0.0 if status == "VOID" else None)
        print(f"🧾 {tid} | {p.get('match')} | {p.get('pick')} @ {odds} → {status} ({detail})")
        settled += 1
    if settled:
        save_tracking(data)
    return settled


# ------------------------------------------------------------------------- report
def _market_family(p: Dict[str, Any]) -> str:
    t = norm((p.get("altenar_market") or "") + " " + (p.get("pick") or ""))
    if any(k in t for k in F5_KEYWORDS):
        return "F5"
    if re.search(r"\b(mas|menos|over|under)\b", t):
        return "Totales"
    if re.search(r"[+-]\d", t) or "handicap" in t:
        return "Hándicap"
    return "Ganador"


def _odds_bucket(o: float) -> str:
    if o < 1.70:
        return "1.55-1.69"
    if o < 1.90:
        return "1.70-1.89"
    if o < 2.10:
        return "1.90-2.09"
    return "2.10+"


def build_report() -> Dict[str, Any]:
    data = load_tracking()
    graded = [p for p in data.values() if p.get("status") in ("WON", "LOST", "VOID")]

    def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        w = sum(1 for r in rows if r["status"] == "WON")
        l = sum(1 for r in rows if r["status"] == "LOST")
        v = sum(1 for r in rows if r["status"] == "VOID")
        staked = sum(float(r.get("stake_units") or 1) for r in rows if r["status"] != "VOID")
        units = round(sum(float(r.get("profit_units") or 0) for r in rows), 2)
        clvs = [r["odds_taken"] / r["closing_odds"] - 1 for r in rows if r.get("closing_odds")]
        return {"n": len(rows), "W": w, "L": l, "P": v, "units": units,
                "roi_pct": round(units / staked * 100, 1) if staked else 0.0,
                "avg_clv_pct": round(sum(clvs) / len(clvs) * 100, 2) if clvs else None,
                "clv_samples": len(clvs)}

    groups: Dict[str, Dict[str, List]] = {"deporte": defaultdict(list), "mercado": defaultdict(list),
                                          "cuota": defaultdict(list), "ventana": defaultdict(list)}
    for p in graded:
        groups["deporte"][p.get("sport") or "?"].append(p)
        groups["mercado"][_market_family(p)].append(p)
        groups["cuota"][_odds_bucket(float(p.get("odds_taken") or 0))].append(p)
        groups["ventana"][p.get("window") or "?"].append(p)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_registrados": len(data),
        "pendientes": sum(1 for p in data.values() if p.get("status") == "PENDING"),
        "manual": sum(1 for p in data.values() if p.get("status") == "MANUAL"),
        "global": summarize(graded),
        **{k: {g: summarize(rows) for g, rows in v.items()} for k, v in groups.items()},
    }
    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def report_text(r: Dict[str, Any]) -> str:
    g = r["global"]
    lines = ["📊 REY TACO — RENDIMIENTO VERIFICADO",
             f"Registrados: {r['total_registrados']} | Liquidados: {g['n']} | Pendientes: {r['pendientes']} | Revisión manual: {r['manual']}",
             f"Global: {g['W']}-{g['L']}-{g['P']} | {g['units']:+.2f}U | ROI {g['roi_pct']:+.1f}%"
             + (f" | CLV {g['avg_clv_pct']:+.2f}% (n={g['clv_samples']})" if g["avg_clv_pct"] is not None else "")]
    for sec, title in [("deporte", "Por deporte"), ("mercado", "Por mercado"), ("cuota", "Por cuota"), ("ventana", "Por ventana")]:
        lines.append(f"\n{title}:")
        for k, s in sorted(r[sec].items(), key=lambda kv: -kv[1]["n"]):
            lines.append(f"  • {k}: {s['W']}-{s['L']}-{s['P']} | {s['units']:+.2f}U | ROI {s['roi_pct']:+.1f}%")
    if g["n"] < 50:
        lines.append(f"\n⚠️ Muestra pequeña ({g['n']}). Con menos de ~50 picks el ROI es mayormente ruido; el CLV es mejor señal temprana.")
    return "\n".join(lines)


if __name__ == "__main__":
    n = settle_pending()
    print(f"✅ Picks liquidados en esta pasada: {n}")
    if "--report" in sys.argv:
        txt = report_text(build_report())
        print(txt)
        if "--telegram" in sys.argv:
            from dotenv import load_dotenv
            load_dotenv(REPO_ROOT / "backend" / ".env")
            from backend.interactive_telegram_dispatcher import telegram_api_call, ADMIN_CHAT_ID
            telegram_api_call("sendMessage", {"chat_id": ADMIN_CHAT_ID, "text": txt})

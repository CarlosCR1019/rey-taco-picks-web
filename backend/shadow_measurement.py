"""
backend/shadow_measurement.py
=============================
Modo Sombra (Shadow Measurement) 100% No-Intrusivo y Autocontenido para Rey Taco Picks.

IMPORTANTE:
- Este módulo es ESTRICTAMENTE DE SOLO LECTURA respecto a los archivos de producción
  (`verified_record.json`, `frontend/public/verified_record.json`, `audit_ledger.jsonl`,
   `settled_picks_history.json`, `pick_tracking.json`).
- NUNCA modifica lo que está publicado arriba ni altera el despacho de picks.
- Únicamente mide, calcula telemetría estadística (CLV, Brier/Log-Loss pareados,
  ROI por banda de cuota, ventanas móviles, drawdown y rechazos de compuerta) y guarda
  snapshots locales en `data/shadow_measurements/`.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.audit_ledger import (
    AUDIT_LEDGER_PATH,
    REJECTED_PICKS_PATH,
    get_ledger_state,
    verify_ledger_integrity,
)

MEXICO_TZ = ZoneInfo("America/Mexico_City")
SHADOW_DIR = REPO_ROOT / "data" / "shadow_measurements"
SHADOW_LOG_PATH = SHADOW_DIR / "shadow_telemetry_log.jsonl"
SHADOW_LATEST_PATH = SHADOW_DIR / "latest_shadow_report.json"
PRICE_GATE_REJECTIONS_PATH = REPO_ROOT / "data" / "price_gate_rejections.jsonl"
PICK_TRACKING_PATH = REPO_ROOT / "data" / "pick_tracking.json"

ACTIVE_CORE_SPORTS = ("nba", "nfl", "tennis")
PAUSED_SPORTS = ("soccer", "baseball")


def _resolve_settled_history_path() -> Path:
    local_data = REPO_ROOT / "data" / "settled_picks_history.json"
    if local_data.exists():
        return local_data
    public_data = REPO_ROOT / "frontend" / "public" / "settled_picks_history.json"
    if public_data.exists():
        return public_data
    return local_data


def _classify_sport_bucket(raw_sport: str = "", category: str = "") -> str:
    s = str(raw_sport or "").lower().strip()
    c = str(category or "").lower()
    if s in ("nba", "basketball", "basket") or "🏀" in c or "nba" in c or "euroliga" in c or "acb" in c:
        return "nba"
    if s in ("nfl", "american_football") or "🏈" in c or "nfl" in c or "ncaaf" in c:
        return "nfl"
    if s in ("tennis", "tenis") or "🎾" in c or "atp" in c or "wta" in c:
        return "tennis"
    if s in ("mlb", "baseball", "kbo", "npb") or "⚾" in c or any(k in c for k in ("mlb", "kbo", "npb")):
        return "baseball"
    return "soccer"


def _empty_bucket() -> Dict[str, Any]:
    return {"won": 0, "lost": 0, "void": 0, "net_units": 0.0, "settled_picks": 0, "win_rate_pct": 0.0, "roi_pct": 0.0}


def _finalize_bucket(b: Dict[str, Any]) -> Dict[str, Any]:
    settled = b["won"] + b["lost"]
    b["settled_picks"] = settled
    b["net_units"] = round(b["net_units"], 2)
    b["win_rate_pct"] = round((b["won"] / settled) * 100, 1) if settled > 0 else 0.0
    b["roi_pct"] = round((b["net_units"] / settled) * 100, 1) if settled > 0 else 0.0
    return b


def _replay_ledger_tickets_readonly(ledger_path: Path = AUDIT_LEDGER_PATH) -> Dict[str, Dict[str, Any]]:
    tickets: Dict[str, Dict[str, Any]] = {}
    if not ledger_path.exists():
        return tickets
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                block = json.loads(stripped)
                tid = block.get("ticket_id")
                payload = block.get("payload") or {}
                if not tid:
                    continue
                rec = tickets.setdefault(tid, {"ticket_id": tid})
                rec.update(payload)
                ev = block.get("event_type")
                if ev == "PICK_SETTLED":
                    rec["status"] = str(payload.get("outcome") or payload.get("status") or "SETTLED").upper()
                elif ev == "PICK_PUBLISHED" and rec.get("status") not in ("WON", "LOST", "VOID"):
                    rec["status"] = "PUBLISHED"
    except Exception:
        pass
    return tickets


def _odds_band(odds: float) -> str:
    if odds < 1.70:
        return "favorito_fuerte (<1.70)"
    if odds < 2.00:
        return "linea_principal (1.70-1.99)"
    if odds < 2.50:
        return "plus_money (2.00-2.49)"
    return "underdog_alto (2.50+)"


def _load_settled_records_readonly() -> List[Dict[str, Any]]:
    """Lee el historial liquidado sin modificar ningún archivo."""
    records: List[Dict[str, Any]] = []
    history_path = _resolve_settled_history_path()
    if history_path.exists():
        try:
            payload = json.loads(history_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("settled_picks"), list):
                records = list(payload["settled_picks"])
            elif isinstance(payload, list):
                records = list(payload)
        except Exception:
            records = []

    if not records and PICK_TRACKING_PATH.exists():
        try:
            raw = json.loads(PICK_TRACKING_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for item in raw.values():
                    st = str(item.get("status", "")).upper()
                    if st in ("WON", "LOST", "VOID"):
                        records.append({
                            "sport": item.get("sport", ""),
                            "categoria": item.get("league", ""),
                            "estado": "ganado" if st == "WON" else ("perdido" if st == "LOST" else "void"),
                            "cuota": float(item.get("odds_taken") or item.get("odds") or 1.90),
                            "clv_pct": item.get("clv_pct"),
                            "fecha": item.get("settled_at") or item.get("created_at") or "",
                        })
        except Exception:
            records = []
    return records


def _compute_portfolio_summary_readonly(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    all_bucket = _empty_bucket()
    core_bucket = _empty_bucket()
    by_sport: Dict[str, Dict[str, Any]] = {
        sp: _empty_bucket() for sp in (*ACTIVE_CORE_SPORTS, *PAUSED_SPORTS)
    }

    for rec in records:
        st = str(rec.get("estado") or rec.get("status") or "").lower().strip()
        if st in ("ganado", "ganada", "won", "win", "w"):
            outcome = "won"
        elif st in ("perdido", "perdida", "lost", "loss", "l"):
            outcome = "lost"
        elif st in ("void", "push", "nulo"):
            outcome = "void"
        else:
            continue

        try:
            odds = float(rec.get("cuota") or rec.get("odds_taken") or rec.get("odds") or 1.90)
        except Exception:
            odds = 1.90
        if odds <= 1.0:
            odds = 1.90

        sport_key = _classify_sport_bucket(rec.get("sport", ""), rec.get("categoria", ""))
        targets = [all_bucket, by_sport[sport_key]]
        if sport_key in ACTIVE_CORE_SPORTS:
            targets.append(core_bucket)

        for bucket in targets:
            if outcome == "won":
                bucket["won"] += 1
                bucket["net_units"] += (odds - 1.0)
            elif outcome == "lost":
                bucket["lost"] += 1
                bucket["net_units"] -= 1.0
            else:
                bucket["void"] += 1

    _finalize_bucket(all_bucket)
    _finalize_bucket(core_bucket)
    for sp in by_sport:
        _finalize_bucket(by_sport[sp])

    return {
        "active_core_portfolio": {
            **core_bucket,
            "active_sports": list(ACTIVE_CORE_SPORTS),
            "paused_sports": list(PAUSED_SPORTS),
        },
        "historical_all_sports": all_bucket,
        "by_sport": by_sport,
    }


def _compute_odds_band_breakdown(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    bands: Dict[str, Dict[str, Any]] = {
        "favorito_fuerte (<1.70)": {"won": 0, "lost": 0, "void": 0, "net_units": 0.0, "implied_prob_sum": 0.0},
        "linea_principal (1.70-1.99)": {"won": 0, "lost": 0, "void": 0, "net_units": 0.0, "implied_prob_sum": 0.0},
        "plus_money (2.00-2.49)": {"won": 0, "lost": 0, "void": 0, "net_units": 0.0, "implied_prob_sum": 0.0},
        "underdog_alto (2.50+)": {"won": 0, "lost": 0, "void": 0, "net_units": 0.0, "implied_prob_sum": 0.0},
    }

    for rec in records:
        st = str(rec.get("estado") or rec.get("status") or "").lower().strip()
        try:
            odds = float(rec.get("cuota") or rec.get("odds_taken") or rec.get("odds") or 1.90)
        except Exception:
            odds = 1.90
        if odds <= 1.0:
            odds = 1.90

        band = bands[_odds_band(odds)]
        if st in ("ganado", "ganada", "won", "win", "w"):
            band["won"] += 1
            band["net_units"] += (odds - 1.0)
            band["implied_prob_sum"] += (1.0 / odds)
        elif st in ("perdido", "perdida", "lost", "loss", "l"):
            band["lost"] += 1
            band["net_units"] -= 1.0
            band["implied_prob_sum"] += (1.0 / odds)
        elif st in ("void", "push", "nulo"):
            band["void"] += 1

    out: Dict[str, Dict[str, Any]] = {}
    for name, b in bands.items():
        settled = b["won"] + b["lost"]
        win_rate = (b["won"] / settled) if settled > 0 else 0.0
        implied_avg = (b["implied_prob_sum"] / settled) if settled > 0 else 0.0
        out[name] = {
            "settled_picks": settled,
            "won": b["won"],
            "lost": b["lost"],
            "void": b["void"],
            "net_units": round(b["net_units"], 2),
            "win_rate_pct": round(win_rate * 100, 1),
            "implied_breakeven_pct": round(implied_avg * 100, 1),
            "edge_over_breakeven_pp": round((win_rate - implied_avg) * 100, 2) if settled > 0 else 0.0,
            "roi_pct": round((b["net_units"] / settled) * 100, 1) if settled > 0 else 0.0,
        }
    return out


def _compute_equity_and_drawdown(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    outcomes_units: List[float] = []
    pseudo_brier_errors: List[float] = []

    for rec in records:
        st = str(rec.get("estado") or rec.get("status") or "").lower().strip()
        try:
            odds = float(rec.get("cuota") or rec.get("odds_taken") or rec.get("odds") or 1.90)
        except Exception:
            odds = 1.90
        if odds <= 1.0:
            odds = 1.90

        implied_p = min(0.99, max(0.01, 1.0 / odds))
        if st in ("ganado", "ganada", "won", "win", "w"):
            u = odds - 1.0
            outcomes_units.append(u)
            pseudo_brier_errors.append((implied_p - 1.0) ** 2)
        elif st in ("perdido", "perdida", "lost", "loss", "l"):
            u = -1.0
            outcomes_units.append(u)
            pseudo_brier_errors.append((implied_p - 0.0) ** 2)
        else:
            continue

        cumulative += u
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd

    rolling_windows: Dict[str, Dict[str, float]] = {}
    for w in (10, 25, 50):
        if len(outcomes_units) >= w:
            slice_u = outcomes_units[-w:]
            wins = sum(1 for x in slice_u if x > 0)
            net_u = sum(slice_u)
            rolling_windows[f"last_{w}"] = {
                "picks": w,
                "win_rate_pct": round((wins / w) * 100, 1),
                "net_units": round(net_u, 2),
                "roi_pct": round((net_u / w) * 100, 1),
            }

    return {
        "total_settled": len(outcomes_units),
        "cumulative_net_units": round(cumulative, 2),
        "peak_units": round(peak, 2),
        "max_drawdown_units": round(max_dd, 2),
        "market_implied_brier_baseline": round(sum(pseudo_brier_errors) / len(pseudo_brier_errors), 4)
        if pseudo_brier_errors else None,
        "rolling_windows": rolling_windows,
    }


def _compute_clv_telemetry() -> Dict[str, Any]:
    clv_values: List[float] = []
    clv_moved: List[float] = []
    by_sport_raw: Dict[str, List[float]] = {}

    if PICK_TRACKING_PATH.exists():
        try:
            raw = json.loads(PICK_TRACKING_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for item in raw.values():
                    clv = item.get("clv_pct")
                    if not (isinstance(clv, (int, float)) and math.isfinite(clv)):
                        taken = item.get("odds_taken") or item.get("odds")
                        closing = item.get("closing_odds")
                        if (
                            isinstance(taken, (int, float))
                            and isinstance(closing, (int, float))
                            and math.isfinite(taken)
                            and math.isfinite(closing)
                            and taken > 1.0
                            and closing > 1.0
                        ):
                            clv = ((float(taken) / float(closing)) - 1.0) * 100.0
                    if isinstance(clv, (int, float)) and math.isfinite(clv):
                        val = float(clv)
                        clv_values.append(val)
                        if abs(val) > 1e-6:
                            clv_moved.append(val)
                        sp = _classify_sport_bucket(item.get("sport", ""), item.get("league", ""))
                        by_sport_raw.setdefault(sp, []).append(val)
        except Exception:
            pass

    if not clv_values:
        return {
            "samples": 0,
            "mean_clv_pct": None,
            "median_clv_pct": None,
            "positive_clv_rate_pct": None,
            "moved_lines_samples": 0,
            "mean_moved_clv_pct": None,
            "moved_positive_rate_pct": None,
            "by_sport": {},
        }

    pos_all = sum(1 for v in clv_values if v > 1e-6)
    pos_moved = sum(1 for v in clv_moved if v > 1e-6)
    neg_moved = sum(1 for v in clv_moved if v < -1e-6)

    by_sport_summary: Dict[str, Dict[str, Any]] = {}
    for sp, vals in sorted(by_sport_raw.items()):
        moved = [v for v in vals if abs(v) > 1e-6]
        pos_sp = sum(1 for v in moved if v > 1e-6)
        neg_sp = sum(1 for v in moved if v < -1e-6)
        by_sport_summary[sp] = {
            "samples": len(vals),
            "mean_clv_pct": round(statistics.mean(vals), 2),
            "median_clv_pct": round(statistics.median(vals), 2),
            "moved_lines": len(moved),
            "mean_moved_clv_pct": round(statistics.mean(moved), 2) if moved else 0.0,
            "beat_closing_count": pos_sp,
            "lost_closing_count": neg_sp,
            "moved_positive_rate_pct": round((pos_sp / len(moved)) * 100, 1) if moved else 0.0,
        }

    return {
        "samples": len(clv_values),
        "mean_clv_pct": round(statistics.mean(clv_values), 2),
        "median_clv_pct": round(statistics.median(clv_values), 2),
        "positive_clv_rate_pct": round((pos_all / len(clv_values)) * 100, 1),
        "moved_lines_samples": len(clv_moved),
        "mean_moved_clv_pct": round(statistics.mean(clv_moved), 2) if clv_moved else 0.0,
        "beat_closing_count": pos_moved,
        "lost_closing_count": neg_moved,
        "moved_positive_rate_pct": round((pos_moved / len(clv_moved)) * 100, 1) if clv_moved else 0.0,
        "by_sport": by_sport_summary,
    }


def _compute_paired_brier_and_logloss() -> Dict[str, Any]:
    all_pairs: List[tuple[str, float, float, float]] = []
    if PICK_TRACKING_PATH.exists():
        try:
            raw = json.loads(PICK_TRACKING_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for item in raw.values():
                    st = str(item.get("status") or "").upper()
                    taken = item.get("odds_taken") or item.get("odds")
                    closing = item.get("closing_odds")
                    margin = item.get("market_margin")
                    if not (isinstance(margin, (int, float)) and math.isfinite(margin) and 0 <= margin < 0.5):
                        margin = 0.05
                    if (
                        st in ("WON", "LOST")
                        and isinstance(taken, (int, float))
                        and isinstance(closing, (int, float))
                        and taken > 1.0
                        and closing > 1.0
                    ):
                        y = 1.0 if st == "WON" else 0.0
                        p_taken = min(0.99, max(0.01, (1.0 / float(taken)) / (1.0 + float(margin))))
                        p_close = min(0.99, max(0.01, (1.0 / float(closing)) / (1.0 + float(margin))))
                        sp = _classify_sport_bucket(item.get("sport", ""), item.get("league", ""))
                        all_pairs.append((sp, y, p_taken, p_close))
        except Exception:
            pass

    def _summarize_pairs(rows: List[tuple[str, float, float, float]]) -> Dict[str, Any]:
        n = len(rows)
        if n == 0:
            return {"paired_settled_samples": 0}
        bs_entry = sum((pt - y) ** 2 for _, y, pt, _ in rows) / n
        bs_close = sum((pc - y) ** 2 for _, y, _, pc in rows) / n
        ll_entry = -sum(y * math.log(pt) + (1.0 - y) * math.log(1.0 - pt) for _, y, pt, _ in rows) / n
        ll_close = -sum(y * math.log(pc) + (1.0 - y) * math.log(1.0 - pc) for _, y, _, pc in rows) / n
        base_rate = sum(y for _, y, _, _ in rows) / n
        bs_clim = sum((base_rate - y) ** 2 for _, y, _, _ in rows) / n
        return {
            "paired_settled_samples": n,
            "empirical_win_rate": round(base_rate, 4),
            "climatology_brier_reference": round(bs_clim, 4),
            "entry_devig_brier_score": round(bs_entry, 4),
            "closing_devig_brier_score": round(bs_close, 4),
            "closing_vs_entry_brier_delta": round(bs_close - bs_entry, 4),
            "entry_devig_log_loss": round(ll_entry, 4),
            "closing_devig_log_loss": round(ll_close, 4),
            "closing_vs_entry_logloss_delta": round(ll_close - ll_entry, 4),
        }

    core_pairs = [r for r in all_pairs if r[0] in ("nba", "nfl", "tennis")]
    return {
        "all_tracked_sports": _summarize_pairs(all_pairs),
        "active_core_portfolio": _summarize_pairs(core_pairs),
    }


def _compute_rejection_telemetry() -> Dict[str, Any]:
    rejected_reasons: Dict[str, int] = {}
    rejected_total = 0
    if REJECTED_PICKS_PATH.exists():
        try:
            with open(REJECTED_PICKS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rejected_total += 1
                    try:
                        row = json.loads(line)
                        reason = str(row.get("rejection_reason") or row.get("reason") or "UNSPECIFIED")
                        rejected_reasons[reason] = rejected_reasons.get(reason, 0) + 1
                    except Exception:
                        rejected_reasons["PARSE_ERROR"] = rejected_reasons.get("PARSE_ERROR", 0) + 1
        except Exception:
            pass

    price_gate_total = 0
    if PRICE_GATE_REJECTIONS_PATH.exists():
        try:
            with open(PRICE_GATE_REJECTIONS_PATH, "r", encoding="utf-8") as f:
                price_gate_total = sum(1 for line in f if line.strip())
        except Exception:
            pass

    return {
        "rejected_picks_total": rejected_total,
        "price_gate_rejections_total": price_gate_total,
        "rejection_reasons_breakdown": rejected_reasons,
    }


def run_shadow_measurement(*, persist: bool = True) -> Dict[str, Any]:
    """
    Ejecuta la medición completa en modo sombra (read-only sobre producción)
    y persiste la instantánea únicamente en `data/shadow_measurements/`.
    """
    now_utc = datetime.now(timezone.utc).isoformat()
    now_cdmx = datetime.now(MEXICO_TZ).strftime("%Y-%m-%d %H:%M:%S")

    is_valid_chain, block_count, chain_msg = verify_ledger_integrity()
    ledger_state = get_ledger_state()
    ledger_tickets = _replay_ledger_tickets_readonly()

    calibrated_ledger_samples = sum(
        1
        for t in ledger_tickets.values()
        if t.get("status") in ("WON", "LOST")
        and isinstance(t.get("calibrated_probability"), (int, float))
        and math.isfinite(t["calibrated_probability"])
    )

    records = _load_settled_records_readonly()
    portfolio_summary = _compute_portfolio_summary_readonly(records)
    odds_bands = _compute_odds_band_breakdown(records)
    equity_metrics = _compute_equity_and_drawdown(records)
    clv_telemetry = _compute_clv_telemetry()
    paired_calibration = _compute_paired_brier_and_logloss()
    rejection_telemetry = _compute_rejection_telemetry()

    snapshot = {
        "mode": "SHADOW_MEASUREMENT_READONLY",
        "affects_production": False,
        "measured_at_utc": now_utc,
        "measured_at_cdmx": now_cdmx,
        "ledger_health": {
            "chain_integrity_verified": is_valid_chain,
            "total_blocks": block_count,
            "status_message": chain_msg,
            "total_tickets_in_ledger": ledger_state.get("total_tickets", 0),
            "settled_tickets_in_ledger": ledger_state.get("settled_tickets", 0),
            "calibrated_settled_samples": calibrated_ledger_samples,
            "samples_needed_for_formal_brier": max(0, 30 - calibrated_ledger_samples),
        },
        "portfolio_measurement": portfolio_summary,
        "odds_band_performance": odds_bands,
        "equity_and_drawdown": equity_metrics,
        "clv_telemetry": clv_telemetry,
        "paired_brier_and_logloss_calibration": paired_calibration,
        "gate_and_veto_telemetry": rejection_telemetry,
    }

    if persist:
        SHADOW_DIR.mkdir(parents=True, exist_ok=True)
        with open(SHADOW_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
        with open(SHADOW_LATEST_PATH, "w", encoding="utf-8") as latest_file:
            json.dump(snapshot, latest_file, ensure_ascii=False, indent=2)

    return snapshot


if __name__ == "__main__":
    report = run_shadow_measurement(persist=True)
    print("=" * 72)
    print("🌮 REY TACO PICKS — MEDICIÓN EN MODO SOMBRA (SOLO LECTURA / NO INTRUSIVO)")
    print("=" * 72)
    print(json.dumps(report, ensure_ascii=False, indent=2))

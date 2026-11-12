"""
scripts/export_settled_history.py
==================================
Exporta el historial auditado de picks de `data/pick_tracking.json`
a `data/settled_picks_history.json` y lo sincroniza con Cloudflare R2
para que https://reytacopicks.com muestre los resultados actualizados de Octubre y Noviembre.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MEXICO_TZ = ZoneInfo("America/Mexico_City")


def export_settled_history() -> Path:
    tracking_file = REPO_ROOT / "data" / "pick_tracking.json"
    if not tracking_file.exists():
        print(f"No existe {tracking_file}")
        return None

    raw = json.loads(tracking_file.read_text(encoding="utf-8"))

    rows = []
    won_count = 0
    lost_count = 0
    void_count = 0
    units_total = 0.0

    for tid, item in raw.items():
        st_raw = str(item.get("status", "")).upper()
        if st_raw == "WON":
            estado = "ganado"
        elif st_raw == "LOST":
            estado = "perdido"
        elif st_raw == "VOID":
            estado = "void"
        elif st_raw == "PENDING":
            estado = "pendiente"
        else:
            continue

        sport = str(item.get("sport", "")).lower()
        league = str(item.get("league", "")).strip()
        if not league:
            if sport == "nba":
                league = "🏀 NBA"
            elif sport == "nfl":
                league = "🏈 NFL"
            elif sport == "tennis":
                league = "🎾 Tenis"
            elif sport == "mlb":
                league = "⚾ MLB"
            else:
                league = "⚽ Fútbol"

        odds = float(item.get("odds_taken") or item.get("odds") or 1.90)

        time_utc_str = item.get("start_time_utc") or item.get("recorded_at_utc") or ""
        date_cdmx = ""
        time_cdmx = ""
        if time_utc_str:
            try:
                dt_utc = datetime.fromisoformat(time_utc_str.replace("Z", "+00:00"))
                dt_mx = dt_utc.astimezone(MEXICO_TZ)
                date_cdmx = dt_mx.strftime("%Y-%m-%d")
                time_cdmx = dt_mx.strftime("%H:%M")
            except Exception:
                pass

        if not date_cdmx:
            date_cdmx = datetime.now(MEXICO_TZ).strftime("%Y-%m-%d")

        reasoning = str(item.get("result_detail") or item.get("reasoning") or item.get("market_name") or "")

        row = {
            "id": tid,
            "categoria": league,
            "partido": str(item.get("match") or "Evento"),
            "pick": str(item.get("pick") or item.get("altenar_selection") or "Selección"),
            "cuota": odds,
            "confianza": "90%",
            "razonamiento": reasoning,
            "fecha_generacion": date_cdmx,
            "fecha_evento": date_cdmx,
            "horario": time_cdmx,
            "estado": estado,
            "es_parlay": False,
            "visibility": "premium",
        }
        rows.append(row)

        if estado == "ganado":
            won_count += 1
            units_total += (odds - 1.0)
        elif estado == "perdido":
            lost_count += 1
            units_total -= 1.0
        elif estado == "void":
            void_count += 1

    # Ordenar descendente (los más recientes arriba)
    rows.sort(key=lambda r: (r.get("fecha_evento", ""), str(r.get("id", ""))), reverse=True)

    settled_count = won_count + lost_count
    roi_pct = round((units_total / settled_count) * 100, 1) if settled_count > 0 else 0.0

    output_payload = {
        "updated_at_cdmx": datetime.now(MEXICO_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "kpis": {
            "total_settled": settled_count,
            "won": won_count,
            "lost": lost_count,
            "void": void_count,
            "win_rate_pct": round((won_count / settled_count) * 100, 1) if settled_count > 0 else 0.0,
            "net_units": round(units_total, 2),
            "roi_pct": roi_pct,
        },
        "settled_picks": rows,
    }

    out_file = REPO_ROOT / "data" / "settled_picks_history.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    public_dest = REPO_ROOT / "frontend" / "public" / "settled_picks_history.json"
    public_dest.parent.mkdir(parents=True, exist_ok=True)
    public_dest.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Exportados {len(rows)} picks ({won_count}W - {lost_count}L, {units_total:+.2f}u, {roi_pct}% ROI) a {out_file}")
    return out_file


def upload_history_to_r2(local_json_path: Path = None):
    import boto3
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(REPO_ROOT / "backend" / ".env")

    acc_id = os.getenv("R2_ACCOUNT_ID")
    ak = os.getenv("R2_ACCESS_KEY_ID")
    sk = os.getenv("R2_SECRET_ACCESS_KEY")
    bucket = os.getenv("R2_BUCKET_NAME", "rey-taco-media")
    public_domain = os.getenv("R2_PUBLIC_DOMAIN", "https://pub-1d89d25fcc84453db0d833d998d5a57c.r2.dev")

    if not acc_id or not ak or not sk:
        print("[R2] Faltan credenciales R2 en el entorno.")
        return False

    if local_json_path is None:
        local_json_path = REPO_ROOT / "data" / "settled_picks_history.json"

    if not local_json_path.exists():
        print(f"[R2] Archivo no encontrado: {local_json_path}")
        return False

    data = local_json_path.read_bytes()
    endpoint = f"https://{acc_id}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        region_name="auto",
    )

    s3.put_object(
        Bucket=bucket,
        Key="settled_picks_history.json",
        Body=data,
        ContentType="application/json",
        CacheControl="no-cache, no-store, must-revalidate",
    )
    print(f"[R2] settled_picks_history.json ({len(data)} bytes) subido exitosamente a R2!")
    print(f"[R2] URL Publica: {public_domain}/settled_picks_history.json")
    return True


if __name__ == "__main__":
    out = export_settled_history()
    if out:
        upload_history_to_r2(out)

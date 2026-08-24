"""Generate and optionally send a neutral Telegram status report."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
import time
import urllib.request

from dotenv import load_dotenv
from supabase import create_client

from backend.evidence_messaging import format_evidence_support
from backend.publishing_policy import public_payload


REPORT_LIMIT = 10
DISPLAY_LIMIT = 6
KEYBOARD = {
    "inline_keyboard": [[
        {"text": "📲 Apostar en Playdoit", "url": "https://www.playdoit.mx/es/"},
        {"text": "🌐 Entrar a reytacopicks.com", "url": "https://reytacopicks.com/"},
    ]]
}


def build_status_message(
    active_picks: Sequence[Mapping[str, object]],
    *,
    generated_at: str | None = None,
) -> str:
    """Build a report from actual rows without claiming value globally."""

    timestamp = generated_at or time.strftime("%I:%M %p CDMX")
    lines = [
        f"👑 REY TACO PICKS • REPORTE VESPERTINO ({timestamp}) 👑",
        "",
        f"📊 {len(active_picks)} registros pendientes recuperados "
        f"(consulta limitada a {REPORT_LIMIT}); se muestran hasta {DISPLAY_LIMIT}:",
        "",
    ]
    for pick in active_picks[:DISPLAY_LIMIT]:
        prefix = "🔗" if pick.get("es_parlay") is True else "🎯"
        value_signal = (
            " | 💎 Señal de valor comparada"
            if pick.get("tiene_valor") is True
            else ""
        )
        lines.append(
            f"{prefix} {pick.get('partido', 'Evento no especificado')} ➔ "
            f"{pick.get('pick', 'Pick no especificado')} @ Cuota "
            f"{pick.get('cuota', 'No especificada')} | "
            f"{format_evidence_support(pick.get('confianza'))}{value_signal}"
        )
    lines.extend([
        "",
        "🌐 Consulta el análisis completo, momios y calculadora en vivo:",
        "👉 https://reytacopicks.com",
    ])
    return "\n".join(lines)


def _active_picks(database) -> list[Mapping[str, object]]:
    response = (
        database.table("picks")
        .select("*")
        .eq("active", True)
        .eq("estado", "pendiente")
        .order("id", desc=True)
        .limit(REPORT_LIMIT)
        .execute()
    )
    return list(response.data or [])


def _public_status_rows(
    active_picks: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    rows = public_payload(active_picks)
    for row in rows:
        row.pop("razonamiento", None)
    return rows


def _send_message(token: str, chat_id: str, message: str) -> int:
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(
            {"chat_id": chat_id, "text": message, "reply_markup": KEYBOARD},
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.getcode()


def main() -> int:
    load_dotenv("backend/.env")
    url = str(os.getenv("SUPABASE_URL") or "").strip()
    service_key = str(os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    token = str(os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    destinations = [
        ("Privado", os.getenv("TELEGRAM_CHAT_ID"), "all"),
        (
            "Canal VIP",
            os.getenv("TELEGRAM_VIP_CHANNEL_ID")
            or os.getenv("TELEGRAM_CHANNEL_ID"),
            "all",
        ),
        ("Canal Free", os.getenv("TELEGRAM_FREE_CHANNEL_ID"), "public"),
    ]
    if not url or not service_key or not token:
        print("Reporte cancelado: configuración requerida incompleta.")
        return 1

    database = create_client(url, service_key)
    active_picks = _active_picks(database)
    messages = {
        "all": build_status_message(active_picks),
        "public": build_status_message(_public_status_rows(active_picks)),
    }
    for name, chat_id, audience in destinations:
        if chat_id:
            status = _send_message(token, str(chat_id), messages[audience])
            print(f" -> {name}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

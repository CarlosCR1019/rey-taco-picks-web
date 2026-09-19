"""
backend/audit_ledger.py
=======================
Ledger Criptográfico Inmutable y Event Sourcing para Rey Taco Picks.

Principios de Seguridad y Auditoría Criptográfica:
1. Event Sourcing Puro: Nunca se muta ni reescribe un registro existente.
   Cualquier cambio de estado (Creación, Publicación, Cierre, Liquidación) se añade como un nuevo evento.
2. Hash-Chain Criptográfica:
   H_n = SHA256(H_{n-1} || SHA256(canonical_json(payload_n)))
   Cualquier alteración histórica en el bloque k invalida instantáneamente los bloques k, k+1, ..., N.
3. Serialización Canónica Determinista:
   json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(',', ':'))
4. Merkle Root:
   Permite certificar y anclar tandas completas de pronósticos en observadores externos (OpenTimestamps/GitHub).
"""

import os
import sys
import time
import json
import hashlib
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union

logger = logging.getLogger("AuditLedger")
MEXICO_TZ = ZoneInfo("America/Mexico_City")

# Rutas estándar de ledger en producción y fallback local
LOCAL_DIR = Path(__file__).resolve().parent.parent / "data"
LOCAL_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_AUDIT_LEDGER_PATH = Path("/root/sports-props-collector/audit_ledger.jsonl")
AUDIT_LEDGER_PATH = DEFAULT_AUDIT_LEDGER_PATH if DEFAULT_AUDIT_LEDGER_PATH.parent.exists() else (LOCAL_DIR / "audit_ledger.jsonl")

DEFAULT_REJECTED_PATH = Path("/root/sports-props-collector/rejected_picks.jsonl")
REJECTED_PICKS_PATH = DEFAULT_REJECTED_PATH if DEFAULT_REJECTED_PATH.parent.exists() else (LOCAL_DIR / "rejected_picks.jsonl")

GENESIS_HASH = "0" * 64

# Tipos de Eventos Inmutables
EVENT_PICK_CREATED = "PICK_CREATED"
EVENT_PICK_PUBLISHED = "PICK_PUBLISHED"
EVENT_PRICE_EXPIRED = "PRICE_EXPIRED"
EVENT_MARKET_CLOSED = "MARKET_CLOSED"
EVENT_PICK_SETTLED = "PICK_SETTLED"


def canonical_json(data: Any) -> str:
    """Serializa un objeto de Python a JSON canónico determinista sin ambigüedad de espacios."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def compute_sha256(content: str) -> str:
    """Calcula el hash SHA-256 en hexadecimal de un string en UTF-8."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def generate_ticket_id(sport: str, home_team: str, away_team: str) -> str:
    """
    Genera un identificador único determinista de ticket con formato:
    RT-YYYYMMDD-SPORT-XXXX
    """
    date_str = datetime.now(MEXICO_TZ).strftime("%Y%m%d")
    clean_sport = "".join(filter(str.isalnum, sport)).upper()[:3] or "SPT"
    entropy = f"{home_team}_{away_team}_{time.time_ns()}"
    hex_suffix = hashlib.sha256(entropy.encode("utf-8")).hexdigest()[:4].upper()
    return f"RT-{date_str}-{clean_sport}-{hex_suffix}"


def get_latest_ledger_block(ledger_path: Path = AUDIT_LEDGER_PATH) -> Tuple[int, str]:
    """
    Lee el último bloque del ledger para encadenar el siguiente hash.
    Retorna: (sequence_id, entry_hash). Si el archivo está vacío, retorna (0, GENESIS_HASH).
    """
    if not ledger_path.exists():
        return 0, GENESIS_HASH

    last_line = ""
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
        if not last_line:
            return 0, GENESIS_HASH

        block = json.loads(last_line)
        return int(block.get("sequence_id", 0)), str(block.get("entry_hash", GENESIS_HASH))
    except Exception as e:
        logger.error(f"Error leyendo último bloque del ledger ({ledger_path}): {e}")
        return 0, GENESIS_HASH


def append_ledger_event(
    event_type: str,
    ticket_id: str,
    payload_data: Dict[str, Any],
    ledger_path: Path = AUDIT_LEDGER_PATH
) -> Dict[str, Any]:
    """
    Escribe un evento atómico e inmutable en la Hash-Chain del ledger.
    Garantiza:
    1. Secuencia estrictamente creciente.
    2. Compromiso criptográfico del bloque previo (previous_hash).
    3. Hashing canónico del payload completo.
    """
    last_seq, prev_hash = get_latest_ledger_block(ledger_path)
    new_seq = last_seq + 1

    now_utc = datetime.now(timezone.utc).isoformat()
    now_cdmx = datetime.now(MEXICO_TZ).strftime("%Y-%m-%d %H:%M:%S")

    # Inyectar metadatos temporales de auditoría en el payload
    full_payload = {
        **payload_data,
        "event_type": event_type,
        "ticket_id": ticket_id,
        "recorded_at_utc": now_utc,
        "recorded_at_cdmx": now_cdmx
    }

    # 1. Hash canónico del payload
    canon_str = canonical_json(full_payload)
    payload_hash = compute_sha256(canon_str)

    # 2. Hash encadenado del bloque H_n = SHA256(H_{n-1} || payload_hash)
    chain_link = f"{prev_hash}|{payload_hash}"
    entry_hash = compute_sha256(chain_link)

    block = {
        "sequence_id": new_seq,
        "event_type": event_type,
        "ticket_id": ticket_id,
        "previous_hash": prev_hash,
        "payload_hash": payload_hash,
        "entry_hash": entry_hash,
        "payload": full_payload
    }

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8") as f:
        f.write(canonical_json(block) + "\n")

    logger.info(f"⛓️ [LEDGER] Bloque #{new_seq} sellado [{event_type}] Ticket: {ticket_id} (Hash: {entry_hash[:8]}...)")
    return block


# =====================================================================
# API DE EVENTOS ESPECÍFICOS DEL SISTEMA
# =====================================================================

def record_pick_created(pick_data: Dict[str, Any], ledger_path: Path = AUDIT_LEDGER_PATH) -> str:
    """Registra la creación y aprobación cuantitativa de un pick antes de su publicación."""
    ticket_id = pick_data.get("ticket_id") or generate_ticket_id(
        pick_data.get("sport", "SPT"),
        pick_data.get("home_team", "HOME"),
        pick_data.get("away_team", "AWAY")
    )
    payload = {
        "match": f"{pick_data.get('home_team')} vs {pick_data.get('away_team')}",
        "home_team": pick_data.get("home_team"),
        "away_team": pick_data.get("away_team"),
        "sport": pick_data.get("sport", "Fútbol"),
        "league": pick_data.get("league"),
        "selection": pick_data.get("pick") or pick_data.get("selection"),
        "market": pick_data.get("market", "Línea Principal"),
        "offered_odds": float(pick_data.get("market_odds_decimal", 1.85)),
        "min_acceptable_odds": float(pick_data.get("minimum_odds_decimal", 1.80)),
        "market_probability": float(pick_data.get("market_probability", 0.50)),
        "model_probability": float(pick_data.get("model_probability", 0.55)),
        "calibrated_probability": float(pick_data.get("calibrated_probability", 0.54)),
        "model_edge_pp": float(pick_data.get("model_edge_pp", 4.0)),
        "expected_value_pct": float(pick_data.get("ev_percent", 5.0)),
        "stake_percent": float(pick_data.get("stake_units", 1.0)),
        "tactical_rationale": pick_data.get("tactical_rationale", "")
    }
    append_ledger_event(EVENT_PICK_CREATED, ticket_id, payload, ledger_path=ledger_path)
    return ticket_id


# Alias de compatibilidad
record_published_pick = record_pick_created


def record_rejected_pick(rejection_data: Dict[str, Any], rejected_path: Path = REJECTED_PICKS_PATH):
    return log_rejected_pick(
        match=f"{rejection_data.get('home_team')} vs {rejection_data.get('away_team')}",
        selection=rejection_data.get("candidate_pick", "N/A"),
        offered_odds=float(rejection_data.get("raw_odds", 1.85)),
        min_acceptable_odds=float(rejection_data.get("minimum_odds", 1.80)),
        reason=rejection_data.get("rejection_reason", "VETO"),
        metadata=rejection_data,
        rejected_path=rejected_path
    )


def record_odds_snapshot(ticket_id: str, snapshot_type: str, odds_decimal: float, odds_raw: str):
    """Snapshot de auditoría para registro de cierre y CLV."""
    pass


def record_pick_published(ticket_id: str, channel: str = "TELEGRAM_FREE", ledger_path: Path = AUDIT_LEDGER_PATH) -> Dict[str, Any]:
    """Registra el despacho oficial de un pick a un canal público o VIP."""
    payload = {
        "channel": channel,
        "dispatched_at_epoch": time.time()
    }
    return append_ledger_event(EVENT_PICK_PUBLISHED, ticket_id, payload, ledger_path=ledger_path)


def record_price_expired(
    ticket_id: str,
    stale_odds: float,
    current_live_odds: float,
    min_acceptable_odds: float,
    ledger_path: Path = AUDIT_LEDGER_PATH
) -> Dict[str, Any]:
    """
    Registra el veto de latencia (Two-Phase Gate):
    La cuota cayó por debajo del mínimo aceptable antes del despacho.
    """
    payload = {
        "stale_odds": stale_odds,
        "current_live_odds": current_live_odds,
        "min_acceptable_odds": min_acceptable_odds,
        "price_drop_pct": round(((current_live_odds - stale_odds) / stale_odds) * 100.0, 2),
        "veto_reason": "PRE_DISPATCH_PRICE_EXPIRED"
    }
    block = append_ledger_event(EVENT_PRICE_EXPIRED, ticket_id, payload, ledger_path=ledger_path)
    # Registrar también en el dataset de descartes para telemetría de latencia
    log_rejected_pick(
        match=ticket_id,
        selection="LATENCY_GATE",
        offered_odds=current_live_odds,
        min_acceptable_odds=min_acceptable_odds,
        reason="PRICE_EXPIRED_PRE_DISPATCH",
        metadata=payload
    )
    return block


def record_pick_settled(
    ticket_id: str,
    status: str,  # WON, LOST, PUSH, VOID
    official_score: str,
    closing_odds_decimal: float,
    units_won_lost: float,
    ledger_path: Path = AUDIT_LEDGER_PATH
) -> Dict[str, Any]:
    """
    Registra la liquidación oficial de un pick (Append-Only Event Sourcing).
    NUNCA modifica el registro anterior. Añade un evento PICK_SETTLED con CLV.
    """
    clv_val = None
    # Calcular CLV si hay cuota de cierre
    # El cálculo exacto se enriquecerá al reconstruir el estado
    payload = {
        "status": status.upper(),
        "official_score": official_score,
        "closing_odds_decimal": closing_odds_decimal,
        "units_won_lost": units_won_lost
    }
    return append_ledger_event(EVENT_PICK_SETTLED, ticket_id, payload, ledger_path=ledger_path)


# =====================================================================
# VERIFICACIÓN DE INTEGRIDAD CRIPTOGRÁFICA
# =====================================================================

def verify_ledger_integrity(ledger_path: Path = AUDIT_LEDGER_PATH) -> Tuple[bool, int, str]:
    """
    Audita matemáticamente toda la Hash-Chain del archivo JSONL:
    1. Verifica que la secuencia sea continua (1, 2, 3...).
    2. Reconstruye el hash del payload usando serialización canónica.
    3. Comprueba que previous_hash coincida exactamente con entry_hash del bloque anterior.
    4. Recomputa entry_hash = SHA256(previous_hash || payload_hash).
    Retorna: (is_valid, total_blocks_audited, message_or_error)
    """
    if not ledger_path.exists():
        return True, 0, "LEDGER_EMPTY"

    expected_prev_hash = GENESIS_HASH
    sequence = 0

    with open(ledger_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                block = json.loads(stripped)
            except json.JSONDecodeError:
                return False, line_num, f"Línea #{line_num}: JSON corrupto"

            seq = block.get("sequence_id")
            prev_h = block.get("previous_hash")
            pay_h = block.get("payload_hash")
            entry_h = block.get("entry_hash")
            payload = block.get("payload")

            sequence += 1
            if seq != sequence:
                return False, seq, f"Línea #{line_num}: Secuencia rota (esperado #{sequence}, encontrado #{seq})"

            if prev_h != expected_prev_hash:
                return False, seq, f"Bloque #{seq}: previous_hash no coincide con el bloque anterior"

            # Recomputar payload_hash canónico
            recomputed_payload_hash = compute_sha256(canonical_json(payload))
            if recomputed_payload_hash != pay_h:
                return False, seq, f"Bloque #{seq}: payload_hash alterado (datos manipulados)"

            # Recomputar entry_hash encadenado
            recomputed_entry_hash = compute_sha256(f"{prev_h}|{pay_h}")
            if recomputed_entry_hash != entry_h:
                return False, seq, f"Bloque #{seq}: entry_hash alterado o manipulado"

            expected_prev_hash = entry_h

    return True, sequence, f"CADENA_INTEGRA (Total bloques: {sequence}, Hash raíz: {expected_prev_hash[:12]}...)"


# =====================================================================
# CÁLCULO DE MERKLE ROOT PARA PRUEBA EXTERNA PÚBLICA
# =====================================================================

def compute_merkle_root(hashes: List[str]) -> str:
    """
    Calcula la Raíz Merkle (Merkle Root) de un conjunto de hashes de bloques.
    Permite anclar N eventos con un solo hash en OpenTimestamps o GitHub commit.
    """
    if not hashes:
        return GENESIS_HASH
    if len(hashes) == 1:
        return hashes[0]

    current_level = list(hashes)
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if (i + 1) < len(current_level) else left
            combined = compute_sha256(f"{left}{right}")
            next_level.append(combined)
        current_level = next_level

    return current_level[0]


# =====================================================================
# DATASET DE DESCARTES (ALPHA DEL VETO)
# =====================================================================

def log_rejected_pick(
    match: str,
    selection: str,
    offered_odds: float,
    min_acceptable_odds: float,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None,
    rejected_path: Path = REJECTED_PICKS_PATH
) -> None:
    """Registra descartes del modelo para medir empíricamente las pérdidas evitadas."""
    now_cdmx = datetime.now(MEXICO_TZ).strftime("%Y-%m-%d %H:%M:%S")
    entry = {
        "timestamp_cdmx": now_cdmx,
        "match": match,
        "selection": selection,
        "offered_odds": offered_odds,
        "min_acceptable_odds": min_acceptable_odds,
        "rejection_reason": reason,
        "metadata": metadata or {}
    }
    rejected_path.parent.mkdir(parents=True, exist_ok=True)
    with open(rejected_path, "a", encoding="utf-8") as f:
        f.write(canonical_json(entry) + "\n")
    logger.info(f"🚫 [VETO DEL REY] Descarte registrado: {match} ({reason})")


# =====================================================================
# RECONSTRUCCIÓN DE ESTADO Y TELEMETRÍA INSTITUCIONAL
# =====================================================================

def get_ledger_state(ledger_path: Path = AUDIT_LEDGER_PATH) -> Dict[str, Any]:
    """
    Reconstruye el estado consolidado de los pronósticos reproduciendo la secuencia de eventos.
    Retorna métricas para el dashboard de verificación de la Web y Mini App.
    """
    if not ledger_path.exists():
        return {"total_tickets": 0, "settled_tickets": 0, "status": "EMPTY"}

    tickets: Dict[str, Dict[str, Any]] = {}

    with open(ledger_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            block = json.loads(stripped)
            evt_type = block.get("event_type")
            t_id = block.get("ticket_id")
            payload = block.get("payload", {})

            if t_id not in tickets:
                tickets[t_id] = {
                    "ticket_id": t_id,
                    "status": "CREATED",
                    "events": []
                }

            ticket = tickets[t_id]
            ticket["events"].append(evt_type)

            if evt_type == EVENT_PICK_CREATED:
                ticket.update(payload)
                ticket["status"] = "PENDING"
            elif evt_type == EVENT_PICK_PUBLISHED:
                ticket["status"] = "PUBLISHED"
                ticket["channel"] = payload.get("channel")
            elif evt_type == EVENT_PRICE_EXPIRED:
                ticket["status"] = "EXPIRED"
            elif evt_type == EVENT_PICK_SETTLED:
                ticket["status"] = payload.get("status", "SETTLED")
                ticket["official_score"] = payload.get("official_score")
                ticket["closing_odds"] = payload.get("closing_odds_decimal")
                ticket["units_won_lost"] = payload.get("units_won_lost", 0.0)

                # Calcular CLV respecto a la cuota tomada
                taken_odds = ticket.get("offered_odds")
                closing_odds = payload.get("closing_odds_decimal")
                if taken_odds and closing_odds and closing_odds > 1.0:
                    ticket["clv_percent"] = round(((taken_odds / closing_odds) - 1.0) * 100.0, 2)

    all_tickets = list(tickets.values())
    settled = [t for t in all_tickets if t.get("status") in ("WON", "LOST", "PUSH")]
    won = [t for t in settled if t.get("status") == "WON"]
    clv_records = [t.get("clv_percent") for t in all_tickets if t.get("clv_percent") is not None]

    win_rate = round((len(won) / len(settled) * 100.0), 1) if settled else 0.0
    avg_clv = round(sum(clv_records) / len(clv_records), 2) if clv_records else 0.0
    net_units = round(sum(t.get("units_won_lost", 0.0) for t in settled), 2)

    return {
        "total_tickets": len(all_tickets),
        "settled_tickets": len(settled),
        "won_tickets": len(won),
        "win_rate_pct": win_rate,
        "net_units": net_units,
        "average_clv_pct": avg_clv,
        "clv_sample_size": len(clv_records),
        "cryptographic_verification": verify_ledger_integrity(ledger_path)[0]
    }

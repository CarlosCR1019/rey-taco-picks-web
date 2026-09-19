"""
scripts/migrate_vps_ledger.py
Migra registros legacy de audit_ledger.jsonl a la nueva estructura Hash-Chained.
"""
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.audit_ledger import canonical_json, compute_sha256, GENESIS_HASH

def migrate(file_path: Path):
    if not file_path.exists():
        print("No existe el archivo.")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    new_blocks = []
    prev_hash = GENESIS_HASH

    for idx, raw in enumerate(lines, start=1):
        item = json.loads(raw)
        # Si ya es un bloque nuevo
        if "sequence_id" in item and "entry_hash" in item:
            new_blocks.append(item)
            prev_hash = item["entry_hash"]
            continue

        # Migrar registro antiguo
        payload = {
            **item,
            "event_type": "PICK_CREATED",
            "recorded_at_utc": item.get("published_at_utc"),
            "recorded_at_cdmx": item.get("published_at_cdmx")
        }
        pay_hash = compute_sha256(canonical_json(payload))
        entry_hash = compute_sha256(f"{prev_hash}|{pay_hash}")
        block = {
            "sequence_id": idx,
            "event_type": "PICK_CREATED",
            "ticket_id": item.get("ticket_id", f"RT-LEGACY-{idx}"),
            "previous_hash": prev_hash,
            "payload_hash": pay_hash,
            "entry_hash": entry_hash,
            "payload": payload
        }
        new_blocks.append(block)
        prev_hash = entry_hash

    with open(file_path, "w", encoding="utf-8") as f:
        for b in new_blocks:
            f.write(canonical_json(b) + "\n")

    print(f"✅ Migración completada: {len(new_blocks)} bloques encadenados.")

if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/root/sports-props-collector/audit_ledger.jsonl")
    migrate(target)

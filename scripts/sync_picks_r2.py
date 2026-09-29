import os
import sys
import json
import boto3
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv(REPO_ROOT / "backend" / ".env")

def upload_active_picks_to_r2(local_json_path: Path = None):
    acc_id = os.getenv("R2_ACCOUNT_ID")
    ak = os.getenv("R2_ACCESS_KEY_ID")
    sk = os.getenv("R2_SECRET_ACCESS_KEY")
    bucket = os.getenv("R2_BUCKET_NAME", "rey-taco-media")
    public_domain = os.getenv("R2_PUBLIC_DOMAIN", "https://pub-1d89d25fcc84453db0d833d998d5a57c.r2.dev")

    if not acc_id or not ak or not sk:
        print("[R2] Faltan credenciales R2 en el entorno.")
        return False

    if local_json_path is None:
        candidates = [
            REPO_ROOT / "frontend" / "public" / "active_private_picks.json",
            REPO_ROOT / "data" / "active_private_picks.json"
        ]
        for c in candidates:
            if c.exists():
                local_json_path = c
                break

    if not local_json_path or not local_json_path.exists():
        print(f"[R2] Archivo no encontrado: {local_json_path}")
        return False

    data = local_json_path.read_bytes()
    endpoint = f"https://{acc_id}.r2.cloudflarestorage.com"
    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        region_name="auto"
    )

    s3.put_object(
        Bucket=bucket,
        Key="active_private_picks.json",
        Body=data,
        ContentType="application/json",
        CacheControl="no-cache, no-store, must-revalidate"
    )
    print(f"[R2] active_private_picks.json ({len(data)} bytes) subido exitosamente a R2!")
    print(f"[R2] URL Publica: {public_domain}/active_private_picks.json")
    return True

if __name__ == "__main__":
    upload_active_picks_to_r2()


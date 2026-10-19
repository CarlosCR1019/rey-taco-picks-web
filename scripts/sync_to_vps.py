import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

import os

ssh_key = os.environ.get("SSH_KEY", r"C:\Users\carlo\.ssh\reytaco_vps_key")
# Contabo vmi3630799 (Producción Activa) / Hetzner (Respaldo en espera)
CONTABO_HOST = "root@158.220.119.201"
HETZNER_HOST = "root@204.168.247.173"
vps = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("TARGET_VPS", CONTABO_HOST)
print(f"Target VPS: {vps}")

files_to_sync = [
    ("backend/multisport_cadence_engine.py", "/root/sports-props-collector/backend/multisport_cadence_engine.py"),
    ("backend/ladder_challenge_engine.py", "/root/sports-props-collector/backend/ladder_challenge_engine.py"),
    ("backend/playdoit_deep_markets.py", "/root/sports-props-collector/backend/playdoit_deep_markets.py"),
    ("backend/auto_reel_producer.py", "/root/sports-props-collector/backend/auto_reel_producer.py"),
    ("backend/tiktok_auto_uploader.py", "/root/sports-props-collector/backend/tiktok_auto_uploader.py"),
    ("backend/pick_settlement.py", "/root/sports-props-collector/backend/pick_settlement.py"),
    ("backend/reel_cadence_bridge.py", "/root/sports-props-collector/backend/reel_cadence_bridge.py"),
    ("scripts/run_multisport_daemon_vps.py", "/root/sports-props-collector/scripts/run_multisport_daemon_vps.py"),
    ("scripts/publish_fabrica_meta.py", "/root/sports-props-collector/scripts/publish_fabrica_meta.py"),
    ("scripts/generate_fabrica_media.py", "/root/sports-props-collector/scripts/generate_fabrica_media.py"),
    ("lab/reels/template_ai_auto_reel.html", "/root/sports-props-collector/lab/reels/template_ai_auto_reel.html"),
]


for local_f, remote_f in files_to_sync:
    print(f"Syncing {local_f} -> {remote_f}...")
    cmd = ["scp", "-i", ssh_key, "-o", "StrictHostKeyChecking=no", local_f, f"{vps}:{remote_f}"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if res.returncode == 0:
        print(f"  ✅ {local_f} synced successfully.")
    else:
        print(f"  ❌ Error syncing {local_f}: {res.stderr}")

# Restart daemon on VPS
print("Restarting reytaco-multisport-daemon on VPS...")
cmd_restart = ["ssh", "-i", ssh_key, "-o", "StrictHostKeyChecking=no", vps, "systemctl restart reytaco-multisport-daemon && systemctl status reytaco-multisport-daemon --no-pager"]
res_restart = subprocess.run(cmd_restart, capture_output=True, text=True, encoding='utf-8')
print("Daemon Status Output:\n", res_restart.stdout)
if res_restart.stderr:
    print("Daemon Status Error:\n", res_restart.stderr)

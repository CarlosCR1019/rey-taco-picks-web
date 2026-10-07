import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh_key = r"C:\Users\carlo\.ssh\reytaco_vps_key"
vps = "root@204.168.247.173"

files_to_sync = [
    ("backend/multisport_cadence_engine.py", "/root/sports-props-collector/backend/multisport_cadence_engine.py"),
    ("backend/pick_settlement.py", "/root/sports-props-collector/backend/pick_settlement.py"),
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

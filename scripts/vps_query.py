import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8')

ssh_cmd = [
    'ssh',
    '-i', r'C:\Users\carlo\.ssh\reytaco_vps_key',
    '-o', 'StrictHostKeyChecking=no',
    'root@204.168.247.173',
    'cd /root/sports-props-collector && python3 -c \'from backend.pick_settlement import settle_pending, build_report, report_text; n = settle_pending(min_hours_after_start=2.0); print(f"Settled: {n}"); print(report_text(build_report()))\''
]

res = subprocess.run(ssh_cmd, capture_output=True, text=True, encoding='utf-8')
print("STDOUT:\n", res.stdout)
if res.stderr:
    print("STDERR:\n", res.stderr)

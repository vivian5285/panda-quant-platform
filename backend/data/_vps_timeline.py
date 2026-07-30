"""Get full trading event timeline from VPS."""
import subprocess

script = r"""
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('187.77.130.144', username='root', password="w'tFzgg2vPZ0D,Z;", timeout=30)

def run(cmd, timeout=60):
    i,o,e = client.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8', errors='replace'), e.read().decode('utf-8', errors='replace')

PROJ = '/home/panda/panda-quant-platform'

# Get all logs today
print('=== TODAY LOGS ===')
o,e = run(f'cd {PROJ} && docker compose logs --since "2026-07-28T00:00:00" backend 2>&1')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
# Print lines with actual trading events
lines = safe.split('\n')
for line in lines[-200:]:
    if any(kw in line for kw in ['UserEvent', 'OPEN', 'CLOSE', 'BREATH', 'TP', 'RADAR', 'FILLED', 'DingTalk', 'VPS', 'STARTUP', 'position', 'signal', 'recovering']):
        print(line[:200])
    elif 'ERROR' in line or 'ERROR' in line:
        print('ERROR:', line[:200])

# VPS time
print('\n=== VPS TIME ===')
o,e = run('date')
print(o.strip())

# Health
print('\n=== HEALTH ===')
o,e = run('curl -s http://localhost:8000/api/health')
print(o.strip())

client.close()
print('\nDONE')
"""

with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_timeline.py", "w", encoding="utf-8") as f:
    f.write(script)

result = subprocess.run(
    ["py", r"C:\Users\Administrator\AppData\Local\Temp\_vps_timeline.py"],
    capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace'
)
try:
    with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_timeline_out.txt", "w", encoding="utf-8") as f:
        f.write(result.stdout)
except:
    pass
print(result.stdout[:8000] if result.stdout else 'no output')
print('RC:', result.returncode)

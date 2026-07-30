"""Check XAU live trading state on VPS."""
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

# Health
o,e = run('curl -s http://localhost:8000/api/health')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print('HEALTH:', safe.strip())

# VPS time
o,e = run('date')
print('TIME:', o.strip())

# All events since 15:40
o,e = run(f'cd {PROJ} && docker compose logs --since "2026-07-28T15:40:00" backend 2>&1')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
lines = safe.split('\n')
events = [l for l in lines if any(kw in l for kw in ['UserEvent', 'ERROR', 'WARNING', 'OPEN', 'CLOSE', 'TP', 'FILLED', 'RADAR', 'DingTalk', 'signal', 'watched', 'XAU', 'startup', 'dispatch', 'webhook'])]
print('\nEVENTS:')
for e in events:
    print(e[:200])

client.close()
"""

with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_xau.py", "w", encoding="utf-8") as f:
    f.write(script)

result = subprocess.run(
    ["py", r"C:\Users\Administrator\AppData\Local\Temp\_vps_xau.py"],
    capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace'
)
print(result.stdout[:6000] if result.stdout else 'no output')
print('RC:', result.returncode)

"""Extract key trading events from VPS logs."""
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

# All logs since 15:20 today
print('=== ALL EVENTS SINCE 15:20 ===')
o,e = run(f'cd {PROJ} && docker compose logs --since "2026-07-28T15:20:00" backend 2>&1')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print(safe[-8000:] if safe else 'empty')

# Check if there are any new TV signals
print('\n=== NEW SIGNALS ===')
o,e = run(f'cd {PROJ} && docker compose logs --since "2026-07-28T15:25:00" backend 2>&1 | grep -aE "TV|SIGNAL|OPEN|signal|webhook" | tail -c 3000')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print(safe[-2000:] if safe else 'none')

# Check for any dispatch events
print('\n=== DISPATCH EVENTS ===')
o,e = run(f'cd {PROJ} && docker compose logs --since "2026-07-28T15:25:00" backend 2>&1 | grep -aE "dispatch|recovering|block|SYNC" | tail -c 2000')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print(safe[-1500:] if safe else 'none')

# Check current time on VPS
print('\n=== VPS TIME ===')
o,e = run('date')
print(o.strip())

client.close()
print('DONE')
"""

with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_events.py", "w", encoding="utf-8") as f:
    f.write(script)

result = subprocess.run(
    ["py", r"C:\Users\Administrator\AppData\Local\Temp\_vps_events.py"],
    capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace'
)
try:
    with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_events_out.txt", "w", encoding="utf-8") as f:
        f.write(result.stdout)
except:
    pass
print(result.stdout[:8000] if result.stdout else 'no output')
print('RC:', result.returncode)

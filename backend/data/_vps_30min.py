"""Check very recent VPS events - last 30 min."""
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('187.77.130.144', username='root', password="w'tFzgg2vPZ0D,Z;", timeout=30)

def run(cmd, timeout=120):
    i,o,e = client.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8', errors='replace'), e.read().decode('utf-8', errors='replace')

PROJ = '/home/panda/panda-quant-platform'

# VPS time
o,e = run('date')
print('VPS TIME:', o.strip())

# Last 30 min - ALL logs
o,e = run(f'cd {PROJ} && docker compose logs --since "30 minutes ago" backend 2>&1')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print('\n--- LAST 30 MIN (all non-health) ---')
lines = safe.split('\n')
for l in lines:
    if '[INFO]' in l or '[WARNING]' in l or '[ERROR]' in l:
        if 'GET /api/health' not in l:
            print(l[:180])

client.close()

"""Check VPS logs directly."""
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

# Try without grep first
print('=== LAST 200 LOGS ===')
o,e = run(f'cd {PROJ} && docker compose logs --tail 200 backend 2>&1')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print(safe[-5000:] if safe else 'empty')

# Check signal log
print('\n=== SIGNAL LOG ===')
o,e = run(f'cd {PROJ} && docker compose logs --since 10m --tail 100 backend 2>&1')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print(safe[-3000:] if safe else 'empty')

# Check supervisor state file
print('\n=== STATE FILES ===')
o,e = run(f'find {PROJ}/backend/state -name "*.json" 2>/dev/null | head -10')
print(o.strip())

# Check users with positions via API
print('\n=== POSITIONS API ===')
o,e = run('curl -s http://localhost:8000/api/supervisors')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print(safe[-3000:] if safe else 'empty')

client.close()
print('DONE')
"""

with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_live4.py", "w", encoding="utf-8") as f:
    f.write(script)

result = subprocess.run(
    ["py", r"C:\Users\Administrator\AppData\Local\Temp\_vps_live4.py"],
    capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace'
)
try:
    with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_live4_out.txt", "w", encoding="utf-8") as f:
        f.write(result.stdout)
except:
    pass
print(result.stdout[:8000] if result.stdout else 'no output')
print('RC:', result.returncode)

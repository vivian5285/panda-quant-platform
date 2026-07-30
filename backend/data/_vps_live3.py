"""Check VPS live state - ASCII safe."""
import subprocess

script = r"""
import paramiko

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('187.77.130.144', username='root', password="w'tFzgg2vPZ0D,Z;", timeout=30)

def run(cmd, timeout=60):
    i,o,e = client.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8',errors='replace'), e.read().decode('utf-8',errors='replace')

PROJ = '/home/panda/panda-quant-platform'

# Health
print('HEALTH:')
o,e = run('curl -s http://localhost:8000/api/health')
print(o.strip())

# Logs - grep for trading events
print('\nLOGS (events):')
o,e = run(f'cd {PROJ} && docker compose logs backend --tail 120 2>&1 | grep -aE "OPEN|CLOSE|TP[0-9]|RADAR|FILLED|SIGNAL|watched|position|ADVERSE|sync|ARM" | tail -a -c 5000')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print(safe[-4000:] if safe else 'none')

# Raw last 60 lines
print('\nRAW LOGS:')
o,e = run(f'cd {PROJ} && docker compose logs backend --tail 60 2>&1 | tail -a -c 5000')
safe = ''.join(c for c in o if ord(c) < 128 or c == '\n')
print(safe[-4000:] if safe else 'none')

client.close()
print('DONE')
"""

with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_live3.py", "w", encoding="utf-8") as f:
    f.write(script)

result = subprocess.run(
    ["py", r"C:\Users\Administrator\AppData\Local\Temp\_vps_live3.py"],
    capture_output=True, text=True, timeout=120, encoding='utf-8', errors='replace'
)
# Write output to file to avoid encoding issues
out = result.stdout
err = result.stderr
try:
    with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_live3_out.txt", "w", encoding="utf-8") as f:
        f.write(out)
except:
    pass
print(out[:6000] if out else 'no output')
print('RC:', result.returncode)

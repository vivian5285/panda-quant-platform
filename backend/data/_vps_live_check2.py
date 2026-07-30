"""Check live trading state on VPS - unicode safe."""
import subprocess
import sys

script = r"""
import paramiko, time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('187.77.130.144', username='root', password="w'tFzgg2vPZ0D,Z;", timeout=30)

def run(cmd, timeout=60):
    i,o,e = client.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8',errors='replace'), e.read().decode('utf-8',errors='replace')

PROJ = '/home/panda/panda-quant-platform'

# 1. Health
print('\n=== HEALTH ===')
o,e = run('curl -s http://localhost:8000/api/health')
print(o.strip())

# 2. Recent logs - focus on OPEN/CLOSE/TP/RADAR/FILLED
print('\n=== RECENT LOGS (OPEN/CLOSE/TP/RADAR/FILLED) ===')
o,e = run(f'cd {PROJ} && docker compose logs backend --tail 150 2>&1 | grep -E "OPEN|CLOSE|TP|RADAR|FILLED|SIGNAL|SYNC|FILLED|position|watched" | tail -c 5000')
print(o.strip()[-4000:] if o.strip() else 'none')

# 3. Logs - all
print('\n=== RECENT LOGS (last 50 lines raw) ===')
o,e = run(f'cd {PROJ} && docker compose logs backend --tail 50 2>&1 | tail -c 5000')
print(o.strip()[-4000:] if o.strip() else 'none')

# 4. Check supervisor state
print('\n=== SUPERVISOR STATE ===')
o,e = run(f'cd {PROJ} && docker compose exec -T backend python3 -c "import sys; sys.stdout.reconfigure(encoding=\'utf-8\',errors=\'replace\'); exec(open(\'/dev/stdin\').read())" 2>&1 << \'EOF\'\nfrom app.database import SessionLocal\nfrom app.models import User\nfrom app.core.exchange_factory import create_exchange_client\ndb = SessionLocal()\nfor u in db.query(User).filter(User.is_active==True).all():\n    print(f"uid={u.uid} exchange={u.exchange} symbol={u.trading_symbol} trading={u.enable_trading}")\ndb.close()\nEOF')
print(o.strip()[-2000:] if o.strip() else 'none')

client.close()
print('\nDONE')
"""

with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_live_check2.py", "w", encoding="utf-8") as f:
    f.write(script)

result = subprocess.run(
    ["py", r"C:\Users\Administrator\AppData\Local\Temp\_vps_live_check2.py"],
    capture_output=True, text=True, timeout=300, encoding='utf-8', errors='replace'
)
print(result.stdout[:8000] if result.stdout else 'no output')
if result.stderr: print('ERR:', result.stderr[:500])
print('RC:', result.returncode)

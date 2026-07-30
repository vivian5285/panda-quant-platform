"""Check live trading state on VPS."""
import subprocess

script = r"""
import paramiko, time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('187.77.130.144', username='root', password="w'tFzgg2vPZ0D,Z;", timeout=30)
print("Connected")

def run(cmd, timeout=60):
    i,o,e = client.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8',errors='replace'), e.read().decode('utf-8',errors='replace')

PROJ = '/home/panda/panda-quant-platform'

# 1. Health
print('\n=== HEALTH ===')
o,e = run('curl -s http://localhost:8000/api/health')
print(o.strip())

# 2. Recent trading logs - all relevant events
print('\n=== RECENT LOGS (last 100 lines) ===')
o,e = run(f'cd {PROJ} && docker compose logs backend --tail 100 2>&1 | tail -c 8000')
print(o[-6000:])

# 3. Open orders
print('\n=== OPEN ORDERS ===')
o,e = run(f'cd {PROJ} && docker compose exec -T backend python -c "from app.core.binance_client import BinanceClient; from app.models import User; from app.core.exchange_factory import create_exchange_client; from app.database import SessionLocal; db=SessionLocal(); users=db.query(User).filter(User.is_active==True).all(); [print(u.uid, u.exchange, u.trading_symbol) for u in users]; db.close()"')
print(o.strip())

# 4. Position check
print('\n=== POSITIONS ===')
o,e = run(f'cd {PROJ} && docker compose exec -T backend python -c "from app.database import SessionLocal; from app.core.exchange_factory import create_exchange_client; from app.models import User; db=SessionLocal(); users=db.query(User).filter(User.is_active==True).all(); [print(f\\\"uid={{u.uid}} exchange={{u.exchange}} sym={{u.trading_symbol}}\\\") for u in users]; db.close()"')
print(o.strip())

client.close()
print('\n=== DONE ===')
"""

with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_live_check.py", "w", encoding="utf-8") as f:
    f.write(script)

result = subprocess.run(
    ["py", r"C:\Users\Administrator\AppData\Local\Temp\_vps_live_check.py"],
    capture_output=True, text=True, timeout=300
)
print(result.stdout)
if result.stderr: print('ERR:', result.stderr[:300])
print('RC:', result.returncode)

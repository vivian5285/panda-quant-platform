"""Full system verification: sync + production status + radar qty sync."""
import subprocess

script = r"""
import paramiko, time

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('187.77.130.144', username='root', password="w'tFzgg2vPZ0D,Z;", timeout=30)
print("Connected")

def run(cmd, timeout=60):
    i,o,e = client.exec_command(cmd, timeout=timeout)
    return o.read().decode('utf-8', errors='replace'), e.read().decode('utf-8', errors='replace')

PROJ = '/home/panda/panda-quant-platform'

# 1. Git sync status
print('\n=== Git Sync Check ===')
o,e = run(f'cd {PROJ} && git log --oneline -3')
print('VPS:', o.strip())
o,e = run(f'cd {PROJ} && git fetch origin && git status --short')
print('VPS status:', o.strip())

# 2. Radar qty sync code presence
print('\n=== Radar Qty Sync Code ===')
o,e = run(f'cd {PROJ} && grep -n "_sync_consumed_tp_levels\\|_sync_tv_hard_stop\\|_sync_binance_merged_stop" backend/app/core/adverse_radar_guard.py | head -20')
print('adverse_radar_guard qty sync:', o.strip())
o,e = run(f'cd {PROJ} && grep -n "sync_consumed_tp_levels" backend/app/core/binance_smart_defense.py | head -15')
print('binance_smart_defense qty sync:', o.strip())
o,e = run(f'cd {PROJ} && grep -n "def _sync_tv_hard_stop" backend/app/core/position_supervisor.py | head -5')
print('position_supervisor _sync_tv_hard_stop:', o.strip())

# 3. TP1/TP2 partial fill → qty sync flow
print('\n=== TP Partial Fill Flow ===')
o,e = run(f'cd {PROJ} && grep -n "on_fill\\|PARTIAL\\|PARTIALLY_FILLED\\|partial_fill" backend/app/core/binance_smart_defense.py | head -20')
print('partial fill handling:', o.strip())
o,e = run(f'cd {PROJ} && grep -n "on_fill\\|PARTIAL\\|PARTIALLY_FILLED\\|partial_fill" backend/app/core/adverse_radar_guard.py | head -20')
print('adverse partial fill:', o.strip())

# 4. Spec compliance checks
print('\n=== Spec Compliance Checks ===')
o,e = run(f'cd {PROJ} && grep -n "TEMP_TV_STOP_BUFFER\\|HARD_STOP_BUFFER_FIXED\\|= 1\\.15" backend/app/core/breathing_stop.py | head -5')
print('breath pad 1.15:', o.strip())
o,e = run(f'cd {PROJ} && grep -n "tp3_limit_active\\|= False" backend/app/core/position_supervisor.py | head -10')
print('tp3_limit_active:', o.strip())
o,e = run(f'cd {PROJ} && grep -n "MAX_REENTRY\\|= 1" backend/app/core/trend_tier_params.py | head -3')
print('MAX_REENTRY:', o.strip())
o,e = run(f'cd {PROJ} && grep -n "recovering\\|recovering" backend/app/services/dispatcher.py | head -10')
print('recovering flag:', o.strip())

# 5. Exchanges
print('\n=== Exchanges ===')
o,e = run(f'cd {PROJ} && grep -rn "binance\\|okx\\|gate\\|deepcoin" backend/app/core/exchange_factory.py | head -20')
print('exchange factory:', o.strip())
o,e = run(f'cd {PROJ} && ls backend/app/core/ | grep _client')
print('exchange clients:', o.strip())

# 6. Health + positions
print('\n=== Health ===')
o,e = run('curl -s http://localhost:8000/api/health')
print('HEALTH:', o.strip())

# 7. Recent trading logs
print('\n=== Recent Trading Logs ===')
o,e = run(f'cd {PROJ} && docker compose logs backend --tail 80 2>&1 | grep -E "OPEN\\|CLOSE\\|TP\\|RADAR\\|SYNC\\|FILLED\\|partial" | tail -c 3000')
print('Trading logs:', o[-2500:])

client.close()
print('\n=== DONE ===')
"""

with open(r"C:\Users\Administrator\AppData\Local\Temp\_vps_full_check.py", "w", encoding="utf-8") as f:
    f.write(script)

result = subprocess.run(
    ["py", r"C:\Users\Administrator\AppData\Local\Temp\_vps_full_check.py"],
    capture_output=True, text=True, timeout=300
)
print(result.stdout)
if result.stderr: print('ERR:', result.stderr[:300])
print('RC:', result.returncode)

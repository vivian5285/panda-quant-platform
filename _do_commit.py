import subprocess, os, sys
os.chdir(r'c:\Users\Administrator\Desktop\panda-quant-platform')

files = [
    'backend/app/core/adverse_radar_guard.py',
    'backend/app/core/binance_smart_defense.py',
    'backend/app/core/rest_throttle_valve.py',
    'backend/app/core/rest_book_cache.py',
    'backend/app/core/rest_symbol_pace.py',
    'backend/app/core/position_supervisor.py',
    'backend/scripts/check_system.py',
    '_verify_fixes.py',
]

for f in files:
    r = subprocess.run(['git', 'add', f], capture_output=True, text=True, timeout=60)
    print(f'add {f}: {r.returncode}')

msg = 'fix: stop force_refresh death spiral under IP cool-down + pending-order merge'
r = subprocess.run(['git', 'commit', '-m', msg], capture_output=True, text=True, timeout=60)
print(f'commit: {r.returncode} {r.stdout[:300]}')
if r.returncode != 0:
    print(f'stderr: {r.stderr[:300]}')

r = subprocess.run(['git', 'push', 'origin', 'HEAD'], capture_output=True, text=True, timeout=60)
print(f'push: {r.returncode} {r.stdout[:300]}')
if r.returncode != 0:
    print(f'stderr: {r.stderr[:300]}')

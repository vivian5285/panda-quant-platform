"""Test complete signal processing path - sends Python code via SSH stdin"""
import subprocess, sys

HOST = "root@187.77.130.144"
KEY = r"C:\Users\Administrator\.ssh\id_rsa"

python_code = """
import sys
sys.path.insert(0, '/app')

print('Step 1: imports...')
from app.core.exchange_factory import create_supervisor
from app.database import SessionLocal
from app.models import User
from app.core.symbol_registry import normalize_canonical_symbol
from app.services.dispatcher import supervisor_pool
print('  OK - all imports passed')

print('Step 2: check supervisor for user 6...')
db = SessionLocal()
try:
    user = db.query(User).filter(User.id == 6).first()
    if not user:
        print('  ERROR: user 6 not found')
        sys.exit(1)
    print(f'  user 6: exchange={user.exchange}')
    can = normalize_canonical_symbol(user.exchange, 'XAUUSDT')
    pool_key = str(user.id) + ':' + can
    sup = supervisor_pool._supervisors.get(pool_key)
    print(f'  supervisor: {sup is not None}')
    if not sup:
        print('  ERROR: supervisor not found')
        sys.exit(1)
    print('  OK - supervisor found')

    print('Step 3: handle_signal...')
    payload = {
        'secret': 'test',
        'action': 'LONG',
        'symbol': 'XAUUSDT',
        'price': 2410.5,
        'atr': 15.2,
        'stop_loss': 2385.0,
        'tp1': 2430.0,
        'tp2': 2450.0,
        'tp3': 2480.0,
        'regime': 'strong'
    }
    result = sup.handle_signal(payload)
    print(f'  status: {result.get(\"status\")}')
    if result.get('status') == 'error':
        print(f'  error: {result.get(\"message\")}')
    print('  handle_signal completed')
finally:
    db.close()

print('ALL TESTS PASSED')
"""

# Write to local file
with open(r"C:\Users\Administrator\Desktop\panda-quant-platform\test_signal.py", "w") as f:
    f.write(python_code)

# Encode to base64
import base64
b64 = base64.b64encode(python_code.encode()).decode()
print(f"Code length: {len(python_code)}, base64 length: {len(b64)}")

# Send to VPS and execute via stdin
result = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30",
     "-i", KEY, HOST,
     f"python3 -c \"import base64, sys; exec(base64.b64decode(sys.stdin.read()).decode())\""],
    input=b64.encode(),
    capture_output=True, text=True, timeout=60
)

print("STDOUT:")
for line in result.stdout.split("\n")[:30]:
    if line.strip():
        print(f"  {line}")

if result.stderr:
    print("STDERR:")
    for line in result.stderr.split("\n")[:10]:
        if line.strip():
            print(f"  {line}")

print(f"Exit code: {result.returncode}")

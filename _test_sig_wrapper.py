"""Send test signal via direct API call inside container and capture traceback"""
import subprocess, base64, sys

HOST = "root@187.77.130.144"
KEY = r"C:\Users\Administrator\.ssh\id_rsa"

# Write test script to VPS via python subprocess
test_code = r'''import sys
sys.path.insert(0, "/app")
import json, traceback

from app.database import SessionLocal
from app.models import User
from app.core.symbol_registry import normalize_canonical_symbol
from app.services.dispatcher import supervisor_pool

payload = {
    "secret": "test",
    "action": "LONG",
    "symbol": "XAUUSDT",
    "price": 2410.5,
    "atr": 15.2,
    "stop_loss": 2385.0,
    "tp1": 2430.0,
    "tp2": 2450.0,
    "tp3": 2480.0,
    "regime": "strong"
}

db = SessionLocal()
try:
    user = db.query(User).filter(User.id == 6).first()
    if not user:
        print("ERROR: user 6 not found")
        sys.exit(1)
    can = normalize_canonical_symbol(user.exchange, "XAUUSDT")
    pool_key = str(user.id) + ":" + can
    sup = supervisor_pool._supervisors.get(pool_key)
    if not sup:
        print("ERROR: supervisor not found for " + pool_key)
        sys.exit(1)
    print("Supervisor found, calling handle_signal...")
    try:
        result = sup.handle_signal(payload)
        print("Result:", json.dumps(result, indent=2))
    except Exception as e:
        tb = traceback.format_exc()
        print("EXCEPTION during handle_signal:")
        print(tb)
finally:
    db.close()
'''

# Write to local file
with open(r"C:\Users\Administrator\Desktop\panda-quant-platform\_test_sig.py", "w") as f:
    f.write(test_code)

# Upload to VPS via cat stdin
upload = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30",
     "-i", KEY, HOST, "cat > /tmp/_test_sig.py"],
    input=test_code.encode(),
    capture_output=True, text=True, timeout=30
)
print("Upload:", upload.returncode, upload.stderr[:100] if upload.stderr else "")

# Copy to container
copy = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30",
     "-i", KEY, HOST,
     "docker cp /tmp/_test_sig.py panda-quant-platform-backend-1:/tmp/_test_sig.py"],
    capture_output=True, text=True, timeout=30
)
print("Copy:", copy.returncode)

# Run in container
result = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30",
     "-i", KEY, HOST,
     "docker exec panda-quant-platform-backend-1 python /tmp/_test_sig.py"],
    capture_output=True, text=True, timeout=120
)

print("\n=== STDOUT ===")
for line in result.stdout.split("\n"):
    if line.strip():
        print(line)

if result.stderr:
    print("\n=== STDERR ===")
    for line in result.stderr.split("\n")[:20]:
        if line.strip():
            print(line)

print(f"\nExit code: {result.returncode}")

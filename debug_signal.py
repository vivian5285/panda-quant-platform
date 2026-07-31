"""Connect to VPS via paramiko and debug signal processing"""
import paramiko, sys, time

HOST = "187.77.130.144"
USER = "root"
KEY = r"C:\Users\Administrator\.ssh\id_rsa"

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, key_filename=KEY, timeout=30)

# Write test script to VPS via SFTP
test_script = r'''import sys
sys.path.insert(0, "/app")
import traceback

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
    print("User 6 exchange:", user.exchange)
    can = normalize_canonical_symbol(user.exchange, "XAUUSDT")
    pool_key = str(user.id) + ":" + can
    print("pool_key:", pool_key)
    sup = supervisor_pool._supervisors.get(pool_key)
    print("supervisor found:", sup is not None)
    if not sup:
        sys.exit(1)
    print("Calling handle_signal...")
    try:
        result = sup.handle_signal(payload)
        print("Result status:", result.get("status"))
        if result.get("status") == "error":
            print("Error message:", result.get("message"))
    except Exception as e:
        print("EXCEPTION:", type(e).__name__, str(e))
        tb = traceback.format_exc()
        print(tb)
finally:
    db.close()
'''

sftp = client.open_sftp()
with sftp.open("/tmp/_debug_sig.py", "w") as f:
    f.write(test_script)
sftp.close()
print("Script uploaded")

# Run it in container
stdin, stdout, stderr = client.exec_command(
    "docker cp /tmp/_debug_sig.py panda-quant-platform-backend-1:/tmp/_debug_sig.py && "
    "docker exec panda-quant-platform-backend-1 python /tmp/_debug_sig.py 2>&1",
    timeout=120
)

print("\n=== OUTPUT ===")
for line in stdout:
    print(line.rstrip())

if stderr.read():
    print("\n=== STDERR ===")
    stderr.seek(0)
    for line in stderr:
        print(line.rstrip())

client.close()

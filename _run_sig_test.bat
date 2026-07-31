@echo off
echo Step 1: Write test script to VPS
ssh -o StrictHostKeyChecking=no -i %USERPROFILE%\.ssh\id_rsa root@187.77.130.144 "cat > /tmp/_sig_test.py << 'PYEOF'
import sys
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
    print(f"user 6: exchange={user.exchange}")
    can = normalize_canonical_symbol(user.exchange, "XAUUSDT")
    pool_key = str(user.id) + ":" + can
    print(f"pool_key={pool_key}")
    sup = supervisor_pool._supervisors.get(pool_key)
    print(f"supervisor found: {sup is not None}")
    if not sup:
        sys.exit(1)
    print("Calling handle_signal...")
    try:
        result = sup.handle_signal(payload)
        print(f"Result status: {result.get('status')}")
        if result.get("status") == "error":
            print(f"Error message: {result.get('message')}")
    except Exception as e:
        print(f"EXCEPTION: {type(e).__name__}: {e}")
        tb = traceback.format_exc()
        print(tb)
finally:
    db.close()
PYEOF"
echo Step 1 done

echo Step 2: Copy to container
ssh -o StrictHostKeyChecking=no -i %USERPROFILE%\.ssh\id_rsa root@187.77.130.144 "docker cp /tmp/_sig_test.py panda-quant-platform-backend-1:/tmp/_sig_test.py"
echo Step 2 done

echo Step 3: Run in container
ssh -o StrictHostKeyChecking=no -i %USERPROFILE%\.ssh\id_rsa root@187.77.130.144 "docker exec panda-quant-platform-backend-1 python /tmp/_sig_test.py"
echo Done

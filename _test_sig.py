import sys
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

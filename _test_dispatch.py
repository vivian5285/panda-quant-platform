import sys
import json
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.services.webhook_payload import parse_webhook_payload
from app.services.webhook_guard import validate_signal_payload
from app.services.signal_admin import run_signal_dispatch

payload = {
    "symbol": "XAUUSDT.P",
    "action": "LONG",
    "price": 2381.19,
    "stop_loss": 2358.33,
    "tp1": 2405.61,
    "tp2": 2429.14,
    "tp3": 2453.56,
    "atr": 15.0,
    "secret": "528586",
    "bot_id": "Trillion_God_v7.2_VPSFinal",
    "regime": "moderate",
    "bar_index": 1,
    "seq": 1
}

print("1. Parsing payload...")
data, err = parse_webhook_payload(json.dumps(payload))
if err:
    print(f"FAIL: Parse error: {err}")
    sys.exit(1)
print(f"OK: Parsed: action={data.get('action')}, symbol={data.get('symbol')}")

print("2. Validating payload...")
ok, verr = validate_signal_payload(data)
if not ok:
    print(f"FAIL: Validation error: {verr}")
    sys.exit(1)
print("OK: Validation passed")

print("3. Running signal dispatch...")
db = SessionLocal()
try:
    row, result = run_signal_dispatch(db, data, source="webhook")
    print(f"OK: Dispatched - ok={row.dispatched_count}, errors={row.error_count}")
    print(f"Results: {json.dumps(result, indent=2)}")
except Exception as e:
    print(f"FAIL: Dispatch exception: {e}")
    import traceback
    traceback.print_exc()
finally:
    db.close()

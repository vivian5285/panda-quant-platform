import sys
sys.path.insert(0, "/app")

# Don't import directly, use the same import path as the webhook
from app.services.dispatcher import signal_dispatcher

print("=== Dispatcher Instance Check ===")
print(f"signal_dispatcher id: {id(signal_dispatcher)}")
print(f"Pool id: {id(signal_dispatcher.pool)}")
print(f"Pool supervisors: {len(signal_dispatcher.pool._supervisors)}")
print(f"Startup complete: {signal_dispatcher.pool.startup_complete}")

for key, sup in signal_dispatcher.pool._supervisors.items():
    print(f"  {key}: canonical_symbol={getattr(sup, 'canonical_symbol', 'N/A')}")

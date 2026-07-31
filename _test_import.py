import sys
sys.path.insert(0, "/app")

print("Testing force_refresh import...")

try:
    from app.core.market_engine import force_refresh
    print("OK: force_refresh imported from market_engine")
    print("Type:", type(force_refresh))
except ImportError as e:
    print("FAIL: Cannot import force_refresh:", e)

try:
    from app.core.position_supervisor import PositionSupervisor
    print("OK: PositionSupervisor imported")
except ImportError as e:
    print("FAIL: Cannot import PositionSupervisor:", e)

try:
    from app.services.dispatcher import signal_dispatcher
    print("OK: signal_dispatcher imported")
except ImportError as e:
    print("FAIL: Cannot import signal_dispatcher:", e)

print("All imports OK")

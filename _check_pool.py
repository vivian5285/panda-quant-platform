import sys
sys.path.insert(0, "/app")

from app.services.dispatcher import supervisor_pool
from app.database import SessionLocal
from app.models import User, ApiStatus

print("=== Supervisor Pool Status ===")
print(f"Total supervisors: {len(supervisor_pool._supervisors)}")
print(f"Startup complete: {supervisor_pool.startup_complete}")
print(f"Startup in progress: {supervisor_pool.startup_in_progress}")

print("\nSupervisors in pool:")
for key, sup in supervisor_pool._supervisors.items():
    print(f"  Key: {key}, Symbol: {getattr(sup, 'canonical_symbol', 'N/A')}")

print("\nReloading users...")
supervisor_pool.load_active_users(SessionLocal())
print(f"After reload: {len(supervisor_pool._supervisors)} supervisors")

print("\nSupervisors after reload:")
for key, sup in supervisor_pool._supervisors.items():
    print(f"  Key: {key}, Symbol: {getattr(sup, 'canonical_symbol', 'N/A')}")

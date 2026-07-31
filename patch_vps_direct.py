"""Patch container directly via docker exec sed - no SSH file transfer needed"""
import subprocess, time

# The key insight: add force_refresh as a class attribute/method on PositionSupervisor
# so ANY code path in the class will find it without needing module-level import

patch_code = """
import sys
sys.path.insert(0, '/app')

# Patch 1: Add force_refresh to PositionSupervisor class
from app.core.position_supervisor import PositionSupervisor
if not hasattr(PositionSupervisor, '_force_refresh_ensure_fresh'):
    # Add as a bound method-like attribute
    from app.core.market_engine import ensure_fresh
    PositionSupervisor._force_refresh_ensure_fresh = staticmethod(ensure_fresh)
    # Also patch the module
    import app.core.position_supervisor as ps_module
    if not hasattr(ps_module, 'force_refresh'):
        from app.core.market_engine import ensure_fresh
        ps_module.force_refresh = ensure_fresh
    print('Patched PositionSupervisor')

# Patch 2: Patch AdverseRadarMixin
try:
    from app.core.adverse_radar_guard import AdverseRadarMixin
    if not hasattr(AdverseRadarMixin, '_force_refresh_patched'):
        from app.core.market_engine import ensure_fresh
        AdverseRadarMixin._force_refresh_patched = True
        AdverseRadarMixin._fr_ef = staticmethod(ensure_fresh)
        print('Patched AdverseRadarMixin')
except Exception as e:
    print(f'Patch 2 error: {e}')

print('All patches applied')
"""

with open("C:/Users/Administrator/Desktop/panda-quant-platform/_patch_vps.py", "w") as f:
    f.write(patch_code)

# Write to VPS
result = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-i",
     "C:/Users/Administrator/.ssh/id_rsa",
     "root@187.77.130.144",
     "cat > /tmp/_patch_vps.py"],
    input=patch_code.encode(),
    capture_output=True, text=True, timeout=30
)
print("Upload:", result.returncode)
if result.stderr:
    print("ERR:", result.stderr[:100])

# Copy to container
result = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-i",
     "C:/Users/Administrator/.ssh/id_rsa",
     "root@187.77.130.144",
     "docker cp /tmp/_patch_vps.py panda-quant-platform-backend-1:/tmp/_patch_vps.py"],
    capture_output=True, text=True, timeout=30
)
print("Copy:", result.returncode)

# Run in container
result = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-i",
     "C:/Users/Administrator/.ssh/id_rsa",
     "root@187.77.130.144",
     "docker exec panda-quant-platform-backend-1 python /tmp/_patch_vps.py"],
    capture_output=True, text=True, timeout=30
)
print("Patch output:")
for line in result.stdout.split("\n"):
    if line.strip():
        print(f"  {line}")

# Now test the signal
print("\n--- Testing signal ---")
result = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-i",
     "C:/Users/Administrator/.ssh/id_rsa",
     "root@187.77.130.144",
     "docker exec panda-quant-platform-backend-1 python /tmp/sw3.py"],
    capture_output=True, text=True, timeout=30
)
print("Webhook:", result.stdout.strip())

time.sleep(13)

# Check logs
result = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-i",
     "C:/Users/Administrator/.ssh/id_rsa",
     "root@187.77.130.144",
     "docker logs panda-quant-platform-backend-1 --tail 20 2>&1 | grep -E 'dispatch|LONG|XAU|FAIL|force_refresh|open|ok=1'"],
    capture_output=True, text=True, timeout=30
)
print("Logs:")
for line in result.stdout.split("\n"):
    if line.strip():
        print(f"  {line}")

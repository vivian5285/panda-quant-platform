"""Patch all force_refresh imports on VPS and redeploy"""
import subprocess, time, sys

HOST = "root@187.77.130.144"
KEY = r"C:\Users\Administrator\.ssh\id_rsa"

def run(cmd, timeout=600):
    print(f"Running: {cmd[:80]}...")
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30",
         "-i", KEY, HOST, cmd],
        capture_output=True, text=True, timeout=timeout
    )
    if result.stdout:
        for line in result.stdout.split('\n')[:5]:
            if line.strip():
                print(f"  OUT: {line}")
    if result.returncode != 0 and result.stderr:
        err_lines = result.stderr.strip().split('\n')
        for line in err_lines[:3]:
            if line.strip():
                print(f"  ERR: {line}")
    return result

# Step 1: Write patch script to VPS
patch_script = r"""
import re, os
root = "/home/panda/panda-quant-platform/backend/app"
changes = 0
for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if d not in ('__pycache__', '.git')]
    for fn in filenames:
        if not fn.endswith('.py'):
            continue
        fp = os.path.join(dirpath, fn)
        with open(fp) as f:
            c = f.read()
        orig = c
        # Replace import statements
        c = re.sub(r'\bfrom\s+app\.core\.market_engine\s+import\s+([^)]*?)force_refresh\b',
                   lambda m: 'from app.core.market_engine import ' + m.group(1).rstrip(',') + 'ensure_fresh',
                   c)
        c = re.sub(r'\bfrom\s+app\.core\.market_engine\s+import\s+force_refresh\b',
                   'from app.core.market_engine import ensure_fresh', c)
        if c != orig:
            with open(fp, 'w') as f:
                f.write(c)
            changes += 1
            print(f"PATCHED: {fp}")
print(f"Total: {changes}")
"""

result = run(f"cat > /tmp/patch_all.py << 'SCRIPT'\n{patch_script}\nSCRIPTEOF")
if result.returncode != 0:
    print("Failed to write patch script")
    sys.exit(1)

# Step 2: Run patch
result = run("python3 /tmp/patch_all.py")
if result.returncode != 0:
    print("Patch failed")
    sys.exit(1)

# Step 3: Rebuild
result = run(
    "cd /home/panda/panda-quant-platform && docker compose build --no-cache backend",
    timeout=600
)
if result.returncode != 0:
    print("Docker build failed")
    sys.exit(1)

# Step 4: Restart
result = run("cd /home/panda/panda-quant-platform && docker compose up -d backend")
if result.returncode != 0:
    print("Docker restart failed")
    sys.exit(1)

print("Waiting 15s for startup...")
time.sleep(15)

# Step 5: Check logs
result = run("docker logs panda-quant-platform-backend-1 --tail 5")
if result.returncode == 0:
    print("Container logs:")
    for line in result.stdout.split('\n'):
        if line.strip():
            print(f"  {line}")

# Step 6: Send test signal
print("\nSending test webhook...")
result = run(
    "docker compose -f /home/panda/panda-quant-platform/docker-compose.yml exec -T backend python /tmp/sw3.py",
    timeout=30
)
print("Test result:", result.stdout[:200] if result.stdout else "no output")

# Step 7: Check dispatch
time.sleep(3)
result = run(
    "docker logs panda-quant-platform-backend-1 --tail 20 2>&1 | grep -E 'dispatch|LONG|XAU|FAIL|force_refresh|open|reentry' | tail -15"
)
print("Dispatch logs:")
for line in result.stdout.split('\n'):
    if line.strip():
        print(f"  {line}")

print("\nDone!")

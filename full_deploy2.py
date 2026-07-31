"""Execute all steps on VPS using Python subprocess - no PowerShell quoting issues"""
import subprocess, time, sys, os

KEY = r"C:\Users\Administrator\.ssh\id_rsa"
HOST = "root@187.77.130.144"

def run(cmd, timeout=600, check=True):
    print(f"CMD: {cmd[:80]}...")
    r = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30",
         "-i", KEY, HOST, cmd],
        capture_output=True, text=True, timeout=timeout
    )
    if r.stdout:
        for l in r.stdout.split("\n")[:5]:
            if l.strip(): print(f"  OUT: {l}")
    if r.returncode != 0 and r.stderr:
        for l in r.stderr.strip().split("\n")[:3]:
            if l.strip(): print(f"  ERR: {l}")
    if check and r.returncode != 0:
        print(f"FAILED (code {r.returncode})")
        sys.exit(1)
    return r

# Step 1: Check if force_refresh import still exists in VPS filesystem
print("=== Checking VPS filesystem ===")
run("grep -rn 'from app.core.market_engine import.*force_refresh' /home/panda/panda-quant-platform/backend/app/ --include='*.py' | head -5", check=False)

# Step 2: Write comprehensive patch script
print("\n=== Writing patch script ===")
patch_content = r"""import re, os
root = "/home/panda/panda-quant-platform/backend/app"
changed = []
for dp, dns, fns in os.walk(root):
    dns[:] = [d for d in dns if d not in ('__pycache__', '.git')]
    for fn in fns:
        if not fn.endswith('.py'): continue
        fp = os.path.join(dp, fn)
        with open(fp) as f: c = f.read()
        orig = c
        # Replace import statement
        c = re.sub(r'(\bfrom\s+app\.core\.market_engine\s+import\s+)([^)]*?)force_refresh\b',
                   lambda m: m.group(1) + m.group(2).rstrip(',\n ') + ', ensure_fresh',
                   c)
        c = re.sub(r'\bfrom\s+app\.core\.market_engine\s+import\s+force_refresh\b',
                   'from app.core.market_engine import ensure_fresh', c)
        if c != orig:
            with open(fp, 'w') as f: f.write(c)
            changed.append(fp)
            print(f"PATCHED: {fp}")
print(f"Total: {len(changed)}")
"""

run(f"cat > /tmp/patch2.py << 'SCRIPTEOF'\n{patch_content}\nSCRIPTEOF")
print("Patch script written")

# Step 3: Run patch
print("\n=== Running patch ===")
run("python3 /tmp/patch2.py")

# Step 4: Verify patch
print("\n=== Verifying ===")
run("grep -rn 'from app.core.market_engine import.*force_refresh' /home/panda/panda-quant-platform/backend/app/ --include='*.py' | head -5", check=False)

# Step 5: Rebuild Docker
print("\n=== Rebuilding Docker ===")
r = subprocess.run(
    ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30",
     "-i", KEY, HOST,
     "cd /home/panda/panda-quant-platform && docker compose build --no-cache backend"],
    capture_output=True, text=True, timeout=600
)
# Print last few lines of build
lines = r.stdout.strip().split("\n")
for l in lines[-5:]:
    if l.strip(): print(f"  {l}")
if r.returncode != 0:
    print("Build failed:", r.stderr[:200])
    sys.exit(1)
print("Build succeeded")

# Step 6: Restart
print("\n=== Restarting container ===")
run("cd /home/panda/panda-quant-platform && docker compose up -d backend")

# Step 7: Wait for startup
print("Waiting 12s for startup...")
time.sleep(12)

# Step 8: Check logs
print("\n=== Container logs ===")
run("docker logs panda-quant-platform-backend-1 --tail 5", check=False)

# Step 9: Send test signal
print("\n=== Sending test webhook ===")
run("docker compose -f /home/panda/panda-quant-platform/docker-compose.yml exec -T backend python /tmp/sw3.py", check=False)

# Step 10: Check dispatch logs
time.sleep(3)
print("\n=== Dispatch logs ===")
run("docker logs panda-quant-platform-backend-1 --tail 20 2>&1 | grep -E 'dispatch|LONG|XAU|FAIL|force_refresh|open|reentry' | tail -15", check=False)

print("\n=== DONE ===")

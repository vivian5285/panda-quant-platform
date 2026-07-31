"""Deploy the fix to VPS"""
import subprocess
import sys
import time

HOST = "root@187.77.130.144"
KEY = r"C:\Users\Administrator\.ssh\id_rsa"

def run_cmd(cmd, timeout=30):
    print(f"Running: {cmd[:60]}...")
    try:
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", "-i", KEY, HOST, cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT after {timeout}s")
        return None
    except Exception as e:
        print(f"  ERROR: {e}")
        return None

# Test connection
print("Testing SSH connection...")
result = run_cmd("echo 'connected'")
if result and result.returncode == 0:
    print("SSH connection OK")
else:
    print("SSH connection FAILED")
    sys.exit(1)

# Read the fixed file
with open("backend/app/core/market_engine.py", "r") as f:
    content = f.read()

# Write to server
print("Uploading fixed market_engine.py...")
result = run_cmd(f"cat > /tmp/market_engine.py << 'EOF'\n{content}\nEOF", timeout=60)
if not result or result.returncode != 0:
    print("Upload failed")
    sys.exit(1)

# Check if file was written
result = run_cmd("wc -l /tmp/market_engine.py")
if result and result.returncode == 0:
    print(f"Uploaded file: {result.stdout.strip()}")

print("Done! Manual steps needed:")
print("1. cp /tmp/market_engine.py to container or rebuild")
print("2. docker compose restart backend")

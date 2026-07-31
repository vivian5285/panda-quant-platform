"""Complete fix: adverse_radar_guard.py force_refresh -> ensure_fresh"""
import paramiko, time, sys

HOST = "187.77.130.144"
USER = "root"
KEY = "~/.ssh/id_rsa"

fix_script = r"""
import re
path = "/home/panda/panda-quant-platform/backend/app/core/adverse_radar_guard.py"
with open(path) as f:
    c = f.read()
orig = c

# 1. Remove force_refresh from import
c = re.sub(r'\n    force_refresh,\n', '\n', c)

# 2. Replace ternary with single line
old = r'''
        snap = (
            force_refresh(client=client, exchange=ex, symbol=sym)
            if force
            else ensure_fresh(client=client, exchange=ex, symbol=sym)
        )'''
new = '        snap = ensure_fresh(client=client, exchange=ex, symbol=sym)'
c = c.replace(old.strip(), new)

if c == orig:
    print("NO CHANGE - check pattern")
    import sys; sys.exit(1)

with open(path, 'w') as f:
    f.write(c)
print("Patched OK")
# verify
with open(path) as f:
    c2 = f.read()
assert 'force_refresh,' not in c2.split('from app.core.market_engine import')[1].split(')')[0]
assert 'if force' not in c2[c2.find('snap = ensure_fresh')-50:c2.find('snap = ensure_fresh')+50]
print("Verified OK")
"""

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(HOST, username=USER, key_filename=KEY, timeout=30)

# Step 1: Write fix script to VPS
sftp = client.open_sftp()
with sftp.open("/tmp/f.py", "w") as f:
    f.write(fix_script)
sftp.close()
print("Uploaded fix script")

# Step 2: Run it
stdin, stdout, stderr = client.exec_command("python3 /tmp/f.py")
chunks = []
while True:
    line = stdout.readline()
    if not line:
        break
    chunks.append(line)
output = "".join(chunks)
print("Fix output:", output)

err = stderr.read().decode()
if err.strip():
    print("Fix stderr:", err)

# Step 3: Rebuild Docker
print("Rebuilding Docker...")
_, stdout, stderr = client.exec_command(
    "cd /home/panda/panda-quant-platform && docker compose build --no-cache backend 2>&1",
    timeout=600
)
for line in stdout:
    sys.stdout.write(line)
err = stderr.read().decode()
if err.strip():
    print("Build stderr:", err[-500:])

# Step 4: Restart
print("Restarting container...")
_, stdout, stderr = client.exec_command(
    "docker compose -f /home/panda/panda-quant-platform/docker-compose.yml up -d backend 2>&1",
    timeout=60
)
for line in stdout:
    sys.stdout.write(line)

# Step 5: Wait and check logs
time.sleep(10)
_, stdout, stderr = client.exec_command("docker logs panda-quant-platform-backend-1 --tail 5 2>&1")
for line in stdout:
    print("LOG:", line.rstrip())

client.close()
print("DONE")

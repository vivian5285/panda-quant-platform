#!/usr/bin/env python3
import subprocess

# Read the file
result = subprocess.run(
    ["docker", "exec", "panda-quant-platform-backend-1", "cat", "/app/app/core/position_supervisor.py"],
    capture_output=True, text=True
)
content = result.stdout

# Add force_refresh import after the other imports
# Find the line with "from app.core.breathing_stop import"
old_import = "from app.core.breathing_stop import load_breathing_coef, resolve_breathing_coef"
new_import = """from app.core.breathing_stop import load_breathing_coef, resolve_breathing_coef
from app.core.market_engine import force_refresh"""

if old_import in content and "from app.core.market_engine import force_refresh" not in content:
    content = content.replace(old_import, new_import)
    print("Added force_refresh import")
else:
    print("Import already exists or old import not found")

# Write back
import tempfile
with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
    f.write(content)
    temp_path = f.name

# Copy to server and then to container
subprocess.run(["docker", "cp", temp_path, "panda-quant-platform-backend-1:/tmp/position_supervisor.py"])
subprocess.run(["docker", "exec", "panda-quant-platform-backend-1", "cp", "/tmp/position_supervisor.py", "/app/app/core/position_supervisor.py"])
print("File updated on server")

# Clean up
import os
os.unlink(temp_path)

# Restart the container to apply changes
print("Restarting container...")
subprocess.run(["docker", "restart", "panda-quant-platform-backend-1"])
print("Container restarted")

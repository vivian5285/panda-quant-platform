import subprocess
result = subprocess.run(
    ["docker", "exec", "panda-quant-platform-backend-1", 
     "grep", "-rn", "from app.core.market_engine import", "/app/app/"],
    capture_output=True, text=True
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)

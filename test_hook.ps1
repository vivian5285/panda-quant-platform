$ErrorActionPreference = "Continue"
$SSH = "ssh -o StrictHostKeyChecking=no root@187.77.130.144"

# Step 1: Write the Python script to VPS via SSH heredoc with double quotes escaped
$pythonScript = 'import json,urllib.request
payload={"secret":"528586","action":"LONG","symbol":"XAUUSDT","price":2410.50,"atr":15.2,"stop_loss":2385.00,"tp1":2430.00,"tp2":2450.00,"tp3":2480.00,"regime":"strong","reason":"cursor_test","tv_tp1":2430.00,"tv_tp2":2450.00,"tv_tp3":2480.00,"tv_sl":2385.00}
url="https://twinstar.pro/gemini/webhook"
data=json.dumps(payload).encode("utf-8")
req=urllib.request.Request(url,data=data,headers={"Content-Type":"application/json"})
resp=urllib.request.urlopen(req,timeout=20)
print("Status: %d" % resp.status)
print("Response: %s" % resp.read().decode("utf-8"))'

# Write using printf to avoid heredoc issues
$cmd = "printf '%s' `"" + $pythonScript.Replace("`"", "```"") + "`" > /tmp/sw3.py"
Write-Host "Writing script to VPS..."
$writeResult = & cmd.exe /c "ssh -o StrictHostKeyChecking=no root@187.77.130.144 `"$cmd`"" 2>&1
Write-Host $writeResult

# Step 2: Copy to container
Write-Host "Copying to container..."
$cpResult = & cmd.exe /c "ssh -o StrictHostKeyChecking=no root@187.77.130.144 `"docker cp /tmp/sw3.py panda-quant-platform-backend-1:/tmp/sw3.py`"" 2>&1
Write-Host $cpResult

# Step 3: Run in container
Write-Host "Running webhook test..."
$runResult = & cmd.exe /c "ssh -o StrictHostKeyChecking=no root@187.77.130.144 `"docker compose -f /home/panda/panda-quant-platform/docker-compose.yml exec -T backend python /tmp/sw3.py`"" 2>&1
Write-Host $runResult

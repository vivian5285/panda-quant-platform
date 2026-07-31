"""Send test webhook to VPS and return logs"""
import subprocess, time

# Step 1: Write the test script to VPS via python subprocess (avoids PowerShell quoting)
script_content = r'''import requests,json,time,hashlib,hmac,sys
BASE='http://localhost:8000'
p={"secret":"panda_test_secret_2024","action":"LONG","symbol":"XAUUSDT","price":2410.5,"atr":15.2,"stop_loss":2385.0,"tp1":2430.0,"tp2":2450.0,"tp3":2480.0,"bot_id":999,"regime":"strong"}
ts=str(int(time.time()))
sig=hmac.new(b"panda_test_secret_2024",(ts+json.dumps(p,separators=(",",":"),sort_keys=True)).encode(),hashlib.sha256).hexdigest()
r=requests.post(f"{BASE}/gemini/webhook",json=p,headers={"Content-Type":"application/json","X-Sig-Ts":ts,"X-Sig":sig},timeout=10)
print("Status:",r.status_code)
print("Response:",r.text[:500])
'''

# Write script to VPS using subprocess
write_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', '-i', r'C:\Users\Administrator\.ssh\id_rsa',
             'root@187.77.130.144', f'cat > /tmp/sw5.py << \'SCRIPTEOF\'\n{script_content}\nSCRIPTEOF']
print("Writing script to VPS...")
result = subprocess.run(write_cmd, capture_output=True, text=True, timeout=30)
print("write:", result.returncode, result.stdout[:200], result.stderr[:200])

# Step 2: Run the test
run_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', '-i', r'C:\Users\Administrator\.ssh\id_rsa',
           'root@187.77.130.144',
           'cd /home/panda/panda-quant-platform && docker compose exec -T backend python /tmp/sw5.py']
print("Running test...")
result = subprocess.run(run_cmd, capture_output=True, text=True, timeout=30)
print("Status:", result.returncode)
print("STDOUT:", result.stdout[:500])
print("STDERR:", result.stderr[:200])

# Step 3: Wait and check logs
time.sleep(3)
log_cmd = ['ssh', '-o', 'StrictHostKeyChecking=no', '-i', r'C:\Users\Administrator\.ssh\id_rsa',
           'root@187.77.130.144', 'docker logs panda-quant-platform-backend-1 --tail 20 2>&1 | tail -15']
result = subprocess.run(log_cmd, capture_output=True, text=True, timeout=30)
print("\n=== CONTAINER LOGS ===")
for line in result.stdout.split('\n'):
    if any(k in line for k in ['u6', 'gemini', 'LONG', 'XAU', 'ERROR', 'FAIL', 'force_refresh', 'dispatch', 'signal']):
        print(line)

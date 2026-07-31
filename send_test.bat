@echo off
set SSH_HOST=root@187.77.130.144
set REMOTE_SCRIPT=/tmp/sw4.py
set LOCAL_SCRIPT=%TEMP%\sw4_local.py

python -c "
content = '''
import requests, json, time, hashlib, hmac, sys
BASE_URL = sys.argv[1] if len(sys.argv) > 1 else \"http://localhost:8000\"
payload = {
    \"secret\": \"panda_test_secret_2024\",
    \"action\": \"LONG\",
    \"symbol\": \"XAUUSDT\",
    \"price\": 2410.5,
    \"atr\": 15.2,
    \"stop_loss\": 2385.0,
    \"tp1\": 2430.0,
    \"tp2\": 2450.0,
    \"tp3\": 2480.0,
    \"bot_id\": 999,
    \"regime\": \"strong\"
}
ts = str(int(time.time()))
sig_input = ts + json.dumps(payload, separators=(\",\", \":\"), sort_keys=True)
sig = hmac.new(b\"panda_test_secret_2024\", sig_input.encode(), hashlib.sha256).hexdigest()
headers = {\"Content-Type\": \"application/json\", \"X-Sig-Ts\": ts, \"X-Sig\": sig}
r = requests.post(f\"{BASE_URL}/gemini/webhook\", json=payload, headers=headers, timeout=10)
print(f\"Status: {r.status_code}\")
print(f\"Response: {r.text[:500]}\")
'''
with open(r'%LOCAL_SCRIPT%', 'w') as f:
    f.write(content)
print('Local script written')
"

echo Uploading to VPS...
scp -o StrictHostKeyChecking=no -i %USERPROFILE%\.ssh\id_rsa %LOCAL_SCRIPT% %SSH_HOST%:%REMOTE_SCRIPT%
if errorlevel 1 echo Upload failed && exit /b 1

echo Running test...
ssh -o StrictHostKeyChecking=no -i %USERPROFILE%\.ssh\id_rsa %SSH_HOST% "docker compose -f /home/panda/panda-quant-platform/docker-compose.yml exec -T backend python %REMOTE_SCRIPT%"

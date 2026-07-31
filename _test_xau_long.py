import json
import urllib.request
import time

url = "https://twinstar.pro/gemini/webhook"

# XAUUSDT LONG 测试
payload = {
    "symbol": "XAUUSDT.P",
    "action": "LONG",
    "price": 2381.19,
    "stop_loss": 2358.33,
    "tp1": 2405.61,
    "tp2": 2429.14,
    "tp3": 2453.56,
    "atr": 15.0,
    "secret": "528586",
    "bot_id": "Trillion_God_v7.2_VPSFinal",
    "regime": "moderate",
    "bar_index": 1,
    "seq": int(time.time()) % 10000
}

print(f"=== XAUUSDT LONG 测试 (seq={payload['seq']}) ===")
print(f"Payload: {json.dumps(payload, indent=2)}")

data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')

try:
    with urllib.request.urlopen(req, timeout=30) as response:
        result = response.read().decode('utf-8')
        print(f"\nWebhook Response: {result}")
except Exception as e:
    print(f"\nError: {str(e)}")

print("\n等待处理...")
time.sleep(25)
print("检查完成")

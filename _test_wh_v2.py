import json
import urllib.request

url = "https://twinstar.pro/gemini/webhook"
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
    "seq": 1
}

data = json.dumps(payload).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')

try:
    with urllib.request.urlopen(req, timeout=30) as response:
        result = response.read().decode('utf-8')
        print("Response:", result)
except Exception as e:
    print("Error:", str(e))

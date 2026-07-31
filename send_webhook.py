import json, urllib.request

payload = {
    "secret": "g3m1n1_tw1n5t4r_2025",
    "action": "LONG",
    "symbol": "XAUUSDT",
    "price": 2410.50,
    "atr": 15.2,
    "stop_loss": 2385.00,
    "tp1": 2430.00,
    "tp2": 2450.00,
    "tp3": 2480.00,
    "regime": "strong",
    "reason": "internal_test_XAU_LONG",
    "tv_tp1": 2430.00,
    "tv_tp2": 2450.00,
    "tv_tp3": 2480.00,
    "tv_sl": 2385.00
}

url = "https://twinstar.pro/gemini/webhook"
data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = resp.read().decode("utf-8")
        print("Status: %d" % resp.status)
        print("Response: %s" % result)
except Exception as e:
    print("Error: %s" % e)

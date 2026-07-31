#!/usr/bin/env python3
import json
import urllib.request

url = "https://twinstar.pro/gemini/webhook"
payload = {
    "symbol": "ETHUSDT.P",
    "action": "LONG",
    "secret": "528586",
    "price": 3500.0,
    "qty": 1,
    "stop_loss": 3400.0,
    "tp1": 3600.0,
    "tp2": 3700.0,
    "tp3": 3800.0,
    "atr": 15.0,
    "bar_index": 1,
    "seq": 1
}

data = json.dumps(payload).encode()
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
try:
    resp = urllib.request.urlopen(req, timeout=10)
    print(resp.read().decode())
except Exception as e:
    print(f"Error: {e}")

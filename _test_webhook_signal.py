#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
import sys

url = "https://twinstar.pro/gemini/webhook"
payload = {
    "symbol": "ETHUSDT",
    "action": "LONG",
    "price": 3500,
    "stop_loss": 3400,
    "tp1": 3600,
    "tp2": 3700,
    "tp3": 3800,
    "atr": 15,
    "secret": "528586"
}

data = json.dumps(payload).encode()
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
try:
    r = urllib.request.urlopen(req, timeout=10)
    resp = r.read().decode()
    print(f"Response: {resp}")
    print(f"Status: {r.status}")
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.read().decode()}")
except Exception as e:
    print(f"Error: {e}")

#!/usr/bin/env python3
"""20U内测 - 验证信号链路"""
import json
import urllib.request
import time

URL = "https://twinstar.pro/gemini/webhook"
SECRET = "528586"

def send_signal(payload):
    """发送webhook"""
    print(f"发送: {payload['symbol']} {payload['action']}")
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(URL, data=data,
                                headers={'Content-Type': 'application/json'},
                                method='POST')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = resp.read().decode('utf-8')
            print(f"  -> {result}")
            return True
    except Exception as e:
        print(f"  -> Error: {e}")
        return False

# ETH: 20U本金 / 3300 = 0.006 ETH
# XAU: 20U本金 / 2380 = 0.008 XAU
tests = [
    # (symbol, action, price, stop_loss, tp1, tp2, tp3, atr)
    ("ETHUSDT.P", "LONG",  3300.0, 3200.0, 3330.0, 3360.0, 3400.0, 15.0),
    ("ETHUSDT.P", "SHORT", 3300.0, 3400.0, 3270.0, 3240.0, 3200.0, 15.0),
    ("XAUUSDT.P", "LONG",  2380.0, 2350.0, 2390.0, 2400.0, 2410.0, 12.0),
    ("XAUUSDT.P", "SHORT", 2380.0, 2410.0, 2370.0, 2360.0, 2350.0, 12.0),
]

print("=" * 50)
print("20U内测 (20%保证金 x 5杠杆 = 20U名义)")
print("=" * 50)

for symbol, action, price, sl, tp1, tp2, tp3, atr in tests:
    payload = {
        "symbol": symbol,
        "action": action,
        "secret": SECRET,
        "price": price,
        "stop_loss": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "atr": atr,
        "regime": 2,
        "bar_index": int(time.time()) % 100000,
        "seq": int(time.time()) % 10000,
        "qty": 1,  # 最小验证用
    }
    send_signal(payload)
    time.sleep(3)

print("\n测试完成! 检查VPS日志和钉钉")

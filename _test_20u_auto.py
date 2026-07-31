#!/usr/bin/env python3
"""20U内测 - 直接发送TV信号测试"""
import json
import urllib.request
import time

URL = "https://twinstar.pro/gemini/webhook"
SECRET = "528586"

ETH_PRICE = 3300.0
XAU_PRICE = 2380.0

def send_signal(payload, label):
    print(f"\n>>> {label}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(URL, data=data,
                                headers={'Content-Type': 'application/json'},
                                method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = resp.read().decode('utf-8')
            print(f"Response: {result}")
            return True
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_eth_long():
    return send_signal({
        "symbol": "ETHUSDT.P", "action": "LONG", "secret": SECRET,
        "price": ETH_PRICE, "stop_loss": ETH_PRICE - 100,
        "tp1": ETH_PRICE + 30, "tp2": ETH_PRICE + 60, "tp3": ETH_PRICE + 100,
        "atr": 15.0, "regime": 2, "bar_index": int(time.time()) % 100000,
        "seq": int(time.time()) % 10000, "qty": 1,
    }, "ETH 多单 (LONG)")

def test_eth_short():
    return send_signal({
        "symbol": "ETHUSDT.P", "action": "SHORT", "secret": SECRET,
        "price": ETH_PRICE, "stop_loss": ETH_PRICE + 100,
        "tp1": ETH_PRICE - 30, "tp2": ETH_PRICE - 60, "tp3": ETH_PRICE - 100,
        "atr": 15.0, "regime": 2, "bar_index": int(time.time()) % 100000,
        "seq": int(time.time()) % 10000, "qty": 1,
    }, "ETH 空单 (SHORT)")

def test_xau_long():
    return send_signal({
        "symbol": "XAUUSDT.P", "action": "LONG", "secret": SECRET,
        "price": XAU_PRICE, "stop_loss": XAU_PRICE - 30,
        "tp1": XAU_PRICE + 10, "tp2": XAU_PRICE + 20, "tp3": XAU_PRICE + 30,
        "atr": 12.0, "regime": 2, "bar_index": int(time.time()) % 100000,
        "seq": int(time.time()) % 10000, "qty": 1,
    }, "XAU 多单 (LONG)")

def test_xau_short():
    return send_signal({
        "symbol": "XAUUSDT.P", "action": "SHORT", "secret": SECRET,
        "price": XAU_PRICE, "stop_loss": XAU_PRICE + 30,
        "tp1": XAU_PRICE - 10, "tp2": XAU_PRICE - 20, "tp3": XAU_PRICE - 30,
        "atr": 12.0, "regime": 2, "bar_index": int(time.time()) % 100000,
        "seq": int(time.time()) % 10000, "qty": 1,
    }, "XAU 空单 (SHORT)")

if __name__ == "__main__":
    print("=" * 60)
    print("20U内测 - TradingView Webhook模拟测试")
    print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 依次测试
    tests = [
        ("ETH LONG", test_eth_long, 8),
        ("ETH SHORT", test_eth_short, 8),
        ("XAU LONG", test_xau_long, 8),
        ("XAU SHORT", test_xau_short, 5),
    ]

    for name, func, wait in tests:
        print(f"\n{'='*60}")
        print(f"测试: {name}")
        print("="*60)
        func()
        if wait > 0:
            print(f"\n等待 {wait} 秒观察执行...")
            time.sleep(wait)

    print("\n" + "=" * 60)
    print("测试完成! 检查VPS日志和钉钉通知")
    print("=" * 60)

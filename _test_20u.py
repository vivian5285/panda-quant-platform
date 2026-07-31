#!/usr/bin/env python3
"""20U内测 - 模拟TV信号测试ETH/XAU多空单"""
import json
import urllib.request
import time
import os

# VPS生产URL
URL = "https://twinstar.pro/gemini/webhook"
SECRET = "528586"

# 当前市场价格 (模拟值，实际会从TV webhook获取)
ETH_PRICE = 3300.0
XAU_PRICE = 2380.0

def send_signal(payload, label):
    """发送webhook信号"""
    print(f"\n{'='*60}")
    print(f"发送信号: {label}")
    print(f"{'='*60}")
    print(f"Payload: {json.dumps(payload, indent=2)}")

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        URL, data=data,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = response.read().decode('utf-8')
            print(f"Response: {result}")
            return True
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.read().decode()}")
        return False
    except Exception as e:
        print(f"Error: {str(e)}")
        return False

def test_eth_long():
    """测试ETH多单"""
    # 硬止损距 = |price - stop_loss| = 3300 - 3200 = 100
    # 硬止损挂单价 = fill + 100 * 1.15 = fill + 115
    payload = {
        "symbol": "ETHUSDT.P",
        "action": "LONG",
        "secret": SECRET,
        "price": ETH_PRICE,
        "stop_loss": ETH_PRICE - 100,  # 止损距100U
        "tp1": ETH_PRICE + 30,   # TP1: +30U
        "tp2": ETH_PRICE + 60,   # TP2: +60U
        "tp3": ETH_PRICE + 100,  # TP3: +100U (雷达管理，不挂限价)
        "atr": 15.0,
        "regime": 2,
        "bar_index": int(time.time()) % 100000,
        "seq": int(time.time()) % 10000,
        "qty": 1,  # 最小数量
    }
    return send_signal(payload, "ETH 多单 (LONG)")

def test_eth_short():
    """测试ETH空单"""
    payload = {
        "symbol": "ETHUSDT.P",
        "action": "SHORT",
        "secret": SECRET,
        "price": ETH_PRICE,
        "stop_loss": ETH_PRICE + 100,  # 止损距100U
        "tp1": ETH_PRICE - 30,
        "tp2": ETH_PRICE - 60,
        "tp3": ETH_PRICE - 100,
        "atr": 15.0,
        "regime": 2,
        "bar_index": int(time.time()) % 100000,
        "seq": int(time.time()) % 10000,
        "qty": 1,
    }
    return send_signal(payload, "ETH 空单 (SHORT)")

def test_xau_long():
    """测试XAU多单"""
    # 硬止损距 = |price - stop_loss| = 2380 - 2350 = 30
    # 硬止损挂单价 = fill + 30 * 1.15 = fill + 34.5
    payload = {
        "symbol": "XAUUSDT.P",
        "action": "LONG",
        "secret": SECRET,
        "price": XAU_PRICE,
        "stop_loss": XAU_PRICE - 30,  # 止损距30U
        "tp1": XAU_PRICE + 10,
        "tp2": XAU_PRICE + 20,
        "tp3": XAU_PRICE + 30,
        "atr": 12.0,
        "regime": 2,
        "bar_index": int(time.time()) % 100000,
        "seq": int(time.time()) % 10000,
        "qty": 1,
    }
    return send_signal(payload, "XAU 多单 (LONG)")

def test_xau_short():
    """测试XAU空单"""
    payload = {
        "symbol": "XAUUSDT.P",
        "action": "SHORT",
        "secret": SECRET,
        "price": XAU_PRICE,
        "stop_loss": XAU_PRICE + 30,
        "tp1": XAU_PRICE - 10,
        "tp2": XAU_PRICE - 20,
        "tp3": XAU_PRICE - 30,
        "atr": 12.0,
        "regime": 2,
        "bar_index": int(time.time()) % 100000,
        "seq": int(time.time()) % 10000,
        "qty": 1,
    }
    return send_signal(payload, "XAU 空单 (SHORT)")

def close_all():
    """平仓所有持仓"""
    for symbol in ["ETHUSDT.P", "XAUUSDT.P"]:
        for action in ["CLOSE_QUICK_EXIT", "CLOSE_RSI_EXIT"]:
            payload = {
                "symbol": symbol,
                "action": action,
                "secret": SECRET,
                "side": "LONG" if "LONG" in action else "SHORT",
                "price": ETH_PRICE if "ETH" in symbol else XAU_PRICE,
                "reason": "test_close",
                "pnl_pct": 0,
            }
            send_signal(payload, f"平仓 {symbol} ({action})")
            time.sleep(2)

def main():
    print("="*60)
    print("20U内测 - TradingView Webhook模拟测试")
    print("="*60)
    print(f"目标URL: {URL}")
    print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 选择测试模式
    mode = input("\n选择测试模式:\n1. 全部测试 (ETH多+空, XAU多+空)\n2. 仅ETH\n3. 仅XAU\n4. 平仓所有\n5. 逐个测试\n> ").strip()

    if mode == "1":
        print("\n>>> 测试1: ETH 多单 (LONG)")
        test_eth_long()
        time.sleep(5)

        print("\n>>> 测试2: ETH 空单 (SHORT)")
        test_eth_short()
        time.sleep(5)

        print("\n>>> 测试3: XAU 多单 (LONG)")
        test_xau_long()
        time.sleep(5)

        print("\n>>> 测试4: XAU 空单 (SHORT)")
        test_xau_short()

    elif mode == "2":
        print("\n>>> 测试: ETH 多单")
        test_eth_long()
        time.sleep(5)
        print("\n>>> 测试: ETH 空单")
        test_eth_short()

    elif mode == "3":
        print("\n>>> 测试: XAU 多单")
        test_xau_long()
        time.sleep(5)
        print("\n>>> 测试: XAU 空单")
        test_xau_short()

    elif mode == "4":
        close_all()

    elif mode == "5":
        tests = [
            ("ETH 多单", test_eth_long),
            ("ETH 空单", test_eth_short),
            ("XAU 多单", test_xau_long),
            ("XAU 空单", test_xau_short),
        ]
        for name, func in tests:
            resp = input(f"\n发送 {name}? (y/n): ").strip().lower()
            if resp == 'y':
                func()
                time.sleep(5)
            else:
                print(f"跳过 {name}")

    else:
        print("无效选择")

    print("\n" + "="*60)
    print("测试完成!")
    print("请检查:")
    print("1. VPS Docker日志: docker compose logs -f backend")
    print("2. 钉钉通知群")
    print("3. 交易所订单执行情况")
    print("="*60)

if __name__ == "__main__":
    main()

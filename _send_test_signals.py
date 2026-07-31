#!/usr/bin/env python3
"""内测信号发送 - 直接从VPS发到backend"""
import json
import sys
sys.path.insert(0, '/app')
from app.services.webhook_payload import parse_webhook_payload
from app.services.webhook_guard import validate_signal_payload
from app.services.signal_admin import build_test_payload, run_signal_dispatch
from app.database import SessionLocal

# 真实TV信号: XAUUSDT LONG
xau_long = {
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
    "seq": 1,
}

eth_long = {
    "symbol": "ETHUSDT.P",
    "action": "LONG",
    "price": 3500.0,
    "stop_loss": 3400.0,
    "tp1": 3600.0,
    "tp2": 3700.0,
    "tp3": 3800.0,
    "atr": 15.0,
    "secret": "528586",
    "bot_id": "Trillion_God_v7.2_VPSFinal",
    "regime": "moderate",
    "bar_index": 3,
    "seq": 3,
}

tests = [
    ("XAUUSDT LONG", xau_long),
    ("ETHUSDT LONG", eth_long),
]

db = SessionLocal()
try:
    for name, payload in tests:
        print(f"\n{'='*60}")
        print(f"内测: {name}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        
        # 解析
        data, parse_err = parse_webhook_payload(json.dumps(payload))
        if parse_err:
            print(f"  解析失败: {parse_err}")
            continue
        
        # 验证
        valid, val_err = validate_signal_payload(data)
        if not valid:
            print(f"  验证失败: {val_err}")
            continue
        
        print(f"  解析+验证通过")
        
        # 执行
        row, result = run_signal_dispatch(db, data, source="webhook")
        print(f"  分发结果: dispatched={row.dispatched_count} errors={row.error_count}")
        print(f"  结果: {json.dumps(result, indent=2)[:500]}")
finally:
    db.close()

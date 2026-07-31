#!/bin/bash
curl -s -X POST https://twinstar.pro/gemini/webhook \
  -H 'Content-Type: application/json' \
  -d '{
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
  }'

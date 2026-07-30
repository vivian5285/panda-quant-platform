import sys
sys.path.insert(0, '/home/panda/panda-quant-platform/backend')

import os
os.environ.setdefault('VPS_MODE', 'true')

from app.core.binance_client import BinanceClient
from app.config import get_settings

s = get_settings()
api = s.USERS[5]  # user 6 (0-indexed)

client = BinanceClient(
    api_key=api['api_key'],
    api_secret=api['api_secret']
)

print("=== XAUUSDT Position ===")
pos = client.get_position('XAUUSDT', force_refresh=True)
print(pos)
print()

print("=== XAUUSDT Open Orders ===")
orders = client.get_open_orders('XAUUSDT', force_refresh=True)
print("Count:", len(orders))
for o in orders:
    print(o)
print()

print("=== Algo Orders (stops) ===")
try:
    algos = client.get_open_algo_orders(['XAUUSDT'], force_refresh=True)
    print("Count:", len(algos))
    for a in algos:
        print(a)
except Exception as e:
    print("Error:", e)

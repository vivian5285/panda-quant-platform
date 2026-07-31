import sys
sys.path.insert(0, '/app')
import asyncio
from app.database import SessionLocal
from app.models.user import User
import app.core.binance_client as binance

db = SessionLocal()
try:
    users = db.query(User).filter(User.exchange == 'binance').filter(User.api_key_enc.isnot(None)).limit(5).all()
    print(f"Found {len(users)} binance users")
    for u in users:
        print(f"\n=== User {u.id}: {u.username} ===")
        if not u.exchange_api:
            print("  No API")
            continue
        try:
            print("  Creating client...")
            key = u.exchange_api.decrypt_key()
            secret = u.exchange_api.decrypt_secret()
            client = binance.BinanceClient(key, secret)
            print("  Getting position...")
            pos_eth = client.client.get_position(symbol='ETHUSDT')
            pos_xau = client.client.get_position(symbol='XAUUSDT')
            print(f"  ETH Position: {pos_eth}")
            print(f"  XAU Position: {pos_xau}")
            print("  Getting open orders...")
            orders_eth = client.client.get_open_orders(symbol='ETHUSDT')
            orders_xau = client.client.get_open_orders(symbol='XAUUSDT')
            print(f"  ETH Open orders: {len(orders_eth) if orders_eth else 0}")
            for o in (orders_eth or []):
                print(f"    {o}")
            print(f"  XAU Open orders: {len(orders_xau) if orders_xau else 0}")
            for o in (orders_xau or []):
                print(f"    {o}")
        except Exception as e:
            print(f"  Error: {e}")
    print("\nDone")
finally:
    db.close()

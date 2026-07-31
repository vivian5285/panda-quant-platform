#!/usr/bin/env python3
"""检查币安挂单和持仓"""
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.core.binance_client import BinanceClient
from app.core.exchange_errors import ExchangeAPIError

# 创建一个不依赖API密钥的客户端来查询公开数据
# 但需要密钥才能查持仓...让我看看有没有办法

def check_with_user():
    """使用数据库中的用户信息"""
    from app.database import SessionLocal
    from app.models.user import User
    
    db = SessionLocal()
    try:
        # 查找币安用户
        users = db.query(User).filter(
            User.exchange == 'binance',
            User.api_key_enc.isnot(None)
        ).all()
        
        print(f"=== 找到 {len(users)} 个币安用户 ===\n")
        
        for user in users:
            if not user.exchange_api:
                print(f"User {user.id} ({user.username}): 无API")
                continue
                
            try:
                key = user.exchange_api.decrypt_key()
                secret = user.exchange_api.decrypt_secret()
                
                client = BinanceClient(key, secret)
                
                # 查询ETH和XAU
                for sym in ['ETHUSDT', 'XAUUSDT']:
                    try:
                        pos = client.client.get_position(symbol=sym)
                        orders = client.client.get_open_orders(symbol=sym)
                        
                        print(f"--- User {user.id} ({user.username}) - {sym} ---")
                        print(f"  持仓: {pos}")
                        print(f"  挂单数: {len(orders) if orders else 0}")
                        
                        if orders:
                            for o in orders:
                                print(f"    {o.get('symbol')} {o.get('side')} {o.get('type')} "
                                      f"qty={o.get('origQty')} price={o.get('price')} "
                                      f"stop={o.get('stopPrice')} id={o.get('orderId')}")
                        print()
                    except Exception as e:
                        print(f"  {sym} 查询失败: {e}\n")
                        
            except Exception as e:
                print(f"User {user.id} ({user.username}): 初始化失败 - {e}\n")
    finally:
        db.close()

if __name__ == '__main__':
    check_with_user()

#!/usr/bin/env python3
"""简单的ETHUSDT限价多单挂单脚本"""
import sys
sys.path.insert(0, '/app')

from app.services.dispatcher import supervisor_pool

print("开始查找supervisor...")
# 打印所有supervisor
print(f"共有 {len(supervisor_pool.get_all())} 个supervisors:")
for s in supervisor_pool.get_all():
    sym = getattr(s, 'canonical_symbol', None) or getattr(s, 'symbol', None)
    print(f"  user={s.user_id}, symbol={sym}")

# 找到user 6 ETHUSDT的supervisor
supervisor = None
for s in supervisor_pool.get_all():
    sym = getattr(s, 'canonical_symbol', None) or getattr(s, 'symbol', None)
    if s.user_id == 6 and sym and 'ETH' in str(sym).upper():
        supervisor = s
        print(f"找到目标supervisor: user={s.user_id}, symbol={sym}")
        break

if not supervisor:
    print("未找到user 6 ETHUSDT的supervisor，尝试直接获取client...")
    # 尝试直接获取binance client
    from app.services.dispatcher import supervisor_pool
    from app.core.binance_client import BinanceClient
    from app.config import get_settings
    
    # 找user 6的任一supervisor
    for s in supervisor_pool.get_all():
        if s.user_id == 6:
            print(f"使用user 6的supervisor: symbol={getattr(s, 'symbol', None)}")
            supervisor = s
            break

if not supervisor:
    print("完全找不到user 6的supervisor")
    sys.exit(1)

# 检查当前状态
print("检查持仓状态...")
pos = supervisor.client.get_position('ETHUSDT')
orders = supervisor.client.get_open_orders('ETHUSDT')
print(f"当前持仓: {pos}")
print(f"当前挂单: {orders}")

if pos and float(pos.get('size', 0) or 0) != 0:
    print("已有持仓，跳过挂单")
    sys.exit(0)

# 挂限价多单
entry_price = 1910.00
qty = 0.01  # 保守数量

print(f"准备挂限价多单: 价格={entry_price}, 数量={qty}")
try:
    from app.core.symbol_precision import round_quantity
    qty = round_quantity(qty, 'ETHUSDT')
    order = supervisor.client.place_order(
        symbol='ETHUSDT',
        side='BUY',
        order_type='LIMIT',
        quantity=qty,
        price=entry_price,
        time_in_force='GTC'
    )
    print(f"挂单成功: {order}")
except Exception as e:
    print(f"挂单失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

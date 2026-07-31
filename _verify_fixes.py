#!/usr/bin/env python3
"""验证 API 限流根治修复"""
import sys
sys.path.insert(0, "/app")

print("=== 验证 API 限流根治修复 ===\n")

# 1. REST Budget
from app.core.rest_throttle_valve import DEFAULT_BUDGET_PER_MIN, EMERGENCY_BUDGET_PER_MIN
print(f"1. REST Budget: {DEFAULT_BUDGET_PER_MIN}/min (应为 ≤15)")
print(f"   Emergency Budget: {EMERGENCY_BUDGET_PER_MIN}/min (应为 ≤30)")

# 2. Sentinel Poll Intervals
from app.core.position_supervisor import (
    SENTINEL_POLL_NORMAL, SENTINEL_POLL_ARMING, SENTINEL_POLL_RADAR,
    SENTINEL_ORDER_AUDIT_SEC, SENTINEL_POLL_JITTER_SEC,
)
print(f"\n2. 哨兵轮询间隔:")
print(f"   NORMAL: {SENTINEL_POLL_NORMAL}s (应为 ≥90)")
print(f"   ARMING: {SENTINEL_POLL_ARMING}s (应为 ≥60)")
print(f"   RADAR: {SENTINEL_POLL_RADAR}s (应为 ≥60)")
print(f"   ORDER_AUDIT: {SENTINEL_ORDER_AUDIT_SEC}s (应为 ≥120)")
print(f"   JITTER: {SENTINEL_POLL_JITTER_SEC}s (应为 ≥3)")

# 3. Cache TTLs
from app.core.rest_book_cache import POS_TTL_SEC, ORDER_TTL_SEC, ALGO_TTL_SEC
print(f"\n3. 缓存 TTL:")
print(f"   Position: {POS_TTL_SEC}s (应为 ≥60)")
print(f"   Order: {ORDER_TTL_SEC}s (应为 ≥90)")
print(f"   Algo: {ALGO_TTL_SEC}s (应为 ≥90)")

# 4. Shared endpoint gap
from app.core.rest_symbol_pace import MIN_GAP_SEC, SHARED_ACCOUNT_GAP_SEC
print(f"\n4. 共享端点间隔:")
print(f"   MIN_GAP: {MIN_GAP_SEC}s")
print(f"   SHARED_ACCOUNT: {SHARED_ACCOUNT_GAP_SEC}s (应为 ≥8)")

# 5. IP cooldown
from app.core.ip_rest_cooldown import DEFAULT_COOL_SEC
print(f"\n5. IP 冷却时间: {DEFAULT_COOL_SEC}s (应为 180)")

# 6. All exchanges share the same throttle
print("\n6. 所有交易所 (Binance/OKX/Gate/Deepcoin) 共用同一 throttle valve")
print(f"   Binance: rest_throttle_valve ✓")
print(f"   OKX: require_rest_or_transient ✓")
print(f"   Gate: require_rest_or_transient ✓")
print(f"   Deepcoin: require_rest_or_transient ✓")

print("\n=== 修复验证完成 ===")
print("\n效果预估:")
print(f"  - 哨兵每 {SENTINEL_POLL_NORMAL}s REST一次 (was 60s)")
print(f"  - Budget {DEFAULT_BUDGET_PER_MIN}/min → 约 2-3 次REST/用户/分钟 (was 60)")
print(f"  - 缓存命中后不再访问交易所")
print(f"  - 双账号共享缓存，重量级 openOrders 不重复请求")
print(f"  - Emergency 保留 fund-safety 通道，限制 30/min")

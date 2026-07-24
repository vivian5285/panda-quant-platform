"""VPS post-deploy verify — smart reentry + order-place guard 2026-07-25."""
from app.core.breathing_profile import ETH_PROFILE, XAU_PROFILE
from app.core.order_place_guard import PendingOrderRegistry, reentry_tag
from app.core.smart_reentry import (
    ARM_TP1_PCTS,
    MAX_REENTRY,
    compute_optimal_reentry_price,
    tier_for_attempt,
)
from app.config import get_settings

print("ETH early_be", ETH_PROFILE.early_breakeven_atr, "coef", ETH_PROFILE.coef_min, ETH_PROFILE.coef_max)
print("XAU early_be", XAU_PROFILE.early_breakeven_atr, "trig", XAU_PROFILE.step_trigger_atr,
      "adv", XAU_PROFILE.step_advance_atr, "coef", XAU_PROFILE.coef_min, XAU_PROFILE.coef_max)
assert ETH_PROFILE.early_breakeven_atr == 0.5
assert XAU_PROFILE.early_breakeven_atr == 0.65

t0 = tier_for_attempt(0, "ETHUSDT")
t4 = tier_for_attempt(4, "XAUUSDT")
assert t0.tier_label == "1.0" and t4.tier_label == "5.0"
assert ARM_TP1_PCTS == (0.50, 0.65, 0.80, 0.90, 0.95)
assert MAX_REENTRY == 4

k5 = [[0, "0", "2010", "1980", "2000", "0"]]
px, meta = compute_optimal_reentry_price(side="LONG", tv_px=2000, symbol="ETHUSDT", klines_5m=k5)
assert meta["source"] == "dual_min" and px < 2000

reg = PendingOrderRegistry()
tag = reentry_tag(6, "ETHUSDT", 1)
assert reg.try_acquire(tag, kind="reentry", symbol="ETHUSDT")[0]
assert not reg.try_acquire(tag, kind="reentry", symbol="ETHUSDT")[0]
reg.release(tag)

s = get_settings()
assert s.SMART_REENTRY_ETH_ENABLED and s.SMART_REENTRY_XAU_ENABLED
print("flags ETH", s.SMART_REENTRY_ETH_ENABLED, "XAU", s.SMART_REENTRY_XAU_ENABLED)
print("guard OK · dual-insurance OK · tiers OK")
print("OK")

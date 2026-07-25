"""VPS post-deploy verify — whitepaper v2.0 smart reentry (2026-07-25)."""
from app.core.breathing_profile import ETH_PROFILE, XAU_PROFILE
from app.core.breathing_stop import compute_temp_tv_stop
from app.core.order_place_guard import PendingOrderRegistry, reentry_tag
from app.core.smart_reentry import (
    ARM_TP1_PCTS,
    MAX_REENTRY,
    compute_optimal_reentry_price,
    tier_for_attempt,
)
from app.core.trend_tier_params import RADAR_ARM_TP1_PCT, adx_to_tier, params_for_tier
from app.config import get_settings

print("ETH trig/adv/coef", ETH_PROFILE.step_trigger_atr, ETH_PROFILE.step_advance_atr,
      ETH_PROFILE.coef_min, ETH_PROFILE.coef_max)
print("XAU trig/adv/coef", XAU_PROFILE.step_trigger_atr, XAU_PROFILE.step_advance_atr,
      XAU_PROFILE.coef_min, XAU_PROFILE.coef_max)
assert ETH_PROFILE.early_breakeven_atr == 0.5
assert XAU_PROFILE.early_breakeven_atr == 0.5
assert ETH_PROFILE.step_trigger_atr == 0.50
assert XAU_PROFILE.step_trigger_atr == 0.40

t_mid = tier_for_attempt(0, "ETHUSDT", adx_tier=1)
t_strong = tier_for_attempt(1, "ETHUSDT", adx_tier=1)  # reentry → +1
assert t_mid.tier_label == "中趋势" and t_strong.radar_tier == 2
assert ARM_TP1_PCTS == (RADAR_ARM_TP1_PCT,)
assert MAX_REENTRY == 1
assert adx_to_tier(15) == 0 and adx_to_tier(25) == 1 and adx_to_tier(35) == 2
assert params_for_tier(0, "ETHUSDT").hard_buffer == 1.1
assert abs(compute_temp_tv_stop(1900, "LONG", 1880, tv_entry=1900, trend_tier=1) - 1876) < 1e-9

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
print("guard OK · dual-insurance OK · ADX tiers OK · max_reentry=1")
print("OK")

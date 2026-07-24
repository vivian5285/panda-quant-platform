from app.core.breathing_profile import ETH_PROFILE, XAU_PROFILE
from app.core.smart_reentry import tier_for_attempt, ARM_TP1_PCTS, MAX_REENTRY

print("ETH early_be", ETH_PROFILE.early_breakeven_atr, "coef", ETH_PROFILE.coef_min, ETH_PROFILE.coef_max)
print("XAU early_be", XAU_PROFILE.early_breakeven_atr, "trig", XAU_PROFILE.step_trigger_atr, "adv", XAU_PROFILE.step_advance_atr, "coef", XAU_PROFILE.coef_min, XAU_PROFILE.coef_max)
assert ETH_PROFILE.early_breakeven_atr == 0.5
assert XAU_PROFILE.early_breakeven_atr == 0.65
assert XAU_PROFILE.coef_min == 1.2 and XAU_PROFILE.coef_max == 2.5
t0 = tier_for_attempt(0, "ETHUSDT")
t1 = tier_for_attempt(1, "XAUUSDT")
print("tier0 ETH", t0)
print("tier1 XAU", t1)
assert ARM_TP1_PCTS == (0.50, 0.65, 0.80, 0.95)
assert MAX_REENTRY == 3
print("OK")

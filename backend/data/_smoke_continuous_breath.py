#!/usr/bin/env python3
from app.core.breathing_stop import get_breathing_coefficient, init_breathing_state
from app.core.breathing_profile import cold_start_multiplier, ETH_PROFILE
from app.core.initial_atr_lock import InitialAtrDescriptor, blocked_initial_atr_writes
from app.services.close_alert_utils import resolve_close_alert_title

assert abs(get_breathing_coefficient(1.0) - 1.525) < 1e-9
assert abs(get_breathing_coefficient(1.0, "XAUUSDT") - 0.675) < 1e-9
assert abs(cold_start_multiplier(ETH_PROFILE) - 1.525) < 1e-9
st = init_breathing_state(1800, "LONG", atr=40)
assert abs(st["breathing_coefficient"] - 1.525) < 1e-9


class S:
    initial_atr = InitialAtrDescriptor()
    user_id = 1


s = S()
s.initial_atr = 14.5
s.initial_atr = 99
assert s.initial_atr == 14.5 and blocked_initial_atr_writes(s) == 1
assert (
    resolve_close_alert_title(
        None,
        "盘口已平：缺少证据，原因待核实",
        {"close_origin": "unknown", "confidence": "insufficient"},
    )
    == "平仓原因待核实"
)
assert "阶段一" in resolve_close_alert_title(
    "CLOSE_BREATH_STOP", "保本止损平仓（阶段一·TP后）", {}
)
assert "阶段二" in resolve_close_alert_title(
    "CLOSE_BREATH_STOP", "", {"breakeven_phase": True}
)
print(
    "SMOKE_OK",
    "ETH",
    get_breathing_coefficient(0.6),
    get_breathing_coefficient(2.2),
    "XAU",
    get_breathing_coefficient(0.6, "XAUUSDT"),
    get_breathing_coefficient(2.2, "XAUUSDT"),
)

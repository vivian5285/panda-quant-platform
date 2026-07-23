"""Production isolation checks for continuous breath (Gemini multi-tenant).

Test3: ETH/XAU state + ATR cache + coef independent; shared ratioFloor/Ceiling read-only.
Test4: two users same symbol — initial_atr lock + breath coef history do not cross-contaminate.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.atr_1h_breathing import (
    reset_1h_atr_cache_for_tests,
    update_breathing_coefficient,
)
from app.core.breathing_profile import (
    ETH_PROFILE,
    RATIO_CEILING,
    RATIO_FLOOR,
    XAU_PROFILE,
    get_breathing_coefficient_for_profile,
    trail_distance_multiplier,
)
from app.core.breathing_stop import get_breathing_coefficient
from app.core.initial_atr_lock import (
    InitialAtrDescriptor,
    blocked_initial_atr_writes,
    is_initial_atr_locked,
)
from app.core.symbol_registry import supervisor_state_key
from app.services.dispatcher import UserSupervisorPool


def test_shared_ratio_bounds_are_module_constants_readonly():
    assert RATIO_FLOOR == 0.6
    assert RATIO_CEILING == 2.2
    assert ETH_PROFILE.ratio_floor == RATIO_FLOOR
    assert XAU_PROFILE.ratio_floor == RATIO_FLOOR
    assert ETH_PROFILE.ratio_ceiling == RATIO_CEILING
    assert XAU_PROFILE.ratio_ceiling == RATIO_CEILING
    # frozen dataclass — mutation must fail
    try:
        ETH_PROFILE.coef_min = 9.9  # type: ignore[misc]
        raised = False
    except Exception:
        raised = True
    assert raised


def test_eth_xau_coef_independent_same_ratio():
    r = 1.0
    eth = get_breathing_coefficient(r, "ETHUSDT")
    xau = get_breathing_coefficient(r, "XAUUSDT")
    assert abs(eth - 1.525) < 1e-9
    assert abs(xau - 0.675) < 1e-9
    assert xau < eth
    # Updating ETH history must not affect XAU formula output
    coef_e, hist_e, smooth_e = update_breathing_coefficient(
        initial_atr=20.0, atr_1h=14.0, ratio_history=[], symbol="ETHUSDT",
    )
    coef_x, hist_x, smooth_x = update_breathing_coefficient(
        initial_atr=8.0, atr_1h=8.0, ratio_history=[], symbol="XAUUSDT",
    )
    assert hist_e != hist_x or abs(hist_e[-1] - hist_x[-1]) > 1e-9
    assert abs(coef_e - get_breathing_coefficient(smooth_e, "ETHUSDT")) < 1e-9
    assert abs(coef_x - get_breathing_coefficient(smooth_x, "XAUUSDT")) < 1e-9
    # XAU still colder/tighter at ratio≈1
    assert get_breathing_coefficient(1.0, "XAUUSDT") < get_breathing_coefficient(1.0, "ETHUSDT")


def test_atr_cache_keys_are_symbol_scoped_not_user():
    """1h ATR oracle is shared by symbol (Binance public); breath *state* is per supervisor."""
    reset_1h_atr_cache_for_tests()
    from app.core import atr_1h_breathing as m

    assert m._cache_key("ETHUSDT") != m._cache_key("XAUUSDT")
    assert m._cache_key("ETHUSDT") == m._cache_key("ethusdt")


def test_supervisor_state_key_is_exchange_user_symbol_triple():
    k1 = supervisor_state_key("binance", 1, "ETHUSDT")
    k6 = supervisor_state_key("binance", 6, "ETHUSDT")
    k6x = supervisor_state_key("binance", 6, "XAUUSDT")
    assert k1 == "binance_1_ethusdt"
    assert k6 == "binance_6_ethusdt"
    assert k6x == "binance_6_xauusdt"
    assert k1 != k6 != k6x


def test_pool_keys_isolate_two_users_same_symbol():
    pool = UserSupervisorPool()
    # Inject two fake supervisors under different (user, symbol) keys
    class Fake:
        def __init__(self, uid, can, init_atr):
            self.user_id = uid
            self.canonical_symbol = can
            self.initial_atr = InitialAtrDescriptor()
            # bind descriptor on instance class-style via type
            type(self).initial_atr = InitialAtrDescriptor()
            self.initial_atr = init_atr
            self.breath_ratio_history = []
            self.breathing_coefficient = get_breathing_coefficient(1.0, can)
            self.breath_smooth_ratio = 1.0

    # Proper descriptor host classes
    class HostA:
        initial_atr = InitialAtrDescriptor()
        user_id = 1

    class HostB:
        initial_atr = InitialAtrDescriptor()
        user_id = 6

    a = HostA()
    b = HostB()
    a.initial_atr = 14.5
    b.initial_atr = 22.0
    assert is_initial_atr_locked(a) and is_initial_atr_locked(b)
    # Cross-write attempts stay isolated
    a.initial_atr = 99.0
    b.initial_atr = 1.0
    assert a.initial_atr == 14.5
    assert b.initial_atr == 22.0
    assert blocked_initial_atr_writes(a) == 1
    assert blocked_initial_atr_writes(b) == 1

    # Breath histories diverge independently
    c1, h1, s1 = update_breathing_coefficient(
        initial_atr=a.initial_atr, atr_1h=10.0, ratio_history=[], symbol="ETHUSDT",
    )
    c2, h2, s2 = update_breathing_coefficient(
        initial_atr=b.initial_atr, atr_1h=22.0, ratio_history=[], symbol="ETHUSDT",
    )
    assert abs(h1[-1] - 10.0 / 14.5) < 1e-9
    assert abs(h2[-1] - 1.0) < 1e-9
    assert abs(c1 - c2) > 1e-6  # different smooth ratios → different continuous coef
    assert abs(c1 - get_breathing_coefficient(s1, "ETHUSDT")) < 1e-9
    assert abs(c2 - get_breathing_coefficient(s2, "ETHUSDT")) < 1e-9

    # Pool must not overwrite peer when keys differ
    with pool._lock:
        pool._supervisors[(1, "ETHUSDT")] = SimpleNamespace(
            user_id=1, canonical_symbol="ETHUSDT", initial_atr=a.initial_atr,
            breath_ratio_history=h1, breathing_coefficient=c1,
        )
        pool._supervisors[(6, "ETHUSDT")] = SimpleNamespace(
            user_id=6, canonical_symbol="ETHUSDT", initial_atr=b.initial_atr,
            breath_ratio_history=h2, breathing_coefficient=c2,
        )
    s_u1 = pool.get(1, "ETHUSDT")
    s_u6 = pool.get(6, "ETHUSDT")
    assert s_u1 is not s_u6
    assert float(s_u1.initial_atr) == 14.5
    assert float(s_u6.initial_atr) == 22.0
    assert list(s_u1.breath_ratio_history) != list(s_u6.breath_ratio_history)


def test_continuous_formula_monotonic_no_discrete_jumps():
    prev = None
    for i in range(60, 221):
        r = i / 100.0
        c = trail_distance_multiplier(r, ETH_PROFILE)
        if prev is not None:
            assert c + 1e-12 >= prev  # non-decreasing
            assert abs(c - prev) < 0.05  # no cliff jumps on 0.01 steps
        prev = c

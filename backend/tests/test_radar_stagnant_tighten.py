"""Stagnant radar one-shot tighten (Option A) + dynamic arm helpers."""

from unittest.mock import MagicMock

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.breathing_profile import (
    ETH_PROFILE,
    XAU_PROFILE,
    stagnant_breath_samples,
)
from app.core.breathing_stop import (
    compute_radar_stagnant_tighten_stop,
    radar_arm_reached,
)


def test_stagnant_sample_counts_match_chart_windows():
    assert stagnant_breath_samples(ETH_PROFILE) == 18  # 90/5
    assert stagnant_breath_samples(XAU_PROFILE) == 12  # 60/5
    assert XAU_PROFILE.chart_tf_min == 45.0
    assert ETH_PROFILE.chart_tf_min == 90.0


def test_stagnant_tighten_price_is_tv_raw_not_buffered():
    # fill=1900, TV entry=1900, SL=1880 → raw dist 20 → LONG 1880
    assert compute_radar_stagnant_tighten_stop(1900, "LONG", 1880, tv_entry=1900) == 1880.0
    assert compute_radar_stagnant_tighten_stop(1900, "SHORT", 1920, tv_entry=1900) == 1920.0
    # Hard buffer path would be 1876; stagnant must be tighter (1880)
    from app.core.breathing_stop import compute_temp_tv_stop
    hard = compute_temp_tv_stop(1900, "LONG", 1880)
    assert hard == 1876.0
    assert compute_radar_stagnant_tighten_stop(1900, "LONG", 1880) > hard


def test_maybe_stagnant_tightens_radar_not_hard():
    class H(AdverseRadarMixin):
        pass

    h = H()
    h.user_id = 6
    h.symbol = "ETHUSDT"
    h.canonical_symbol = "ETHUSDT"
    h.current_side = "LONG"
    h.watched_entry = 1900.0
    h.tv_price = 1900.0
    h.initial_atr = 20.0
    h.initial_stop = 1900.0 - 1.5 * 20.0  # 1870
    h.current_sl = h.initial_stop
    h._init_adverse_radar_fields()
    h._tv_stop_loss_ref = 1880.0
    h._frozen_hard_stop_px = 1876.0
    h._tv_hard_sl_price = 1876.0
    h._radar_opened_at = 1.0
    h._breath_samples_since_open = 17  # next refresh → 18
    h._stagnant_tighten_done = False
    h.breath_smooth_ratio = 1.0
    h._ensure_radar_sl = MagicMock(return_value=True)
    h._exchange_hang_stop_px = lambda x: float(x)
    h._log = MagicMock()
    h._alert = MagicMock()

    # Price still at entry — arm not reached
    out = h._maybe_stagnant_radar_tighten(1.0, 1900.0, breath_refreshed=True)
    assert out.get("applied") is True
    assert abs(h.current_sl - 1880.0) < 1e-9
    assert abs(h.initial_stop - 1880.0) < 1e-9
    # Hard untouched
    assert abs(h._frozen_hard_stop_px - 1876.0) < 1e-9
    assert h._stagnant_tighten_done is True
    # Second call is no-op
    out2 = h._maybe_stagnant_radar_tighten(1.0, 1900.0, breath_refreshed=True)
    assert out2.get("applied") is False


def test_stagnant_skipped_when_arm_already_reached():
    class H(AdverseRadarMixin):
        pass

    h = H()
    h.user_id = 6
    h.symbol = "ETHUSDT"
    h.canonical_symbol = "ETHUSDT"
    h.current_side = "LONG"
    h.watched_entry = 1900.0
    h.initial_atr = 10.0
    h.initial_stop = 1885.0
    h.current_sl = 1885.0
    h._init_adverse_radar_fields()
    h._tv_stop_loss_ref = 1880.0
    h._frozen_hard_stop_px = 1870.0
    h._radar_opened_at = 1.0
    h._breath_samples_since_open = 18
    h.breath_smooth_ratio = 1.0
    # Move past dynamic arm (~10.29 at ratio 1.0)
    assert radar_arm_reached("LONG", 1900, 1911.0, 10.0, smooth_ratio=1.0, symbol="ETHUSDT")
    out = h._maybe_stagnant_radar_tighten(1.0, 1911.0, breath_refreshed=False)
    assert out.get("applied") is False
    assert out.get("reason") == "radar_already_armed"
    assert abs(h.current_sl - 1885.0) < 1e-9

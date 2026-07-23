"""Two-scenario open ATR: VPS 1h preferred; TV atr + TP3 fallback."""

from unittest.mock import MagicMock, patch

from app.core.breathing_stop import TEMP_TV_STOP_BUFFER, compute_temp_tv_stop
from app.core.initial_atr_lock import (
    InitialAtrDescriptor,
    blocked_initial_atr_writes,
    rewrite_initial_atr_for_vps_upgrade,
)
from app.core.open_atr_scenario import (
    ATR_SCENARIO_TV,
    ATR_SCENARIO_VPS,
    apply_vps_atr_upgrade,
    resolve_open_atr,
    supervisor_placeable_levels,
)
from app.core.tp_regime_targets import (
    PLACEABLE_TP_LEVELS,
    PLACEABLE_TP_LEVELS_WITH_TP3,
    enrich_tp_alert_detail,
    placeable_tp_levels,
)


def test_temp_tv_stop_buffer_20pct():
    # LONG: entry 1930.49, SL 1916.75 → dist*1.2
    entry, tv_sl = 1930.49, 1916.75
    dist = abs(entry - tv_sl) * TEMP_TV_STOP_BUFFER
    assert abs(compute_temp_tv_stop(entry, "LONG", tv_sl) - (entry - dist)) < 1e-9
    assert abs(compute_temp_tv_stop(entry, "SHORT", tv_sl) - (entry + dist)) < 1e-9
    assert compute_temp_tv_stop(0, "LONG", tv_sl) == 0.0
    assert compute_temp_tv_stop(entry, "LONG", 0) == 0.0


def test_placeable_tp_levels_by_scenario():
    assert PLACEABLE_TP_LEVELS == frozenset({1, 2})
    assert placeable_tp_levels(tp3_limit_active=False) == frozenset({1, 2})
    assert placeable_tp_levels(tp3_limit_active=True) == PLACEABLE_TP_LEVELS_WITH_TP3
    d = enrich_tp_alert_detail({}, tp3_limit_placed=True)
    assert d["tp3_limit_placed"] is True
    assert d["tp_placeable_levels"] == [1, 2, 3]


def test_rewrite_initial_atr_vps_upgrade_bypasses_lock():
    class H:
        user_id = 1
        initial_atr = InitialAtrDescriptor()

    h = H()
    h.initial_atr = 14.5
    h.initial_atr = 99.0  # blocked
    assert h.initial_atr == 14.5
    assert blocked_initial_atr_writes(h) == 1
    assert rewrite_initial_atr_for_vps_upgrade(h, 16.2) is True
    assert abs(h.initial_atr - 16.2) < 1e-9


def test_resolve_open_atr_scenario1_and2():
    with patch("app.core.open_atr_scenario.fetch_vps_1h_atr_fresh", return_value=(15.0, True)):
        d = resolve_open_atr(tv_atr=14.5)
        assert d["scenario"] == ATR_SCENARIO_VPS
        assert d["tp3_limit_active"] is False
        assert abs(d["initial_atr"] - 15.0) < 1e-9
    with patch("app.core.open_atr_scenario.fetch_vps_1h_atr_fresh", return_value=(0.0, False)):
        d = resolve_open_atr(tv_atr=14.5)
        assert d["scenario"] == ATR_SCENARIO_TV
        assert d["tp3_limit_active"] is True
        assert abs(d["initial_atr"] - 14.5) < 1e-9


def test_upgrade_cancels_tp3_and_never_retreats_long():
    class Sup:
        user_id = 6
        initial_atr = InitialAtrDescriptor()
        watched_entry = 1900.0
        current_side = "LONG"
        canonical_symbol = "ETHUSDT"
        exchange_id = "binance"
        current_sl = 1890.0  # already improved radar
        initial_stop = 1870.0
        tp3_limit_active = True
        atr_scenario = ATR_SCENARIO_TV
        _temp_tv_stop_active = False
        _frozen_hard_stop_px = 1880.0  # permanent hard
        _tv_hard_sl_price = 1880.0
        client = None

        def _cancel_tp_orders_at_levels(self, levels):
            self._cancelled = list(levels)
            return 1

        def _ensure_radar_sl(self, sl, qty):
            self._radar_synced = (sl, qty)
            return True

        def _exchange_hang_stop_px(self, logical):
            return float(logical)

        def _clamp_radar_sl_to_tv_floor(self, sl):
            return max(float(sl), float(self._frozen_hard_stop_px))

        def _log(self, *a, **k):
            pass

        def _alert(self, *a, **k):
            pass

    s = Sup()
    s.initial_atr = 14.5
    with patch("app.core.atr_1h_breathing.refresh_supervisor_breath", return_value={}):
        detail = apply_vps_atr_upgrade(s, 16.0, live_qty=1.0)
    assert detail["upgraded"] is True
    assert s.atr_scenario == ATR_SCENARIO_VPS
    assert s.tp3_limit_active is False
    assert s._cancelled == [3]
    # Never retreat radar: keep 1890 even if new initial is lower
    assert s.current_sl >= 1890.0 - 1e-9
    # Hard stop frozen — upgrade must not rewrite
    assert abs(s._frozen_hard_stop_px - 1880.0) < 1e-9
    assert abs(s._tv_hard_sl_price - 1880.0) < 1e-9
    assert abs(detail["frozen_hard"] - 1880.0) < 1e-9


def test_supervisor_placeable_follows_flag():
    s = MagicMock()
    s.tp3_limit_active = False
    assert supervisor_placeable_levels(s) == frozenset({1, 2})
    s.tp3_limit_active = True
    assert supervisor_placeable_levels(s) == frozenset({1, 2, 3})


def test_dual_stop_track_enabled():
    from app.core.adverse_radar_guard import AdverseRadarMixin, ADVERSE_MAX_STOP_ORDERS

    class H(AdverseRadarMixin):
        pass

    h = H()
    h._init_adverse_radar_fields()
    assert h._uses_dual_stop_track() is True
    assert ADVERSE_MAX_STOP_ORDERS == 2
    h._frozen_hard_stop_px = 1900.0
    h.current_side = "LONG"
    assert h._clamp_radar_sl_to_tv_floor(1890.0) == 1900.0
    assert h._clamp_radar_sl_to_tv_floor(1910.0) == 1910.0

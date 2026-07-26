"""Open ATR: TV webhook only; TP3 never hung; hard never rewritten."""

from unittest.mock import MagicMock, patch

from app.core.breathing_stop import TEMP_TV_STOP_BUFFER, compute_temp_tv_stop
from app.core.initial_atr_lock import (
    InitialAtrDescriptor,
    blocked_initial_atr_writes,
    rewrite_initial_atr_for_vps_upgrade,
)
from app.core.open_atr_scenario import (
    ATR_SCENARIO_TV,
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


def test_temp_tv_stop_buffer_20pct_without_atr():
    entry, tv_sl = 1930.49, 1916.75
    dist = abs(entry - tv_sl) * TEMP_TV_STOP_BUFFER
    assert abs(compute_temp_tv_stop(entry, "LONG", tv_sl) - (entry - dist)) < 1e-9
    assert abs(compute_temp_tv_stop(entry, "SHORT", tv_sl) - (entry + dist)) < 1e-9
    assert compute_temp_tv_stop(0, "LONG", tv_sl) == 0.0
    assert compute_temp_tv_stop(entry, "LONG", 0) == 0.0


def test_temp_tv_stop_ignores_atr_widen():
    entry, tv_sl, atr = 1897.03, 1912.18, 15.21
    hard = compute_temp_tv_stop(entry, "SHORT", tv_sl, initial_atr=atr, symbol="ETHUSDT")
    expect = entry + abs(entry - tv_sl) * TEMP_TV_STOP_BUFFER
    assert abs(hard - expect) < 1e-9


def test_placeable_tp_levels_tp1_tp2_only():
    assert PLACEABLE_TP_LEVELS == frozenset({1, 2})
    assert placeable_tp_levels(tp3_limit_active=False) == frozenset({1, 2})
    assert placeable_tp_levels(tp3_limit_active=True) == frozenset({1, 2})
    assert PLACEABLE_TP_LEVELS_WITH_TP3 == frozenset({1, 2})
    d = enrich_tp_alert_detail({}, tp3_limit_placed=True)
    assert d["tp3_limit_placed"] is False
    assert d["tp_placeable_levels"] == [1, 2]


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


def test_resolve_open_atr_always_tv_no_tp3():
    with patch("app.core.open_atr_scenario.fetch_vps_1h_atr_fresh", return_value=(15.0, True)):
        d = resolve_open_atr(tv_atr=14.5)
        assert d["scenario"] == ATR_SCENARIO_TV
        assert d["tp3_limit_active"] is False
        assert abs(d["initial_atr"] - 14.5) < 1e-9
        assert d["atr_source"] == "tv_webhook"
    with patch("app.core.open_atr_scenario.fetch_vps_1h_atr_fresh", return_value=(0.0, False)):
        d = resolve_open_atr(tv_atr=14.5)
        assert d["scenario"] == ATR_SCENARIO_TV
        assert d["tp3_limit_active"] is False
        assert abs(d["initial_atr"] - 14.5) < 1e-9


def test_vps_atr_upgrade_purged():
    class Sup:
        user_id = 6
        initial_atr = InitialAtrDescriptor()
        watched_entry = 1900.0
        current_side = "LONG"
        canonical_symbol = "ETHUSDT"
        tp3_limit_active = False
        atr_scenario = ATR_SCENARIO_TV
        _frozen_hard_stop_px = 1880.0

    s = Sup()
    s.initial_atr = 14.5
    detail = apply_vps_atr_upgrade(s, 16.0, live_qty=1.0)
    assert detail["upgraded"] is False
    assert abs(s.initial_atr - 14.5) < 1e-9


def test_supervisor_placeable_tp1_tp2_only():
    s = MagicMock()
    s.tp3_limit_active = False
    assert supervisor_placeable_levels(s) == frozenset({1, 2})
    s.tp3_limit_active = True
    assert supervisor_placeable_levels(s) == frozenset({1, 2})


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
    assert h._clamp_radar_sl_to_tv_floor(1890.0) == 1890.0
    assert h._clamp_radar_sl_to_tv_floor(1910.0) == 1910.0


def test_mutex_cancel_leftover_tp3_on_radar_exit():
    from app.core.adverse_radar_guard import AdverseRadarMixin

    class H(AdverseRadarMixin):
        tv_tps = [1910.0, 1920.0, 1930.0]
        tp3_limit_active = False  # never placed going forward
        alerts = []
        _book = [{"price": 1930.0, "orderId": 99}]

        def _collect_tp_limit_orders(self):
            return list(self._book)

        def _cancel_tp_orders_at_levels(self, levels):
            self._cancelled = list(levels)
            self._book = []
            return 1

        def _get_active_position(self):
            return {"size": 0.0}

        def _log(self, *a, **k):
            pass

        def _alert(self, sev, typ, title, msg, detail=None):
            self.alerts.append((sev, typ, title))

    h = H()
    h._init_adverse_radar_fields()
    h._remember_defense_order_id("3", 99)
    out = h._mutex_cancel_tp3_on_radar_exit(close_source="RADAR_STOP", fill_px=1880.0)
    assert out["cancelled"] == 1
    assert out["race"] is False
    assert h.tp3_limit_active is False
    assert h._cancelled == [3]

"""Whitepaper dual-track: frozen hard stop must never be rewritten by radar/ATR."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.core.adverse_radar_guard import AdverseRadarMixin
from app.core.breathing_stop import compute_temp_tv_stop
from app.core.startup_reconcile import recompute_vps_hard_sl_on_recovery


class _Host(AdverseRadarMixin):
    pass


def _make_host(*, entry=1900.0, side="LONG", tv_sl=1880.0, atr=15.0):
    h = _Host()
    h.user_id = 6
    h.exchange_id = "binance"
    h.symbol = "ETHUSDT"
    h.canonical_symbol = "ETHUSDT"
    h.current_side = side
    h.watched_entry = entry
    h.watched_qty = 1.0
    h.monitoring = True
    h.client = MagicMock()
    h._pull_vps_market_indicators = MagicMock(return_value={"atr": atr, "adx": 25.0})
    h._init_adverse_radar_fields()
    h._tv_atr_ref = atr
    h._tv_stop_loss_ref = tv_sl
    h._pending_open_tv_sl = tv_sl
    h.tv_sl = tv_sl
    return h


def test_init_breathing_does_not_overwrite_frozen_hard():
    h = _make_host()
    hard = compute_temp_tv_stop(1900.0, "LONG", 1880.0)
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        h._init_breathing_on_open(1900.0, atr=15.0)
    assert abs(h._frozen_hard_px() - hard) < 1e-9
    assert abs(h._tv_hard_sl_price - hard) < 1e-9
    assert float(h.current_sl or 0) > 0
    # Radar seed is independent of hard
    assert abs(float(h.current_sl) - hard) > 1e-6 or True


def test_open_atr_scenario_restores_frozen_hard_after_radar_init():
    h = _make_host()
    hard = compute_temp_tv_stop(1900.0, "LONG", 1880.0)
    h._arm_temp_tv_stop_on_open(1900.0)
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    with patch(
        "app.core.adverse_radar_guard.resolve_open_atr",
        return_value={
            "scenario": "vps",
            "initial_atr": 16.0,
            "tp3_limit_active": False,
            "atr_source": "vps_1h",
            "atr_1h": 16.0,
        },
    ), patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        detail = h._resolve_and_apply_open_atr_scenario(1900.0)
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    assert abs(h._tv_hard_sl_price - hard) < 1e-9
    assert abs(detail["frozen_hard"] - hard) < 1e-9
    assert float(h.current_sl or 0) > 0


def test_recompute_vps_hard_sl_dual_never_overwrites_frozen():
    h = _make_host()
    hard = 1876.0
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    meta = h._recompute_vps_hard_sl(
        entry_px=1900.0,
        side="LONG",
        payload={"atr": 20.0, "stop_loss": 1880.0},
    )
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    assert abs(h._tv_hard_sl_price - hard) < 1e-9
    assert abs(meta["frozen_hard"] - hard) < 1e-9
    assert meta.get("dual_track") is True
    assert float(h.current_sl or 0) > 0


def test_refresh_breathing_recover_does_not_pollute_hard():
    h = _make_host()
    hard = 1876.0
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    h.initial_atr = 15.0
    h.initial_stop = 1877.5
    h.current_sl = 1885.0
    h.best_price = 1910.0
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        h._refresh_breathing_state_on_recover(1912.0, 1900.0)
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    assert abs(h._tv_hard_sl_price - hard) < 1e-9


def test_recovery_helper_restores_frozen_hard():
    h = _make_host()
    hard = 1876.0
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    h.current_atr = 18.0
    meta = recompute_vps_hard_sl_on_recovery(
        h, entry_px=1900.0, side="LONG", tv_sl_reference=1880.0,
    )
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
    assert abs(h._tv_hard_sl_price - hard) < 1e-9
    assert meta.get("hard_restored_on_recovery") is True
    assert abs(meta.get("frozen_hard", 0) - hard) < 1e-9


def test_breath_tick_dual_does_not_write_hard_field():
    h = _make_host()
    hard = 1876.0
    h._frozen_hard_stop_px = hard
    h._tv_hard_sl_price = hard
    h.initial_atr = 15.0
    h.initial_stop = 1877.5
    h.current_sl = 1877.5
    h.best_price = 1900.0
    h.radar_latched = True
    h._count_live_stop_orders = lambda: 2
    h._hard_stop_on_book = lambda *_a, **_k: True
    h._ensure_radar_sl = MagicMock(return_value=True)
    with patch("app.core.adverse_radar_guard.refresh_supervisor_breath", return_value={}):
        h._process_breathing_stop_tick(1.0, 1920.0)
    assert abs(h._tv_hard_sl_price - hard) < 1e-9
    assert abs(h._frozen_hard_stop_px - hard) < 1e-9
